import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from osw import settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(settings, "CONFIG_FILE", tmp_path / "config/settings.json")
    # Keep filesystem scans off the developer's real ~/SteamMods folder.
    defaults = dict(settings.DEFAULTS)
    defaults["content_root"] = str(tmp_path / "mods")
    monkeypatch.setattr(settings, "DEFAULTS", defaults)
    monkeypatch.setattr(settings, "_LAST", {})


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app

    # Parentless page widgets used by unit tests are otherwise destroyed during
    # PySide's interpreter-shutdown walk, after their C++ side is gone, which
    # segfaults. Delete them while the application still exists.
    for widget in list(app.allWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass
    for _ in range(3):
        app.processEvents()
    app.quit()
