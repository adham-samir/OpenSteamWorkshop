"""Library workspace: installed Workshop content discovered under the mods root."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from .library import UNAVAILABLE, UNKNOWN, UP_TO_DATE, UPDATE_AVAILABLE


class InstalledFilter(QSortFilterProxyModel):
    """Filtering stays in the view; rows retain their authoritative item object."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.appid = None
        self.query = ""
        self.update_state = "all"
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        item = model.item_at(row)
        if item is None or (self.appid is not None and item.appid != self.appid):
            return False
        if self.query and self.query not in f"{item.label} {item.game_label} {item.fileid} {item.path}".casefold():
            return False
        update = model.update_for(item.fileid)
        status = update.status if update else UNKNOWN
        return self.update_state == "all" or status == self.update_state


class LibraryPage(QWidget):
    """Intent: refresh / open root / per-item actions; the controller scans."""

    refresh_requested = Signal()
    check_updates_requested = Signal()
    update_all_requested = Signal()
    cleanup_requested = Signal()
    open_root_requested = Signal()
    scope_changed = Signal()
    action_requested = Signal(object, str)  # InstalledItem, action label

    def __init__(self):
        super().__init__()
        self._content_dir: Path | None = None
        self.model = InstalledLibraryModel(self)
        self.proxy = InstalledFilter(self)
        self.proxy.setSourceModel(self.model)
        self._game = None
        self._all_games = False
        self._scope_contexts = {}
        self._duplicates = []

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 8)
        v.setSpacing(9)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Installed")
        title.setStyleSheet("font-size: 23px; font-weight: 650;")
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
        # Actions live below the heading so the minimum window stays readable.

        self.update_all_btn = QPushButton("Update all")
        self.update_all_btn.setAccessibleName("Review and install all available mod updates")
        self.update_all_btn.setEnabled(False)
        self.update_all_btn.clicked.connect(self.update_all_requested.emit)


        self.cleanup_btn = QPushButton("Cleanup")
        self.cleanup_btn.setAccessibleName("Review and remove duplicate installed copies")
        self.cleanup_btn.setEnabled(False)
        self.cleanup_btn.clicked.connect(self.cleanup_requested.emit)


        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setAccessibleName("Rescan installed Workshop content")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)


        self.open_root_btn = QPushButton("Open mods folder")
        self.open_root_btn.clicked.connect(self.open_root_requested.emit)

        v.addLayout(head)
        filters = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.setAccessibleName("Installed game scope")
        self.scope.addItem("All games", None)
        filters.addWidget(self.scope)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search installed mods")
        self.search.setAccessibleName("Search installed mods")
        filters.addWidget(self.search, 1)
        self.update_filter = QComboBox()
        self.update_filter.setAccessibleName("Filter installed mods by update status")
        for label, value in (("All update states", "all"), ("Update available", UPDATE_AVAILABLE),
                             ("Up to date", UP_TO_DATE), ("Unavailable", UNAVAILABLE), ("Not checked", UNKNOWN)):
            self.update_filter.addItem(label, value)
        filters.addWidget(self.update_filter)
        v.addLayout(filters)
        actions = QHBoxLayout()
        for button in (self.check_btn, self.update_all_btn, self.cleanup_btn, self.refresh_btn, self.open_root_btn):
            actions.addWidget(button)
        actions.addStretch(1)
        v.addLayout(actions)

        self.path_label = QLabel("")
        self.path_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11.5px;")
        self.path_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.path_label)

        self.table = QTableView()
        self.table.setModel(self.proxy)
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
        self.table.setColumnWidth(1, 125)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnHidden(4, True)
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
        self.sel_label.setMaximumWidth(200)
        self.sel_label.setStyleSheet(f"color: {theme.TEXT2};")
        ab.addWidget(self.sel_label)
        ab.addStretch(1)
        self.action_buttons: list[QPushButton] = []
        v.addWidget(self.action_bar)

        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self.update_actions(self.table.selectionModel().currentIndex())
        )
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.search.textChanged.connect(self._filter_changed)
        self.update_filter.currentIndexChanged.connect(self._filter_changed)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._filter_changed)
        # Metadata arrives row by row. The proxy updates those rows itself;
        # recount the displayed scope only once after the current batch.
        self.model.dataChanged.connect(lambda *_: self._filter_timer.start(0))
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
        self._filter_changed()
        self.table.setEnabled(True)
        if not items:
            self.show_empty(self._content_dir)
            return
        self._stack.setCurrentIndex(0)
        self.action_bar.setVisible(True)
        self._render_summary()
        self.update_actions(self.table.selectionModel().currentIndex())
        self._filter_changed()

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
        available = sum(self.model.update_available(item.fileid) for item in self.visible_items())
        self.update_all_btn.setEnabled(bool(available))
        self.update_all_btn.setText(
            f"Update all ({available})" if available else "Update all"
        )

    def _render_summary(self) -> None:
        count = self.proxy.rowCount()
        self._sync_update_all()
        if count == 0:
            self.summary.setText("0 installed items in this view")
            return
        total = fmt_size(sum(item.size for item in self.visible_items())) or "unknown size"
        noun = "item" if count == 1 else "items"
        text = f"{count} installed {noun} · {total}"
        if self.model.checked_count():
            available = sum(self.model.update_available(item.fileid) for item in self.visible_items())
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
        self._filter_changed()

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
        self.sel_label.setText(self.fontMetrics().elidedText(item.label, Qt.TextElideMode.ElideRight, 190))
        self.path_label.setText(str(item.path))
        self.path_label.setToolTip(str(item.path))
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

    def visible_items(self) -> list:
        return [self.proxy.index(row, 0).data(InstalledItemRole)
                for row in range(self.proxy.rowCount())]

    @property
    def installed_scope(self):
        return self.proxy.appid

    def set_game_context(self, game) -> None:
        previous = self.proxy.appid
        self._save_scope_context(previous)
        self._game = game
        self.scope.blockSignals(True)
        self.scope.clear()
        if game:
            self.scope.addItem(game.name, game.appid)
        self.scope.addItem("All games", None)
        self.scope.setCurrentIndex(self.scope.count()-1 if self._all_games else 0)
        self.scope.blockSignals(False)
        self._apply_scope()

    def set_installed_scope(self, appid=None) -> None:
        index = self.scope.findData(appid)
        if index >= 0:
            self.scope.setCurrentIndex(index)

    def _save_scope_context(self, scope):
        current = self.table.currentIndex().data(InstalledItemRole)
        self._scope_contexts[scope] = (self.search.text(), self.update_filter.currentIndex(),
                                       current.fileid if current else None,
                                       self.table.verticalScrollBar().value())

    def _scope_changed(self):
        self._save_scope_context(self.proxy.appid)
        self._all_games = self.scope.currentData() is None
        self._apply_scope()

    def _apply_scope(self):
        self.proxy.appid = self.scope.currentData()
        query, status, fileid, scroll = self._scope_contexts.get(self.proxy.appid, ("", 0, None, 0))
        self.search.blockSignals(True)
        self.search.setText(query)
        self.search.blockSignals(False)
        self.update_filter.blockSignals(True)
        self.update_filter.setCurrentIndex(status)
        self.update_filter.blockSignals(False)
        self._filter_changed()
        for row, item in enumerate(self.visible_items()):
            if item.fileid == fileid:
                self.table.setCurrentIndex(self.proxy.index(row, 0))
                break
        QTimer.singleShot(0, lambda: self.table.verticalScrollBar().setValue(scroll))
        self.scope_changed.emit()

    def _filter_changed(self, *_):
        self._filter_timer.stop()
        self.proxy.query = self.search.text().strip().casefold()
        self.proxy.update_state = self.update_filter.currentData() or "all"
        self.proxy.invalidate()
        self._render_summary()
        if self.model.rowCount():
            matched = bool(self.proxy.rowCount())
            self._stack.setCurrentIndex(0 if matched else 1)
            self.action_bar.setVisible(matched)
            if not matched:
                self.state_panel.set_state("empty", "No installed mods in this view",
                                           "Choose All games or change the search and update filter.")
        self.update_actions(self.table.currentIndex())
        if self._duplicates:
            ids = {item.fileid for item in self.visible_items()}
            self.set_duplicates(sum(group.fileid in ids for group in self._duplicates))

    def set_duplicate_groups(self, groups):
        self._duplicates = list(groups)
        ids = {item.fileid for item in self.visible_items()}
        self.set_duplicates(sum(group.fileid in ids for group in groups))
