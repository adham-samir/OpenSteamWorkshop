"""CLI: `osw` command. Human-friendly console frontend for the API + steamcmd."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

from . import __version__
from .bulk import resolve_downloads
from .desktop import (
    desktop_supported,
    entry_text,
    install_desktop_entry,
    uninstall_desktop_entry,
)
from .installed import InstalledIndex, check_updates
from .models import WorkshopItem
from .net import NetError
from .queue import DownloadManager, JobState
from .settings import get, save
from .steam_api import (
    SORTS,
    browse_workshop,
    get_item_details,
    resolve_ids,
    search_games,
)
from .steamcmd import SteamCMDError

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
    try:
        items, total, pages = browse_workshop(
            appid,
            page=page,
            per_page=per,
            sort=args.sort,
            search_text=" ".join(args.search or []),
        )
    except NetError as e:
        _p(f"Could not browse app {appid}: {e}")
        return EXIT_ERR
    if not items:
        _p(f"No workshop items found (app {appid}, page {page}).")
        return EXIT_ERR
    _p(f"app {appid} — total items {total}, page {page}/{pages or '?'}\n")
    for it in items:
        size = f"{it.file_size / 1e6:.1f}MB" if it.file_size else "?"
        subs = f"{it.subscriptions:,}"
        stars = f"★{it.star_rating:.1f}" if it.star_rating else "-"
        print(f"{it.publishedfileid:>11} {size:>9} {subs:>10} {stars:>5}  {it.title}")
    _p(
        f"\nTip: osw info {items[0].publishedfileid} | osw download {appid} {items[0].publishedfileid}"
    )
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
    items = [
        WorkshopItem(publishedfileid=n, appid=int(args.appid)) for n in dict.fromkeys(args.fileid)
    ]
    return _download_items(args, items)


def _console_auth(job, kind, prompt, cancel):
    if not sys.stdin.isatty():
        return None
    if kind == "approval":
        print("Approve the Steam sign-in request in your Steam mobile app.", flush=True)
        return ""
    label = "Steam password: " if kind == "password" else "Steam Guard code: "
    if os.name == "nt":  # pragma: no cover
        return getpass.getpass(label)
    import select
    import termios

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    no_echo = list(original)
    no_echo[3] &= ~termios.ECHO
    try:
        termios.tcsetattr(fd, termios.TCSANOW, no_echo)
        print(label, end="", file=sys.stderr, flush=True)
        value = bytearray()
        while not cancel.is_set():
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                chunk = os.read(fd, 1024)
                if not chunk:
                    return None
                value.extend(chunk)
                if b"\n" in value:
                    return value.split(b"\n", 1)[0].decode("utf-8").rstrip("\r")
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        print(file=sys.stderr, flush=True)


def _installed_index(root) -> InstalledIndex:
    """Build an index that also understands per-game delivery folders."""
    index = InstalledIndex()
    try:
        from .gui.state import AppState

        game_paths = AppState(autosave=False).game_paths
    except Exception:  # state is optional for the CLI
        game_paths = {}
    index.scan(root, game_paths)
    return index


def _filter_installed(args, items):
    """Drop items already installed under the effective root unless --reinstall."""
    if not items or getattr(args, "reinstall", False):
        return items
    root = args.out or get("content_root")
    index = _installed_index(root)
    keep = []
    for item in items:
        hit = index.lookup(item.appid, item.publishedfileid)
        if hit is None:
            keep.append(item)
            continue
        print(
            f"[{item.publishedfileid}] already installed at {hit.path} — "
            "use --reinstall to download again"
        )
    return keep


def _download_items(args, items, had_issues=False):
    if not items:
        return EXIT_ERR
    items = _filter_installed(args, items)
    if not items:
        print("Nothing to download — every requested item is already installed.")
        return EXIT_ERR if had_issues else EXIT_OK
    manager = _build_manager(args)
    try:
        return _run_jobs(manager, manager.add_many(items), had_issues)
    finally:
        manager.shutdown()


def _run_jobs(manager, jobs, had_issues=False):
    last = {}
    while any(
        j.state in (JobState.QUEUED, JobState.RUNNING, JobState.WAITING_FOR_AUTH) for j in jobs
    ):
        for job in jobs:
            if last.get(job.id) != job.state:
                print(f"[{job.fileid}] {job.state.value}: {job.title}", flush=True)
                last[job.id] = job.state
        time.sleep(0.05)
    for job in jobs:
        print(f"[{job.fileid}] {job.state.value}: {job.message}")
    failures = [j for j in jobs if j.state is not JobState.DONE]
    if failures and all(j.error_kind == "access" for j in failures) and not had_issues:
        return EXIT_NOT_OWNED  # retained exit code; access denied does not prove non-ownership
    return EXIT_ERR if failures or had_issues else EXIT_OK


def cmd_desktop_install(args) -> int:
    if not desktop_supported():
        _p("Application-menu integration is only available on Linux.")
        return EXIT_ERR
    if args.print_entry:
        print(entry_text())
        return EXIT_OK
    entry, icon = install_desktop_entry()
    _p("Installed the OpenSteamWorkshop application-menu entry:")
    _p(f"  {entry}")
    _p(f"  {icon}")
    _p(
        "Search for OpenSteamWorkshop in your application menu; "
        "log out and back in if it is not there yet."
    )
    return EXIT_OK


def cmd_desktop_uninstall(args) -> int:
    if not desktop_supported():
        _p("Application-menu integration is only available on Linux.")
        return EXIT_ERR
    removed = uninstall_desktop_entry()
    if not removed:
        _p("No application-menu entry was installed.")
        return EXIT_OK
    _p("Removed the application-menu entry:")
    for path in removed:
        _p(f"  {path}")
    return EXIT_OK


def cmd_updates(args):
    root = Path(args.out or get("content_root"))
    index = _installed_index(root)
    wanted = set(args.appid or [])
    items = [item for item in index.items() if not wanted or item.appid in wanted]
    if not items:
        print("No installed Workshop content found.")
        return EXIT_OK

    statuses = check_updates(items)

    def rank(item):
        info = statuses.get(item.fileid)
        return (0 if info is not None and info.available else 1, item.appid, item.fileid)

    ordered = sorted(items, key=rank)
    for item in ordered:
        info = statuses.get(item.fileid)
        if info is None:
            continue
        print(
            f"{info.label:<17} installed {info.installed_label} · latest {info.online_label}"
            f"  {item.fileid}  {info.title or item.label}"
        )
    available = [
        item
        for item in ordered
        if item.fileid in statuses and statuses[item.fileid].available
    ]
    noun = "update" if len(available) == 1 else "updates"
    print(f"\n{len(items)} installed · {len(available)} {noun} available")

    if not args.apply or not available:
        return EXIT_OK

    manager = _build_manager(args)
    try:
        jobs = []
        for item in available:
            jobs.append(
                manager.add(
                    WorkshopItem(
                        item.fileid,
                        appid=item.appid,
                        title=item.title,
                        time_updated=statuses[item.fileid].online,
                    ),
                    item.app_name,
                    deliver_to=item.origin if item.delivered else None,
                    reinstall=True,
                )
            )
        return _run_jobs(manager, jobs)
    finally:
        manager.shutdown()


def cmd_batch(args):
    references = list(args.references)
    if args.input:
        references.append(Path(args.input).read_text(encoding="utf-8"))
    if not references:
        raise ValueError("Supply Workshop URLs/IDs or --input FILE")
    resolved = resolve_downloads(references, args.appid, args.with_dependencies)
    for issue in resolved.issues:
        print(f"Skipped {issue.reference}: {issue.message}", file=sys.stderr)
    print(
        f"Resolved {len(resolved.items)} mods, {resolved.collections} collections, "
        f"{resolved.duplicates} duplicate references"
    )
    return _download_items(args, resolved.items, bool(resolved.issues))


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
            patch["parallel_downloads"] = 1
            _p("--parallel is deprecated: SteamCMD operations run one at a time.")
        save(patch)
    s = get("content_root")
    _p("Settings are stored in ~/.config/OpenSteamWorkshop/settings.json")
    _p(f"  content_root = {s!r}")
    _p(f"  username     = {get('username')!r}")
    _p(f"  parallel     = {get('parallel_downloads')}")
    return EXIT_OK


def _build_manager(args) -> DownloadManager:
    # An account is used only when explicitly requested; --anonymous always wins.
    username = "" if args.anonymous else (args.username or "")
    password = os.environ.get("OSW_PASS", "") if username else ""
    mgr = DownloadManager(
        content_root=args.out or get("content_root"),
        steamcmd_dir=get("steamcmd_dir") or None,
        username=username,
        password=password,
        parallel=1,
        on_log=lambda m: print(m, flush=True),
        on_auth=_console_auth,
    )
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
    d.add_argument(
        "--reinstall", action="store_true", help="download again even if already installed"
    )
    d.add_argument("--username", default=None, help="steam username (anonymous if omitted)")
    d.add_argument("--anonymous", action="store_true", help="force anonymous login")
    d.set_defaults(func=cmd_download)

    batch = sub.add_parser("batch", help="download URLs, collections or an imported list")
    batch.add_argument("references", nargs="*", help="Workshop URLs or item IDs")
    batch.add_argument("--input", metavar="FILE", help="UTF-8 text file of Workshop URLs or IDs")
    batch.add_argument("--appid", type=int, help="fallback game ID for items without one")
    batch.add_argument(
        "--with-dependencies", action="store_true", help="resolve required items recursively"
    )
    batch.add_argument("--out", help="content root directory")
    batch.add_argument(
        "--reinstall", action="store_true", help="download again even if already installed"
    )
    batch.add_argument("--username", help="optional Steam account; default is anonymous")
    batch.add_argument("--anonymous", action="store_true", help="force anonymous login")
    batch.set_defaults(func=cmd_batch)

    up = sub.add_parser(
        "updates", help="check installed workshop items for newer revisions"
    )
    up.add_argument("appid", nargs="*", type=int, help="limit the check to these games")
    up.add_argument("--out", default=None, help="content root dir (default from settings)")
    up.add_argument(
        "--apply", action="store_true", help="download every available update"
    )
    up.add_argument("--username", default=None, help="steam username (anonymous if omitted)")
    up.add_argument("--anonymous", action="store_true", help="force anonymous login")
    up.set_defaults(func=cmd_updates)

    di = sub.add_parser(
        "desktop-install", help="add the app to the Linux application menu"
    )
    di.add_argument(
        "--print",
        dest="print_entry",
        action="store_true",
        help="print the launcher entry without installing it",
    )
    di.set_defaults(func=cmd_desktop_install)

    du = sub.add_parser(
        "desktop-uninstall", help="remove the Linux application-menu entry"
    )
    du.set_defaults(func=cmd_desktop_uninstall)

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
    except (NetError, SteamCMDError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERR


if __name__ == "__main__":
    sys.exit(main())
