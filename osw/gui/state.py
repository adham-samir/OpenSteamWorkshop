"""Small, separate store for personal UI state: recent and pinned games.

Kept out of ``settings.json`` so browsing history never looks like configuration.
Loading is tolerant: a corrupt or partial file simply yields empty lists.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import settings
from ..models import Game
from ..storage import atomic_json

RECENT_LIMIT = 6
UPDATE_CHECK_INTERVAL = 24 * 60 * 60  # seconds between automatic checks


def default_path() -> Path:
    return settings.CONFIG_DIR / "state.json"


def _game(value) -> Game | None:
    if not isinstance(value, dict):
        return None
    try:
        appid = int(value.get("appid", 0))
    except (TypeError, ValueError):
        return None
    if appid <= 0:
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    image = value.get("image")
    return Game(appid, name.strip(), image=image if isinstance(image, str) else "")


def _games(values) -> list[Game]:
    out: list[Game] = []
    seen: set[int] = set()
    for value in values if isinstance(values, list) else []:
        game = _game(value)
        if game is None or game.appid in seen:
            continue
        seen.add(game.appid)
        out.append(game)
    return out


def _game_paths(values) -> dict[int, Path]:
    paths: dict[int, Path] = {}
    for key, value in ((values or {}).items() if isinstance(values, dict) else []):
        try:
            appid = int(key)
        except (TypeError, ValueError):
            continue
        if appid <= 0 or not isinstance(value, str) or not value.strip():
            continue
        paths[appid] = Path(value).expanduser()
    return paths


class AppState:
    """Recently opened games, pinned favorites and per-game mods folders."""

    def __init__(self, path: Path | None = None, *, autosave: bool = True):
        self._path = Path(path) if path is not None else None
        self._autosave = autosave
        self.recent: list[Game] = []
        self.favorites: list[Game] = []
        self.game_paths: dict[int, Path] = {}
        self.last_update_check = 0.0
        self.load()

    @property
    def path(self) -> Path:
        return self._path or default_path()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        self.recent = _games(raw.get("recent"))[:RECENT_LIMIT]
        self.favorites = _games(raw.get("favorites"))
        self.game_paths = _game_paths(raw.get("game_paths"))
        try:
            self.last_update_check = max(0.0, float(raw.get("last_update_check") or 0))
        except (TypeError, ValueError):
            self.last_update_check = 0.0

    def save(self) -> None:
        atomic_json(
            self.path,
            {
                "version": 1,
                "recent": [self._plain(g) for g in self.recent],
                "favorites": [self._plain(g) for g in self.favorites],
                "game_paths": {
                    str(appid): str(path)
                    for appid, path in sorted(self.game_paths.items())
                },
                "last_update_check": self.last_update_check,
            },
        )

    def _save_if_needed(self) -> None:
        if self._autosave:
            self.save()

    @staticmethod
    def _plain(game: Game) -> dict:
        return {"appid": int(game.appid), "name": game.name, "image": game.image}

    def record_game(self, game: Game | None) -> None:
        if game is None or not game.appid:
            return
        self.recent = [g for g in self.recent if g.appid != game.appid]
        self.recent.insert(0, Game(game.appid, game.name, game.type, game.image))
        del self.recent[RECENT_LIMIT:]
        self._save_if_needed()

    def is_favorite(self, appid: int) -> bool:
        return any(g.appid == appid for g in self.favorites)

    def toggle_favorite(self, game: Game | None) -> bool:
        """Pin or unpin a game; returns the new pinned state."""
        if game is None or not game.appid:
            return False
        if self.is_favorite(game.appid):
            self.favorites = [g for g in self.favorites if g.appid != game.appid]
            self._save_if_needed()
            return False
        self.favorites.append(Game(game.appid, game.name, game.type, game.image))
        self._save_if_needed()
        return True

    def favorite_ids(self) -> set[int]:
        return {g.appid for g in self.favorites}

    def game_path(self, appid: int) -> Path | None:
        """The opt-in mods folder for a game, or ``None`` for the default root."""
        return self.game_paths.get(int(appid))

    def set_game_path(self, appid: int, path) -> None:
        appid = int(appid)
        if appid <= 0 or not str(path).strip():
            return
        self.game_paths[appid] = Path(path).expanduser()
        self._save_if_needed()

    def clear_game_path(self, appid: int) -> bool:
        appid = int(appid)
        if appid not in self.game_paths:
            return False
        del self.game_paths[appid]
        self._save_if_needed()
        return True

    def updates_check_due(self, interval: int = UPDATE_CHECK_INTERVAL) -> bool:
        return time.time() - self.last_update_check >= interval

    def mark_updates_checked(self, when: float | None = None) -> None:
        self.last_update_check = float(time.time() if when is None else when)
        self._save_if_needed()

    def favorite_games(self) -> list[Game]:
        return list(self.favorites)

    def recent_games(self) -> list[Game]:
        return list(self.recent)
