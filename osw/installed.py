"""Installed Workshop content discovery and lookup.

Downloads land in the layout SteamCMD writes:
``<mods root>/steamapps/workshop/content/<appid>/<itemid>/``; per-game override
folders receive title-named copies carrying a ``.opensteamworkshop.json`` marker.

Scanning is deliberately filesystem-only and tolerant: unreadable directories,
non-numeric entries and symlinks are skipped rather than failing the whole
scan. Metadata enrichment is a separate, paced network step so opening the
Library never waits on Steam.

Installed revisions come from SteamCMD's ``appworkshop_<appid>.acf`` manifest
(staged items) or the delivery marker (moved items), so the update checker can
compare them with the latest Workshop metadata.

This module is Qt-free so the CLI can reuse it for its installed guard.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .delivery import read_marker
from .steam_api import get_app_name, get_published_files

UPDATE_AVAILABLE = "update-available"
UP_TO_DATE = "up-to-date"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"


def _date(ts) -> str:
    try:
        ts = int(ts or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _short_path(path: Path) -> str:
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


@dataclass
class InstalledItem:
    """One directory installed by SteamCMD or delivered to a game folder."""

    appid: int
    fileid: int
    path: Path
    size: int = 0
    modified: float = 0.0
    title: str = ""
    app_name: str = ""
    delivered: bool = False
    origin: Path | None = None
    updated: int = 0  # Workshop time_updated of the installed copy; 0 = unknown

    @property
    def updated_label(self) -> str:
        return _date(self.updated) or "unknown"

    @property
    def label(self) -> str:
        return self.title or f"Workshop item {self.fileid}"

    @property
    def game_label(self) -> str:
        return self.app_name or f"App {self.appid}"

    @property
    def location_label(self) -> str:
        if not self.delivered:
            return "Default mods root"
        return f"Delivered · {_short_path(self.origin or self.path.parent)}"

    @property
    def summary(self) -> str:
        """One-line location for notices and dialogs."""
        return f"{_short_path(self.path)} ({self.location_label})"


@dataclass(frozen=True)
class InstalledMetadata:
    title: str = ""
    app_name: str = ""


def content_dir(mods_root: Path | str) -> Path:
    """Return the Workshop content directory for a configured mods root."""
    root = Path(mods_root).expanduser()
    if root.name == "content" and root.parent.name == "workshop":
        return root
    return root / "steamapps" / "workshop" / "content"


def acf_path(mods_root: Path | str, appid: int) -> Path:
    """SteamCMD's per-game manifest sits beside the content tree."""
    return content_dir(mods_root).parent / f"appworkshop_{int(appid)}.acf"


_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def _parse_vdf(text: str) -> dict:
    """Parse the subset of Valve KeyValues used by ``appworkshop_*.acf``."""
    tokens = [
        (match.group(1), None) if match.group(1) is not None else (None, match.group(2))
        for match in _VDF_TOKEN.finditer(text)
    ]
    position = 0

    def block() -> dict:
        nonlocal position
        values: dict = {}
        while position < len(tokens):
            key, brace = tokens[position]
            if brace == "}":
                position += 1
                return values
            if brace == "{":  # stray container without a key
                position += 1
                continue
            position += 1
            if position < len(tokens) and tokens[position][1] == "{":
                position += 1
                values[key] = block()
            elif position < len(tokens):
                values[key] = tokens[position][0]
                position += 1
        return values

    return block()


def _positive_int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def read_acf_updates(mods_root: Path | str, appid: int) -> dict[int, int]:
    """Map installed file IDs to the Workshop revision SteamCMD recorded.

    Returns an empty mapping when the manifest is missing or unreadable; a
    portable mods tree may have been copied without it.
    """
    try:
        text = acf_path(mods_root, appid).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    root = _parse_vdf(text).get("AppWorkshop")
    installed = root.get("WorkshopItemsInstalled") if isinstance(root, dict) else None
    if not isinstance(installed, dict):
        return {}
    updates: dict[int, int] = {}
    for key, value in installed.items():
        if not str(key).isdigit() or not isinstance(value, dict):
            continue
        stamp = _positive_int(value.get("timeupdated"))
        if stamp:
            updates[int(key)] = stamp
    return updates


def _marker_updated(marker: dict) -> int:
    """Exact revision from the marker, else the delivery day as a lower bound.

    Legacy markers only recorded a date. Using UTC midnight keeps the display
    stable across time zones and errs towards one redundant update rather than
    missing a same-day revision.
    """
    stamp = _positive_int(marker.get("updated"))
    if stamp:
        return stamp
    try:
        day = datetime.strptime(str(marker.get("delivered") or ""), "%Y-%m-%d")
    except (TypeError, ValueError):
        return 0
    return int(day.replace(tzinfo=timezone.utc).timestamp())


def _cancelled(cancel: threading.Event | None) -> bool:
    return cancel is not None and cancel.is_set()


def _pause(cancel: threading.Event | None, seconds: float) -> bool:
    if seconds <= 0:
        return not _cancelled(cancel)
    if cancel is not None:
        return not cancel.wait(seconds)
    time.sleep(seconds)
    return True


def _tree_stats(path: Path, cancel: threading.Event | None) -> tuple[int, float] | None:
    """Sum regular-file sizes and find the newest mtime below ``path``.

    Returns ``None`` when the scan was cancelled. Unreadable entries are
    ignored; symlinks are never followed or deleted.
    """
    total = 0
    newest = 0.0
    try:
        newest = path.stat().st_mtime
    except OSError:
        pass
    pending = [path]
    while pending:
        if _cancelled(cancel):
            return None
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if _cancelled(cancel):
                        return None
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            stat = entry.stat(follow_symlinks=False)
                            total += stat.st_size
                            newest = max(newest, stat.st_mtime)
                    except OSError:
                        continue
        except OSError:
            continue
    return total, newest


def _numeric_dirs(path: Path) -> list[Path]:
    entries: list[Path] = []
    try:
        with os.scandir(path) as scanned:
            for entry in scanned:
                try:
                    if (
                        not entry.is_symlink()
                        and entry.is_dir(follow_symlinks=False)
                        and entry.name.isdigit()
                    ):
                        entries.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return []
    entries.sort(key=lambda entry: entry.name)
    return entries


def scan_installed(
    mods_root: Path | str,
    cancel: threading.Event | None = None,
    game_paths: dict | None = None,
) -> list[InstalledItem] | None:
    """Scan installed app/item directories plus per-game override folders.

    Default downloads live in the numeric SteamCMD tree; override deliveries
    are title-named folders carrying a ``.opensteamworkshop.json`` marker.
    Delivered rows win over leftover staged copies of the same item.

    Returns ``None`` if cancelled so the caller can ignore a stale worker.
    """
    content = content_dir(mods_root)
    found: dict[tuple[int, int], InstalledItem] = {}
    for app_path in _numeric_dirs(content):
        if _cancelled(cancel):
            return None
        appid = int(app_path.name)
        revisions = read_acf_updates(mods_root, appid)
        for item_path in _numeric_dirs(app_path):
            if _cancelled(cancel):
                return None
            stats = _tree_stats(item_path, cancel)
            if stats is None:
                return None
            size, modified = stats
            fileid = int(item_path.name)
            found[(appid, fileid)] = InstalledItem(
                appid=appid,
                fileid=fileid,
                path=item_path,
                size=size,
                modified=modified,
                origin=content,
                updated=revisions.get(fileid, 0),
            )

    for _appid, folder in sorted((game_paths or {}).items()):
        if _cancelled(cancel):
            return None
        delivered = scan_delivered_folder(folder, cancel)
        if delivered is None:
            return None
        for item in delivered:
            found[(item.appid, item.fileid)] = item
    items = list(found.values())
    items.sort(key=lambda item: (item.appid, item.fileid))
    return items


def scan_delivered_folder(
    folder: Path | str, cancel: threading.Event | None = None
) -> list[InstalledItem] | None:
    """Find app-delivered items in one game's mods folder (marker-based)."""
    root = Path(folder).expanduser()
    items: list[InstalledItem] = []
    try:
        with os.scandir(root) as scanned:
            entries = sorted(
                (Path(entry.path) for entry in scanned), key=lambda path: path.name
            )
    except OSError:
        return items
    for item_path in entries:
        if _cancelled(cancel):
            return None
        try:
            if item_path.is_symlink() or not item_path.is_dir():
                continue
        except OSError:
            continue
        marker = read_marker(item_path)
        if marker is None:
            continue
        try:
            appid, fileid = int(marker.get("appid", 0)), int(marker.get("fileid", 0))
        except (TypeError, ValueError):
            continue
        if appid <= 0 or fileid <= 0:
            continue
        stats = _tree_stats(item_path, cancel)
        if stats is None:
            return None
        size, modified = stats
        title = marker.get("title")
        items.append(
            InstalledItem(
                appid=appid,
                fileid=fileid,
                path=item_path,
                size=size,
                modified=modified,
                title=title.strip() if isinstance(title, str) else "",
                delivered=True,
                origin=root,
                updated=_marker_updated(marker),
            )
        )
    return items


def fetch_installed_metadata(
    items: list[InstalledItem],
    cancel: threading.Event | None = None,
    *,
    batch_size: int = 100,
    pause: float = 0.35,
) -> dict[int, InstalledMetadata]:
    """Fetch titles and game names in paced batches.

    Metadata is best effort: network failures leave the local rows intact and
    do not fail the scan. Returning a partial mapping is intentional.
    """
    if not items or _cancelled(cancel):
        return {}

    titles: dict[int, str] = {}
    fileids = sorted({item.fileid for item in items})
    for offset in range(0, len(fileids), max(1, batch_size)):
        if _cancelled(cancel):
            return {}
        batch = fileids[offset : offset + max(1, batch_size)]
        try:
            rows = get_published_files(batch, cancel)
        except Exception:
            rows = {}
        for fileid, row in (rows or {}).items():
            if isinstance(row, dict):
                title = str(row.get("title") or "").strip()
                if title:
                    titles[int(fileid)] = title
        if offset + len(batch) < len(fileids) and not _pause(cancel, pause):
            return {}

    app_names: dict[int, str] = {}
    appids = sorted({item.appid for item in items})
    for index, appid in enumerate(appids):
        if _cancelled(cancel):
            return {}
        try:
            name = get_app_name(appid, cancel)
        except Exception:
            name = ""
        if name and not name.startswith("App "):
            app_names[appid] = name
        if index + 1 < len(appids) and not _pause(cancel, pause):
            return {}

    metadata: dict[int, InstalledMetadata] = {}
    for item in items:
        title = titles.get(item.fileid, "")
        app_name = app_names.get(item.appid, "")
        if title or app_name:
            metadata[item.fileid] = InstalledMetadata(title=title, app_name=app_name)
    return metadata


@dataclass(frozen=True)
class UpdateInfo:
    """Comparison of an installed copy with the latest Workshop revision."""

    fileid: int
    status: str
    installed: int = 0
    online: int = 0
    title: str = ""

    @property
    def available(self) -> bool:
        return self.status == UPDATE_AVAILABLE

    @property
    def installed_label(self) -> str:
        return _date(self.installed) or "unknown"

    @property
    def online_label(self) -> str:
        return _date(self.online) or "unknown"

    @property
    def label(self) -> str:
        return {
            UPDATE_AVAILABLE: "Update available",
            UP_TO_DATE: "Up to date",
            UNAVAILABLE: "Unavailable",
            UNKNOWN: "Version unknown",
        }.get(self.status, self.status)


def check_updates(
    items, cancel: threading.Event | None = None, *, pace: float = 0.35
) -> dict[int, UpdateInfo]:
    """Compare installed revisions with the latest public Workshop metadata.

    Uses the same 100-ID batches as metadata enrichment. Network errors
    propagate so callers can report them; a cancelled check returns ``{}``.
    """
    by_fileid: dict[int, InstalledItem] = {}
    for item in items:
        by_fileid.setdefault(int(item.fileid), item)
    if not by_fileid or _cancelled(cancel):
        return {}

    statuses: dict[int, UpdateInfo] = {}
    fileids = sorted(by_fileid)
    for offset in range(0, len(fileids), 100):
        if _cancelled(cancel):
            return {}
        batch = fileids[offset : offset + 100]
        rows = get_published_files(batch, cancel) or {}
        for fileid in batch:
            item = by_fileid[fileid]
            row = rows.get(fileid)
            if not isinstance(row, dict) or _positive_int(row.get("result")) != 1:
                statuses[fileid] = UpdateInfo(
                    fileid, UNAVAILABLE, item.updated, 0, item.title
                )
                continue
            online = _positive_int(row.get("time_updated"))
            title = str(row.get("title") or item.title)
            if not item.updated or not online:
                status = UNKNOWN
            elif online > item.updated:
                status = UPDATE_AVAILABLE
            else:
                status = UP_TO_DATE
            statuses[fileid] = UpdateInfo(
                fileid, status, item.updated, online, title
            )
        if offset + len(batch) < len(fileids) and not _pause(cancel, pace):
            return {}
    return statuses


def delete_installed_item(item: InstalledItem, mods_root: Path | str) -> None:
    """Delete one installed item after proving it is app-managed content.

    Delivered items are recognised by their marker and live in a user-chosen
    folder; staged items must still sit directly below ``<content>/<appid>/``.
    """
    path = item.path
    if path.is_symlink():
        raise ValueError("Refusing to delete a symlinked Workshop item")
    resolved = path.resolve()
    marker = read_marker(resolved)
    try:
        marker_match = marker is not None and (
            int(marker.get("appid", 0)),
            int(marker.get("fileid", 0)),
        ) == (int(item.appid), int(item.fileid))
    except (TypeError, ValueError):
        marker_match = False
    if marker_match:
        if not resolved.is_dir():
            raise FileNotFoundError(f"Installed item folder is missing: {resolved}")
        shutil.rmtree(resolved)
        return

    root = content_dir(mods_root).resolve()
    if (
        resolved.parent.parent != root
        or not resolved.parent.name.isdigit()
        or not resolved.name.isdigit()
    ):
        raise ValueError("Refusing to delete a folder outside the Workshop content tree")
    if not resolved.is_dir():
        raise FileNotFoundError(f"Installed item folder is missing: {resolved}")
    shutil.rmtree(resolved)


@dataclass
class InstalledIndex:
    """In-memory lookup of installed items, refreshed by scans.

    Published file IDs are globally unique, so ``lookup`` falls back to a
    file-id-only search when the app id is unknown (e.g. pasted item IDs).
    """

    content_root: Path | None = None
    game_paths: dict = field(default_factory=dict)
    _by_key: dict[tuple[int, int], InstalledItem] = field(default_factory=dict, init=False)
    _by_fileid: dict[int, InstalledItem] = field(default_factory=dict, init=False)

    def replace(self, items) -> None:
        self._by_key = {}
        self._by_fileid = {}
        for item in items:
            self.put(item)

    def put(self, item: InstalledItem) -> None:
        self._by_key[(int(item.appid), int(item.fileid))] = item
        self._by_fileid[int(item.fileid)] = item

    def scan(
        self,
        content_root: Path | str | None = None,
        game_paths: dict | None = None,
        cancel: threading.Event | None = None,
    ) -> bool:
        """Rescan the recovered roots; returns False when a scan was cancelled."""
        if content_root is not None:
            self.content_root = Path(content_root).expanduser()
        if game_paths is not None:
            self.game_paths = dict(game_paths)
        if self.content_root is None:
            return True
        items = scan_installed(self.content_root, cancel, self.game_paths)
        if items is None:
            return False
        self.replace(items)
        return True

    def lookup(self, appid: int, fileid: int) -> InstalledItem | None:
        key = (int(appid or 0), int(fileid))
        if key in self._by_key:
            return self._by_key[key]
        hit = self._by_fileid.get(int(fileid))
        if hit is not None and (not appid or hit.appid == int(appid)):
            return hit
        return None

    def record(
        self,
        appid: int,
        fileid: int,
        path: Path | str,
        *,
        title: str = "",
        delivered: bool | None = None,
    ) -> InstalledItem:
        """Register a finished download without rescanning the whole tree."""
        target = Path(path).expanduser()
        if delivered is None:
            delivered = self._is_delivered(target)
        item = InstalledItem(
            appid=int(appid or 0),
            fileid=int(fileid),
            path=target,
            modified=time.time(),
            title=title,
            delivered=bool(delivered),
            origin=(target.parent if delivered else None),
        )
        self.put(item)
        return item

    def remove(self, appid: int, fileid: int) -> None:
        self._by_key.pop((int(appid or 0), int(fileid)), None)
        self._by_fileid.pop(int(fileid), None)

    def _is_delivered(self, path: Path) -> bool:
        if self.content_root is None:
            return False
        try:
            root = content_dir(self.content_root).resolve()
            return not path.resolve().is_relative_to(root)
        except (OSError, ValueError):
            return False

    def fileids(self) -> set[int]:
        return set(self._by_fileid)

    def locations(self) -> dict[int, InstalledItem]:
        return dict(self._by_fileid)

    def items(self) -> list[InstalledItem]:
        return sorted(self._by_key.values(), key=lambda item: (item.appid, item.fileid))

    def __len__(self) -> int:
        return len(self._by_key)

    def __contains__(self, fileid: int) -> bool:
        return int(fileid) in self._by_fileid
