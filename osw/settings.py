"""Persistent app settings stored as JSON in ~/.config/OpenSteamWorkshop."""

from __future__ import annotations

import json
from pathlib import Path

from .storage import atomic_json

CONFIG_DIR = Path.home() / ".config" / "OpenSteamWorkshop"
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "content_root": str(Path.home() / "SteamMods"),
    "steamcmd_dir": "",
    "username": "",
    "parallel_downloads": 1,  # compatibility setting; SteamCMD is serialized
}

_LAST: dict = {}


def load() -> dict:
    """Load settings, filling in defaults. Cached for the process lifetime."""
    global _LAST
    if not _LAST:
        data = {}
        try:
            data = {} if not CONFIG_FILE.is_file() else json.loads(CONFIG_FILE.read_text())
        except (OSError, ValueError):
            data = {}
        s = dict(DEFAULTS)
        if not isinstance(data, dict):
            data = {}
        for k in DEFAULTS:
            if k in data:
                s[k] = data[k]
        _LAST = _validated(s)
    return dict(_LAST)


def save(patch: dict) -> None:
    global _LAST
    current = load()
    current.update({k: v for k, v in patch.items() if k in DEFAULTS})
    current = _validated(current)
    atomic_json(CONFIG_FILE, current)
    _LAST = current


def _validated(data: dict) -> dict:
    result = dict(DEFAULTS)
    for key in ("content_root", "steamcmd_dir", "username"):
        if isinstance(data.get(key), str):
            result[key] = data[key].strip()
    if not result["content_root"]:
        result["content_root"] = DEFAULTS["content_root"]
    result["content_root"] = str(Path(result["content_root"]).expanduser().resolve())
    if result["steamcmd_dir"]:
        result["steamcmd_dir"] = str(Path(result["steamcmd_dir"]).expanduser().resolve())
    return result


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def set_key(key: str, value) -> None:
    save({key: value})
