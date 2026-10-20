"""CLI: `osw` command. Human-friendly console frontend for the API + steamcmd."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .models import WorkshopItem
from .queue import DownloadManager, JobState
from .settings import DEFAULTS, get, save
from .steam_api import (
    SORTS,
    browse_workshop,
    get_item_details,
    resolve_ids,
    search_games,
)
from .steamcmd import SteamCMD, SteamCMDError

EXIT_OK = 0
EXIT_ERR = 1
EXIT_NOT_OWNED = 2


# --------------------------------------------------------------------- views

def _p(*a):
    print(*a)


def cmd_search(args) -> int:
    games = search_games(" ".join(args.term))
    if not games:
        _p("No games found.")
        return EXIT_ERR
    for g in games:
        _p(f"{g.appid:>10}  {g.name}")
    if games:
        _p(f"\nTip: osw browse {games[0].appid}  to list its workshop mods")
    return EXIT_OK


def cmd_browse(args) -> int:
    appid = int(args.appid)
    page = max(1, args.page)
    per = min(50, max(1, args.count))
    items, total, pages = browse_workshop(
        appid, page=page, per_page=per, sort=args.sort, search_text=" ".join(args.search or [])
    )
    if not items:
        _p(f"No workshop items found (app {appid}, page {page}).")
        return EXIT_ERR
    _p(f"app {appid} — total items {total}, page {page}/{pages or '?'}\n")
    for it in items:
        size = f"{it.file_size / 1e6:.1f}MB" if it.file_size else "?"
        subs = f"{it.subscriptions:,}"
        stars = f"★{it.star_rating:.1f}" if it.star_rating else "-"
        print(f"{it.publishedfileid:>11} {size:>9} {subs:>10} {stars:>5}  {it.title}")
    _p(f"\nTip: osw info {items[0].publishedfileid} | osw download {appid} {items[0].publishedfileid}")
    return EXIT_OK


def cmd_info(args) -> int:
    det = get_item_details(args.fileid)
    if det.error:
        print(det.error)
        return EXIT_ERR
    _p(f"title:      {det.title}")
    _p(f"author:     {det.author or '?'}")
    if det.file_size:
        _p(f"size:       {det.file_size}")
    if det.fileid:
        _p(f"fileid:     {det.fileid}")
    if det.appid:
        _p(f"appid:      {det.appid}")
    if det.author_url:
        _p(f"profile:    {det.author_url}")
    if det.num_ratings:
        _p(f"ratings:    {det.num_ratings}")
    if det.tags:
        _p(f"tags:       {', '.join(det.tags[:8])}")
    if det.required_items:
        _p("required:   " + ", ".join(f"{t or i} ({i})" for i, t in det.required_items[:12]))
    print()
    print((det.description or "(no description)")[:3000])
    return EXIT_OK


def cmd_download(args) -> int:
    appid = int(args.appid)
    try:
        manager = _build_manager(args)
        manager.steamcmd().ensure_installed(log=lambda m: print(m))
    except (SteamCMDError, Exception) as e:
        _p(f"Error: {e}")
        return EXIT_ERR

    failed = False
    for fileid in args.fileid:
        job = manager.add_direct(appid, fileid)
        last_state = None
        while True:
            if job.state is not last_state:
                last_state = job.state
                if job.state is JobState.RUNNING:
                    print(f"[{job.fileid}] downloading {job.title} ...")
            if job.state in (JobState.DONE, JobState.FAILED):
                break
            import time

            time.sleep(0.3)
        if job.state is JobState.FAILED:
            print(f"[{job.fileid}] FAILED: {job.message}")
            failed = True
        else:
            print(f"[{job.fileid}] done → {job.message}")
    return EXIT_ERR if failed else EXIT_OK


def cmd_url(args) -> int:
    text = " ".join(args.text)
    appid, fileids = resolve_ids(text)
    _p(f"appid:   {appid}")
    _p(f"fileids: {fileids}")
    for f in fileids:
        det = get_item_details(f)
        print(f"  - {det.title or '(?)'}  (by {det.author or '?'})")
    return EXIT_OK


def cmd_settings(args) -> int:
    if any(v is not None for v in (args.root, args.username, args.parallel)):
        patch = {}
        if args.root is not None:
            patch["content_root"] = args.root
        if args.username is not None:
            patch["username"] = args.username
        if args.parallel is not None:
            patch["parallel_downloads"] = max(1, args.parallel)
        save(patch)
    s = get("content_root")
    _p("Settings are stored in ~/.config/OpenSteamWorkshop/settings.json")
    _p(f"  content_root = {s!r}")
    _p(f"  username     = {get('username')!r}")
    _p(f"  parallel     = {get('parallel_downloads')}")
    return EXIT_OK


def _build_manager(args) -> DownloadManager:
    username = args.username or (get("username") if not args.anonymous else "") or ""
    password = ""
    if username and not args.anonymous:
        import getpass

        password = getpass.getpass(f"Steam password for {username} (blank = env OSW_PASS): ")
        password = password or __import__("os").environ.get("OSW_PASS", "")
    mgr = DownloadManager(
        content_root=args.out or get("content_root"),
        steamcmd_dir=get("steamcmd_dir") or None,
        username=username,
        password="",
        parallel=get("parallel_downloads"),
        on_log=lambda m: None,
    )
    # password never flows through settings; only in-memory here
    mgr.password = password
    return mgr


# -------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="osw",
        description="Browse and download Steam Workshop content.",
    )
    p.add_argument("--version", action="version", version=f"osw {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search the steam store for games")
    s.add_argument("term", nargs="+")
    s.set_defaults(func=cmd_search)

    b = sub.add_parser("browse", help="list a game's workshop mods")
    b.add_argument("appid")
    b.add_argument("--sort", default="trend", choices=list(SORTS), help="default: trend")
    b.add_argument("--search", nargs="*", default=[], help="text search inside workshop")
    b.add_argument("--page", type=int, default=1)
    b.add_argument("--count", type=int, default=30)
    b.set_defaults(func=cmd_browse)

    i = sub.add_parser("info", help="show details of a single workshop item")
    i.add_argument("fileid")
    i.set_defaults(func=cmd_info)

    d = sub.add_parser("download", help="download workshop item(s) via steamcmd")
    d.add_argument("appid")
    d.add_argument("fileid", nargs="+", type=int)
    d.add_argument("--out", default=None, help="content root dir (default from settings)")
    d.add_argument("--username", default=None, help="steam username (anonymous if omitted)")
    d.add_argument("--anonymous", action="store_true", help="force anonymous login")
    d.set_defaults(func=cmd_download)

    u = sub.add_parser("url", help="parse a pasted steam URL into ids")
    u.add_argument("text", nargs="+")
    u.set_defaults(func=cmd_url)

    c = sub.add_parser("settings", help="show/update persistent settings")
    c.add_argument("--root", default=None)
    c.add_argument("--username", default=None)
    c.add_argument("--parallel", type=int, default=None)
    c.set_defaults(func=cmd_settings)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or EXIT_OK
    except KeyboardInterrupt:
        _p("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
