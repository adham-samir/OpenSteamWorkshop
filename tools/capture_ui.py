"""Capture deterministic desktop review fixtures; no downloads or network requests.

QT_QPA_PLATFORM=offscreen .venv/bin/python tools/capture_ui.py --art-dir /tmp
Set QT_SCALE_FACTOR=2 and --suffix @2x for the high-DPI pass.
Artwork files, when supplied: osw-garry.jpg, osw-rimworld.jpg,
osw-wiremod.jpg and osw-pac3.jpg (Steam game / Workshop artwork).
The library, queue, counts and long titles in captures are illustrative fixtures.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from osw import settings
from osw.bulk import DownloadResolution, ResolutionIssue
from osw.gui import theme
from osw.gui.browse_page import MODE_GRID
from osw.gui.library import UPDATE_AVAILABLE, InstalledItem, UpdateInfo
from osw.gui.main_window import Hub, MainWindow
from osw.models import Game, ItemDetails, WorkshopItem
from osw.queue import JobSnapshot, JobState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art-dir", type=Path, default=Path("/tmp"))
    parser.add_argument("--out", type=Path, default=Path(".impeccable/review"))
    parser.add_argument("--suffix", default="")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    settings.CONFIG_DIR = Path("/tmp/osw-ui-capture")
    settings.CONFIG_FILE = settings.CONFIG_DIR / "settings.json"
    settings.DEFAULTS = dict(settings.DEFAULTS, content_root="/tmp/osw-ui-capture/Mods")
    app = QApplication([])
    theme.apply_theme(app)
    with patch.object(Hub, "call", lambda *a, **kw: None):
        w = MainWindow(queue_path=Path("/tmp/osw-ui-capture/queue.json"))
        w.manager.ensure_workers = lambda: None
        w.state._autosave = False
        games = [Game(4000, "Garry’s Mod"), Game(294100, "RimWorld")]
        w.games = games
        w.current_game = games[0]
        w.nav.set_game_context(games[0])
        w.browse.set_game_context(games[0])
        w.browse.set_mode(MODE_GRID)
        w.browse.set_browser_enabled(True)
        w.library.set_game_context(games[0])
        items = [WorkshopItem(160250458, appid=4000, title="Wiremod", subscriptions=2400000,
                              file_size=15500000, star_rating=4.9),
                 WorkshopItem(104691717, appid=4000, title="PAC3", subscriptions=1800000,
                              file_size=9400000, star_rating=4.8),
                 WorkshopItem(900000001, appid=4000, title="A deliberately long Workshop title to verify wrapping and selection",
                              file_size=9400000),
                 WorkshopItem(900000002, appid=4000, title="Missing artwork example", file_size=720000)]
        items += [WorkshopItem(900000010+n, appid=4000, title=f"Illustrative Workshop item {n+1}",
                               subscriptions=12000, file_size=4500000) for n in range(8)]
        w.items = items
        w.browse.set_items(items, 1248, 1, 42)
        def art(name):
            path = args.art_dir / f"osw-{name}.jpg"
            return path.read_bytes() if path.exists() else None
        for item, name in zip(items, ["wiremod", "pac3"]):
            w.browse.update_card_thumb(item.publishedfileid, art(name))
        installed = [InstalledItem(4000, it.publishedfileid,
                                  Path(f"/home/player/SteamMods/steamapps/workshop/content/4000/{it.publishedfileid}"),
                                  title=it.title, app_name="Garry’s Mod", size=it.file_size,
                                  modified=1770000000) for it in items[:4]]
        w.library.show_items(installed, "/home/player/SteamMods")
        w._library_content_dir = Path("/home/player/SteamMods")
        w.library.apply_update_status({it.fileid: UpdateInfo(it.fileid, UPDATE_AVAILABLE, 1770000000, 1775000000)
                                       for it in installed[:2]})
        w.installed.replace(installed)
        for n, state in enumerate((JobState.RUNNING, JobState.RUNNING, JobState.FAILED,
                                    JobState.WAITING_FOR_AUTH, JobState.INTERRUPTED, JobState.QUEUED, JobState.DONE)):
            snapshot = JobSnapshot(str(n), 4000 if n % 2 == 0 else 294100,
                                   "Garry’s Mod" if n % 2 == 0 else "RimWorld", 160250458+n,
                                   ["Wiremod", "Illustrative RimWorld mod", "Private Workshop item"][n % 3],
                                   Path("/home/player/SteamMods"), state, 62 if n == 0 else 18,
                                   "Access denied. Retry with a Steam account." if n == 2 else
                                   "Waiting for Steam Guard" if n == 3 else "Downloading Workshop content",
                                   1, "/home/player/SteamMods" if state is JobState.DONE else "", "", (), False)
            w.downloads.upsert(snapshot)
        w.strip.update_state("Wiremod", "Downloading · 62%", True, 62, 1, 1, 2)
        w.strip.set_hint("2 need attention · Open Downloads")
        w.imports.set_source("https://steamcommunity.com/sharedfiles/filedetails/?id=160250458\n104691717\ninvalid-link",
                            hint="4000", dependencies=True, auto_resolve=False)
        w.imports.resolve_finished(DownloadResolution(items=items[:2], issues=[ResolutionIssue("invalid-link", "No Workshop item ID found")]))
        w.settings_page.load("/home/player/SteamMods", "", False, "", "", 3)
        w.show()
        def settle():
            for _ in range(4):
                app.processEvents()
        def capture(name):
            settle()
            path = args.out / f"{name}{args.suffix}.png"
            w.grab().save(str(path))
        for width, height in ((960, 640), (1150, 740), (1440, 900)):
            w.resize(width, height)
            settle()
            prefix = f"{width}x{height}"
            w.games_page.set_personal([], [])
            w.navigate("games")
            capture(f"{prefix}-games-first-use")
            w.games_page.set_personal(games, games[:1])
            w.games_page.update_thumb(4000, art("garry"))
            w.games_page.update_thumb(294100, art("rimworld"))
            capture(f"{prefix}-games")
            w.browse.set_inspector(False)
            w.browse.set_presentation("cards")
            w.navigate("browse")
            capture(f"{prefix}-browse")
            w.browse.cards.selectionModel().select(w.browse.grid_model.index(0), QItemSelectionModel.SelectionFlag.Select)
            w.browse._selection_timer.stop()
            w.browse._emit_selection()
            w.browse.inspector.set_details(ItemDetails(160250458, appid=4000, title="Wiremod", author="Wiremod team",
                                                       description="Wiremod adds components that can be connected with wires. Build circuits, create contraptions, and experiment with expression chips in Garry’s Mod.",
                                                       required_items=[(104691717, "Illustrative dependency")]), 4000)
            capture(f"{prefix}-details")
            w.browse.dismiss_details()
            w.browse.cards.clearSelection()
            w.browse._selection_timer.stop()
            w.browse.set_presentation("list")
            capture(f"{prefix}-list")
            w.navigate("library")
            w.library.table.setCurrentIndex(w.library.proxy.index(0, 0))
            capture(f"{prefix}-installed")
            w.navigate("downloads")
            w.downloads.table.setCurrentIndex(w.downloads.model.index(2, 0))
            capture(f"{prefix}-downloads")
            w.navigate("imports")
            capture(f"{prefix}-imports")
            w.navigate("settings")
            capture(f"{prefix}-settings")
        w.close()
        w.deleteLater()
        settle()
    print(f"Captured desktop screen matrix to {args.out}")


if __name__ == "__main__":
    main()
