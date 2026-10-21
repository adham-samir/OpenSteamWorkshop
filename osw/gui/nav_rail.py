"""Left navigation: Browse / Imports / Library / Downloads / Settings; icon rail below 1120 px."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

WIDE_W, RAIL_W = 208, 64
ITEM_H = 40


class NavButton(QPushButton):
    """One nav destination; accessible name persists even in icon-rail mode."""

    def __init__(self, key: str, title: str, icon_name: str):
        super().__init__()
        self.key = key
        self.icon_name = icon_name
        self.setObjectName(f"nav_{key}")
        self.setProperty("nav", True)
        self._title = title
        self.setText(title)
        self.setAccessibleName(title)
        self.setToolTip(f"{title} — {self._tooltip_hint()}")
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(ITEM_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _tooltip_hint(self) -> str:
        return {
            "browse": "games and Workshop content",
            "imports": "paste links, files, and IDs",
            "library": "installed Workshop content",
            "downloads": "queue, progress, failures",
            "settings": "storage, account, SteamCMD",
        }.get(self.key, "")

    def set_compact(self, compact: bool, counts: str = "") -> None:
        if compact:
            self.setText("")
            tip = f"{self._title} ({counts})" if counts else self._title
            self.setToolTip(tip)
            self.setAccessibleName(self._title)
            self.setAccessibleDescription(tip)
        else:
            self.setText(f"{self._title}  {counts}" if counts else self._title)
            self.setToolTip(f"{self._title} — {self._tooltip_hint()}")


class NavRail(QFrame):
    """Brand, primary destinations, live counts, and the Secondary group."""

    navigate = Signal(str)
    switch_requested = Signal()
    LABELS = {
        "games": "Games",
        "browse": "Browse mods",
        "imports": "Import links",
        "library": "Installed",
        "downloads": "Downloads",
        "settings": "Settings",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setFixedWidth(WIDE_W)
        self._compact = False
        self._library_count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 14, 10, 12)
        outer.setSpacing(2)

        brand = QWidget()
        brand_lay = QHBoxLayout(brand)
        brand_lay.setContentsMargins(0, 0, 0, 12)
        brand_lay.setSpacing(9)
        badge = QLabel()
        badge.setFixedSize(26, 26)
        badge.setPixmap(icons.icon("brand", theme.ACCENT_TEXT, 16).pixmap(17, 17))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {theme.ACCENT}; border-radius: 7px;"
            f"border: 1px solid {theme.ACCENT};"
        )
        brand_lay.addWidget(badge)
        self.brand_label = QLabel("OpenWorkshop")
        self.brand_label.setObjectName("brandName")
        brand_lay.addWidget(self.brand_label, 1)
        outer.addWidget(brand)

        self.switcher = QPushButton("Select a game")
        self.switcher.setIcon(icons.icon("browse"))
        self.switcher.setFixedHeight(40)
        self.switcher.setAccessibleName("Switch game")
        self.switcher.clicked.connect(self.switch_requested.emit)
        outer.addWidget(self.switcher)
        outer.addSpacing(16)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, NavButton] = {}
        for key, title, icon_name in (
            ("games", "Games", "browse"),
            ("browse", "Browse mods", "search"),
            ("imports", "Import links", "import"),
            ("library", "Installed", "stack"),
            ("downloads", "Downloads", "transfer"),
        ):
            btn = NavButton(key, title, icon_name)
            btn.setIcon(icons.icon(icon_name, theme.TEXT2, 15))
            btn.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            outer.addWidget(btn)
            if key == "imports":
                btn.hide()

        self.spacer = QWidget()
        outer.addWidget(self.spacer, 1)

        self.secondary_label = QLabel("")
        self.secondary_label.setObjectName("navSection")
        outer.addWidget(self.secondary_label)
        self._settings_btn = NavButton("settings", "Settings", "settings")
        self._settings_btn.setIcon(icons.icon("settings", theme.TEXT2, 15))
        self._settings_btn.setAccessibleDescription("Storage, account, and SteamCMD configuration")
        self._settings_btn.clicked.connect(lambda: self.navigate.emit("settings"))
        self._group.addButton(self._settings_btn)
        outer.addWidget(self._settings_btn)

        self.hint = QLabel("Ctrl+F  Find games\nCtrl+L  Installed")
        self.hint.setObjectName("navHint")
        self.hint.setWordWrap(True)
        outer.addSpacing(6)
        outer.addWidget(self.hint)

    # ---------------------------------------------------------------- api

    @property
    def buttons(self) -> dict[str, NavButton]:
        return {**self._buttons, "settings": self._settings_btn}

    @property
    def library_count(self) -> int:
        return self._library_count

    def is_collapsed(self) -> bool:
        return self._compact

    def active(self) -> str:
        for key, button in self.buttons.items():
            if button.isChecked():
                return key
        return "browse"

    def set_active(self, key: str) -> None:
        btn = self._buttons.get(key) or self._settings_btn
        btn.setChecked(True)

    def set_library_count(self, count: int) -> None:
        self._library_count = max(0, int(count or 0))
        self._sync_library_button()

    def _sync_library_button(self) -> None:
        button = self._buttons.get("library")
        if button is None:
            return
        counts = f"{self._library_count} installed" if self._library_count else ""
        button.set_compact(self._compact, counts)
        button.setAccessibleDescription(
            f"{self._library_count} installed Workshop item(s)"
            if self._library_count
            else "No installed Workshop content"
        )

    def set_counts(self, queued: int, failed: int) -> None:
        chip = []
        if queued:
            chip.append(f"{queued} queued")
        if failed:
            chip.append(f"{failed} failed")
        counts = " · ".join(chip) if chip else ""
        compact = self._compact
        btn = self._buttons["downloads"]
        btn.set_compact(compact, counts if compact else "")
        btn.setProperty("warn", bool(queued))
        btn.setStyleSheet(btn.styleSheet())  # re-evaluate property styles
        btn.setToolTip(
            btn.toolTip().split(" — ")[0]
            + (" — " + counts if counts else " — no active jobs")
        )

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self.setFixedWidth(RAIL_W if compact else WIDE_W)
        self.switcher.setText("" if compact else self.fontMetrics().elidedText(getattr(self, "_game_name", "Select a game"), Qt.TextElideMode.ElideRight, 135))
        self.brand_label.setVisible(not compact)
        self.secondary_label.setVisible(not compact)
        self.hint.setVisible(not compact)
        for btn in self._buttons.values():
            btn.set_compact(compact)
        self._settings_btn.set_compact(compact)
        self._sync_library_button()

    def set_game_context(self, game) -> None:
        self._game_name = game.name if game else "Select a game"
        self.switcher.setText("" if self._compact else self.fontMetrics().elidedText(self._game_name, Qt.TextElideMode.ElideRight, 135))
        self.switcher.setToolTip(f"Switch game: {self._game_name}")
