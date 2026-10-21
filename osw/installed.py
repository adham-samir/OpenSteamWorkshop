"""Installed Workshop content discovery and lookup.

Downloads land in the layout SteamCMD writes:
``<mods root>/steamapps/workshop/content/<appid>/<itemid>/``; per-game override
folders receive title-named copies carrying a ``.opensteamworkshop.json`` marker.

Scanning is deliberately filesystem-only and tolerant: unreadable directories,
non-numeric entries and symlinks are skipped rather than failing the whole
scan. Metadata enrichment is a separate, paced network step so opening the
Library never waits on Steam.

This module is Qt-free so the CLI can reuse it for its installed guard.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .delivery import read_marker
from .steam_api import get_app_name, get_published_files


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
        for item_path in _numeric_dirs(app_path):
            if _cancelled(cancel):
                return None
            stats = _tree_stats(item_path, cancel)
            if stats is None:
                return None
            size, modified = stats
            found[(appid, int(item_path.name))] = InstalledItem(
                appid=appid,
                fileid=int(item_path.name),
                path=item_path,
                size=size,
                modified=modified,
                origin=content,
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

    def __len__(self) -> int:
        return len(self._by_key)

    def __contains__(self, fileid: int) -> bool:
        return int(fileid) in self._by_fileid
