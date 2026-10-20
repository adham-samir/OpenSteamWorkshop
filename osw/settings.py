"""Persistent app settings stored as JSON in ~/.config/OpenSteamWorkshop."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "OpenSteamWorkshop"
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "content_root": str(Path.home() / "SteamMods"),
    "steamcmd_dir": "",
    "username": "",
    "remember_password": False,
    "password": "",
    "parallel_downloads": 2,
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
        for k in DEFAULTS:
            if k in data:
                s[k] = data[k]
        _LAST = s
    return dict(_LAST)


def save(patch: dict) -> None:
    global _LAST
    current = load()
    current.update(patch)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(current, indent=2))
    _LAST = current


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def set_key(key: str, value) -> None:
    save({key: value})
