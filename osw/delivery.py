"""Per-game delivery: move downloaded Workshop items into a chosen mods folder.

SteamCMD always writes its numeric
``<mods root>/steamapps/workshop/content/<appid>/<itemid>/`` layout. When a game
has an explicit mods-folder override, the finished item folder is moved into
that folder instead, named after the item title and tagged with a small marker
file so later deliveries and the Library can recognise it.

The marker is intentionally tiny and additive:

``<delivered folder>/.opensteamworkshop.json``
``{"appid": ..., "fileid": ..., "title": ..., "delivered": "YYYY-MM-DD"}``
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

MARKER_NAME = ".opensteamworkshop.json"
_INVALID_NAME_CHARS = frozenset('<>:"/\\|?*')
_MAX_NAME = 60


class DeliveryError(Exception):
    """Raised when staged files cannot be moved into the chosen game folder."""

    kind = "delivery"


def sanitize_folder_name(title: str, fileid: int) -> str:
    """A readable, cross-platform folder name derived from an item title."""
    raw = "".join(
        ch for ch in str(title or "") if ch not in _INVALID_NAME_CHARS and ord(ch) >= 32
    )
    name = " ".join(raw.split()).strip(" .")
    if len(name) > _MAX_NAME:
        name = name[:_MAX_NAME].strip(" .")
    return name or str(int(fileid))


def marker_path(folder: Path | str) -> Path:
    return Path(folder) / MARKER_NAME


def read_marker(folder: Path | str) -> dict | None:
    """Read a delivery marker; malformed or missing files yield ``None``."""
    try:
        data = json.loads(marker_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def marker_ids(folder: Path | str) -> tuple[int, int] | None:
    marker = read_marker(folder)
    if marker is None:
        return None
    try:
        appid, fileid = int(marker.get("appid", 0)), int(marker.get("fileid", 0))
    except (TypeError, ValueError):
        return None
    return (appid, fileid) if appid > 0 and fileid > 0 else None


def _child_dirs(parent: Path) -> list[Path]:
    entries: list[Path] = []
    try:
        with os.scandir(parent) as scanned:
            for entry in scanned:
                try:
                    if not entry.is_symlink() and entry.is_dir(follow_symlinks=False):
                        entries.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return []
    entries.sort(key=lambda path: path.name)
    return entries


def _same_item(folder: Path, appid: int, fileid: int) -> bool:
    return marker_ids(folder) == (appid, fileid)


def _remove_tree(path: Path) -> None:
    """Remove a previous delivery (never follows or deletes a symlinked folder)."""
    if path.is_symlink():
        raise DeliveryError(f"Refusing to replace a symlinked folder: {path}")
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except OSError as exc:
        raise DeliveryError(f"Could not replace {path}: {exc}") from exc


def _pick_target(
    destination_root: Path, name: str, appid: int, fileid: int, existing: Path | None
) -> Path:
    """Resolve the folder that should receive this item.

    The title wins when it is free. An existing folder for the same item keeps
    its slot (and may be renamed when the author changed the title). A folder
    belonging to a different item forces the ``Title (itemid)`` fallback.
    """
    preferred = destination_root / name
    if existing is not None:
        if preferred == existing:
            return preferred
        if not preferred.exists() or _same_item(preferred, appid, fileid):
            return preferred
    elif not preferred.exists() or _same_item(preferred, appid, fileid):
        return preferred

    fallback = destination_root / f"{name} ({fileid})"
    candidate = fallback
    counter = 2
    while candidate.exists() and not _same_item(candidate, appid, fileid):
        candidate = destination_root / f"{name} ({fileid} {counter})"
        counter += 1
    return candidate


def deliver_item(
    staged: Path | str,
    destination_root: Path | str,
    appid: int,
    fileid: int,
    title: str,
    updated: int = 0,
) -> Path:
    """Move one staged item folder into the game's mods folder.

    Move semantics: on success the staged folder no longer exists. The
    operation is retry-safe — an existing delivery of the same item is replaced
    (and renamed when the title changed), while a different item with the same
    title gets an item-id suffix. ``updated`` is the Workshop revision that was
    just downloaded, stored for the update checker.
    """
    staged_path = Path(staged)
    root = Path(destination_root).expanduser()
    if not staged_path.is_dir():
        raise DeliveryError(f"Downloaded item folder is missing: {staged_path}")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DeliveryError(f"Could not create the mods folder {root}: {exc}") from exc

    name = sanitize_folder_name(title, fileid)
    existing = next(
        (path for path in _child_dirs(root) if _same_item(path, appid, fileid)),
        None,
    )
    target = _pick_target(root, name, appid, fileid, existing)

    # A title collision plus a previous delivery of the same item can leave two
    # folders; clearing both keeps exactly one copy behind.
    for path in {existing, target}:
        if path is not None and path.exists() and path.resolve() != staged_path.resolve():
            _remove_tree(path)

    try:
        if target.resolve() == staged_path.resolve():
            final = staged_path
        else:
            shutil.move(str(staged_path), str(target))
            final = target
    except OSError as exc:
        raise DeliveryError(f"Could not move the item into {root}: {exc}") from exc

    marker = {
        "appid": int(appid),
        "fileid": int(fileid),
        "title": str(title or ""),
        "delivered": time.strftime("%Y-%m-%d"),
    }
    if int(updated or 0) > 0:
        marker["updated"] = int(updated)
    try:
        marker_path(final).write_text(
            json.dumps(marker, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise DeliveryError(f"Could not tag the delivered folder {final}: {exc}") from exc
    return final
