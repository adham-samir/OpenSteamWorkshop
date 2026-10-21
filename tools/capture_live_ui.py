"""Capture the running Qt app with real Steam data in an isolated profile.

Invoked by tools/capture_ui.py --live. No downloads are queued and no sample
Workshop metadata or transfer states are injected.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from osw import settings
from osw.gui import main_window, theme
from osw.gui.item_models import ThumbRole


def capture_live(out: Path, *, desktop: bool = False) -> None:
    if desktop and not shutil.which("spectacle"):
        raise RuntimeError("Desktop capture requires KDE Spectacle")
    out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="openworkshop-capture-") as temporary:
        profile = Path(temporary)
        settings.CONFIG_DIR = profile
        settings.CONFIG_FILE = profile / "settings.json"
        settings._LAST = {}
        main_window.CONFIG_DIR = profile
        main_window.CACHE_DIR = profile / "thumbs"
        app = QApplication.instance() or QApplication([])
        app.setApplicationName("OpenWorkshop")
        app.setDesktopFileName("openworkshop")
        app.setStyle("Fusion")
        theme.apply_theme(app)
        window = main_window.MainWindow(queue_path=profile / "queue.json")
        window.resize(1440, 900)
        if desktop:
            area = app.primaryScreen().availableGeometry()
            window.resize(min(1440, area.width() - 80), min(900, area.height() - 80))
            window.move(area.center() - window.rect().center())
        errors: list[str] = []
        window.hub.error.connect(errors.append)
        captures = []

        def wait_for(predicate, description: str, timeout: float = 90) -> None:
            deadline = time.monotonic() + timeout
            while not predicate():
                app.processEvents()
                if errors:
                    raise RuntimeError(f"{description}: {errors[-1]}")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for {description}")
                QTest.qWait(40)
            QTest.qWait(150)

        def grab(name: str) -> None:
            app.processEvents()
            QTest.qWait(150)
            filename = f"openworkshop-{name}.png"
            path = (out / filename).resolve()
            if desktop:
                window.raise_()
                window.activateWindow()
                wait_for(window.isActiveWindow, "app window focus", timeout=10)
                subprocess.run(
                    ["spectacle", "--activewindow", "--background", "--nonotify", "--output", str(path)],
                    check=True, timeout=30,
                )
                wait_for(path.is_file, "desktop screenshot", timeout=10)
            elif not window.grab().save(str(path)):
                raise OSError(f"Could not save {filename}")
            captures.append(filename)
            print(f"Captured {filename}", flush=True)

        try:
            window.show()
            QTest.keyClicks(window.games_page.search, "Garry")
            QTest.mouseClick(window.games_page.find, Qt.MouseButton.LeftButton)
            wait_for(lambda: bool(window.games) and window.games_page.find.isEnabled(), "game search")
            model = window.games_page.results.model()
            wait_for(
                lambda: all(
                    model.data(model.index(i), ThumbRole) is not None
                    for i, game in enumerate(window.games) if game.image
                ),
                "game artwork",
            )
            if not any(game.appid == 4000 for game in window.games):
                raise RuntimeError("Garry's Mod was not present in the Steam search results")
            grab("games")
            row = next(i for i, game in enumerate(window.games) if game.appid == 4000)
            QTest.mouseClick(
                window.games_page.results.viewport(), Qt.MouseButton.LeftButton,
                pos=window.games_page.results.visualRect(model.index(row)).center(),
            )
            wait_for(lambda: bool(window.items) and not window._browse_loading, "Workshop browsing")
            window.browse.sortCombo.setFocus()
            QTest.keyClick(window.browse.sortCombo, Qt.Key.Key_Home)
            QTest.keyClick(window.browse.sortCombo, Qt.Key.Key_Down)
            wait_for(lambda: not window._browse_loading, "top-rated Workshop items")
            wait_for(
                lambda: all(
                    window.browse.card_thumb(item.publishedfileid)
                    for item in window.items if item.preview_url
                ),
                "Workshop artwork",
            )
            # Let Qt finish requests and remove any transient loading message.
            wait_for(lambda: window.hub.tp.activeThreadCount() == 0, "remaining public requests")
            grab("browse")
            # Pick a mod whose description reads well as plain text; some Workshop
            # descriptions contain raw markup that is noisy in a finished screenshot.
            rows = range(min(8, window.browse.grid_model.rowCount()))
            for row in rows:
                QTest.mouseClick(
                    window.browse.cards.viewport(), Qt.MouseButton.LeftButton,
                    pos=window.browse.cards.visualRect(window.browse.grid_model.index(row)).center(),
                )
                wait_for(lambda: window.browse.inspector._deps_item is not None, "item details")
                wait_for(lambda: window.hub.tp.activeThreadCount() == 0, "details and artwork")
                if window.browse.inspector.error_label.text():
                    raise RuntimeError(window.browse.inspector.error_label.text())
                description = window.browse.inspector.desc.text()
                if not any(mark in description for mark in ("[", "http")):
                    break
            else:
                raise RuntimeError("No Workshop item with a clean description was found")
            window.browse.cards.clearFocus()
            window.setFocus(Qt.FocusReason.OtherFocusReason)
            grab("details")
            manifest = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source": "Visible app window captured by KDE Spectacle" if desktop else "Offscreen native Qt rendering",
                "platform": app.platformName(),
                "window_size": [window.width(), window.height()],
                "screenshots": captures,
                "game_search": "Garry",
                "games": [
                    {"appid": game.appid, "name": game.name, "artwork_url": game.image}
                    for game in window.games
                ],
                "game": {"appid": 4000, "name": window.current_game.name},
                "workshop_url": "https://steamcommunity.com/workshop/browse/?appid=4000&browsesort=toprated",
                "items": [
                    {"id": it.publishedfileid, "title": it.title, "url": it.url,
                     "artwork_url": it.preview_url}
                    for it in window.items
                ],
            }
            (out / "live-capture.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        finally:
            window.close()
            window.hub.tp.waitForDone()
            app.processEvents()
            window.deleteLater()
            app.processEvents()
