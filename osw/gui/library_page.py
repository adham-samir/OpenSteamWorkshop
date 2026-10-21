"""Library workspace: installed Workshop content discovered under the mods root."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..models import fmt_size
from . import theme
from .components import StatePanel
from .item_models import INSTALLED_ACTIONS, InstalledItemRole, InstalledLibraryModel


class LibraryPage(QWidget):
    """Intent: refresh / open root / per-item actions; the controller scans."""

    refresh_requested = Signal()
    check_updates_requested = Signal()
    update_all_requested = Signal()
    cleanup_requested = Signal()
    open_root_requested = Signal()
    action_requested = Signal(object, str)  # InstalledItem, action label

    def __init__(self):
        super().__init__()
        self._content_dir: Path | None = None
        self.model = InstalledLibraryModel(self)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 8)
        v.setSpacing(9)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Library")
        title.setStyleSheet("font-size: 19px; font-weight: 650;")
        self.subheader = QLabel(
            "Workshop content installed under your mods root or per-game mods folders."
        )
        self.subheader.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12.5px;")
        title_box.addWidget(title)
        title_box.addWidget(self.subheader)
        head.addLayout(title_box, 1)

        self.check_btn = QPushButton("Check for updates")
        self.check_btn.setAccessibleName("Check installed Workshop items for newer versions")
        self.check_btn.clicked.connect(self.check_updates_requested.emit)
        head.addWidget(self.check_btn)

        self.update_all_btn = QPushButton("Update all")
        self.update_all_btn.setAccessibleName("Review and install all available mod updates")
        self.update_all_btn.setEnabled(False)
        self.update_all_btn.clicked.connect(self.update_all_requested.emit)
        head.addWidget(self.update_all_btn)

        self.cleanup_btn = QPushButton("Cleanup")
        self.cleanup_btn.setAccessibleName("Review and remove duplicate installed copies")
        self.cleanup_btn.setEnabled(False)
        self.cleanup_btn.clicked.connect(self.cleanup_requested.emit)
        head.addWidget(self.cleanup_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setAccessibleName("Rescan installed Workshop content")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        head.addWidget(self.refresh_btn)

        self.open_root_btn = QPushButton("Open mods folder")
        self.open_root_btn.clicked.connect(self.open_root_requested.emit)
        head.addWidget(self.open_root_btn)
        v.addLayout(head)

        self.path_label = QLabel("")
        self.path_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11.5px;")
        self.path_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.path_label)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.verticalHeader().setMinimumSectionSize(46)
        self.table.setAlternatingRowColors(False)
        self.table.setAccessibleName("Installed Workshop items")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 145)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 125)
        self.table.setColumnWidth(5, 130)
        self.table.setCornerButtonEnabled(False)
        self.table.doubleClicked.connect(self._open_selected_folder)

        self.state_panel = StatePanel()
        self._stack = QStackedWidget()
        self._stack.addWidget(self.table)
        self._stack.addWidget(self.state_panel)
        v.addWidget(self._stack, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        v.addWidget(self.summary)

        self.action_bar = QWidget()
        ab = QHBoxLayout(self.action_bar)
        ab.setContentsMargins(0, 2, 0, 0)
        ab.setSpacing(8)
        self.sel_label = QLabel("")
        self.sel_label.setStyleSheet(f"color: {theme.TEXT2};")
        ab.addWidget(self.sel_label)
        ab.addStretch(1)
        self.action_buttons: list[QPushButton] = []
        v.addWidget(self.action_bar)

        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self.update_actions(self.table.selectionModel().currentIndex())
        )
        self.show_empty(None)

    # ------------------------------------------------------------- state

    @property
    def content_dir(self) -> Path | None:
        return self._content_dir

    def _set_path(self, path) -> None:
        self._content_dir = Path(path) if path else None
        text = str(self._content_dir) if self._content_dir is not None else "No mods root configured"
        self.path_label.setText(text)
        self.path_label.setToolTip(text)

    def set_duplicates(self, count: int) -> None:
        count = max(0, int(count))
        self.cleanup_btn.setText(f"Cleanup ({count})" if count else "Cleanup")
        self.cleanup_btn.setEnabled(bool(count))
        self.cleanup_btn.setToolTip(
            f"{count} installed items have duplicate copies" if count else ""
        )

    def show_loading(self, path) -> None:
        self.model.set_items([])
        self.set_duplicates(0)
        self._content_dir = Path(path) if path else None
        text = str(self._content_dir) if self._content_dir is not None else "your mods root"
        self.path_label.setText(f"Scanning: {text}")
        self.path_label.setToolTip(text)
        self.summary.setText("")
        self._sync_update_all()
        self.state_panel.set_state(
            "loading",
            "Scanning installed content…",
            f"Reading {text}. Large libraries can take a moment.",
        )
        self._stack.setCurrentIndex(1)
        self.table.setEnabled(False)
        self.action_bar.setVisible(False)
        self.update_actions()

    def show_items(self, items, path=None, duplicates: int = 0) -> None:
        if path is not None:
            self._set_path(path)
        items = list(items or [])
        self.model.set_items(items)
        self.set_duplicates(duplicates)
        self.table.setEnabled(True)
        if not items:
            self.show_empty(self._content_dir)
            return
        self._stack.setCurrentIndex(0)
        self.action_bar.setVisible(True)
        self._render_summary()
        self.update_actions(self.table.selectionModel().currentIndex())

    def show_empty(self, path=None) -> None:
        if path is not None or self._content_dir is None:
            self._set_path(path)
        self.model.set_items([])
        self.set_duplicates(0)
        self.table.setEnabled(True)
        text = str(self._content_dir) if self._content_dir is not None else "your mods root"
        self.summary.setText("")
        self._sync_update_all()
        self.state_panel.set_state(
            "empty",
            "No installed Workshop content",
            (
                f"Nothing was found under {text} or your per-game mods folders. "
                "Download a mod, or change the mods root in Settings."
            ),
            [
                ("Refresh", "primary", self.refresh_requested.emit),
                ("Open mods folder", "", self.open_root_requested.emit),
            ],
        )
        self._stack.setCurrentIndex(1)
        self.action_bar.setVisible(False)
        self.update_actions()

    def show_error(self, message: str, path=None) -> None:
        if path is not None:
            self._set_path(path)
        self.model.set_items([])
        self.set_duplicates(0)
        self.table.setEnabled(True)
        self.summary.setText("")
        self._sync_update_all()
        self.state_panel.set_state(
            "error",
            "Could not scan the library",
            str(message),
            [("Try again", "primary", self.refresh_requested.emit)],
        )
        self._stack.setCurrentIndex(1)
        self.action_bar.setVisible(False)
        self.update_actions()

    def apply_metadata(self, metadata: dict) -> None:
        self.model.apply_metadata(metadata)

    def apply_update_status(self, statuses) -> None:
        self.model.set_update_status(statuses)
        self._render_summary()
        self.update_actions(self.table.selectionModel().currentIndex())

    def mark_updated(self, fileid: int) -> None:
        self.model.mark_updated(fileid)
        self._render_summary()
        self.update_actions(self.table.selectionModel().currentIndex())

    def set_checking(self, running: bool) -> None:
        self.check_btn.setEnabled(not running)
        self.check_btn.setText("Checking for updates…" if running else "Check for updates")

    def _sync_update_all(self) -> None:
        available = self.model.update_count()
        self.update_all_btn.setEnabled(bool(available))
        self.update_all_btn.setText(
            f"Update all ({available})" if available else "Update all"
        )

    def _render_summary(self) -> None:
        count = self.model.rowCount()
        self._sync_update_all()
        if count == 0:
            self.summary.setText("")
            return
        total = fmt_size(self.model.total_size()) or "unknown size"
        noun = "item" if count == 1 else "items"
        text = f"{count} installed {noun} · {total}"
        if self.model.checked_count():
            available = self.model.update_count()
            if available:
                noun = "update" if available == 1 else "updates"
                text += f" · {available} {noun} available"
            elif self.model.up_to_date_count():
                text += " · everything up to date"
        self.summary.setText(text)

    def remove_item(self, fileid: int) -> None:
        self.model.remove(fileid)
        if self.model.rowCount() == 0:
            self.show_empty(self._content_dir)
            return
        self._render_summary()
        self.update_actions()

    # ----------------------------------------------------------- actions

    def _open_selected_folder(self, index) -> None:
        item = index.data(InstalledItemRole)
        if item is not None:
            self.action_requested.emit(item, "Open folder")

    def update_actions(self, index=None) -> None:
        layout = self.action_bar.layout()
        for button in list(self.action_buttons):
            button.hide()
            layout.removeWidget(button)
            button.deleteLater()
        self.action_buttons.clear()

        item = (
            index.data(InstalledItemRole)
            if index is not None and index.isValid()
            else None
        )
        if item is None:
            self.sel_label.setText("Select an installed item to act on it…")
            return
        self.sel_label.setText(f"{item.label} —")
        for label in INSTALLED_ACTIONS:
            if label == "Update" and not self.model.update_available(item.fileid):
                continue
            button = QPushButton(label)
            button.setAccessibleName(f"{label} {item.label}")
            button.clicked.connect(
                lambda _=False, target=item, action=label: self.action_requested.emit(
                    target, action
                )
            )
            if label == "Delete":
                button.setProperty("role", "danger")
            elif label == "Re-download":
                button.setProperty("role", "primary")
            layout.addWidget(button)
            self.action_buttons.append(button)
