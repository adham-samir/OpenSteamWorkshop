"""Downloads workspace: filterable, model-driven job table with per-row actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .delegates import JobRowDelegate
from .item_models import JobFilter, JobTableModel


class DownloadsPage(QWidget):
    action_requested = Signal(str, str)   # job_id, action label
    filter_changed = Signal(int)
    page_action = Signal(str)             # resume / retry-failed / clear

    def __init__(self):
        super().__init__()
        self.model = JobTableModel(self)
        self.delegate = JobRowDelegate(self._dispatch, self)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 8)
        v.setSpacing(9)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Downloads")
        title.setStyleSheet("font-size: 23px; font-weight: 650;")
        self.subheader = QLabel("")
        self.subheader.setWordWrap(True)
        self.subheader.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12.5px;")
        title_box.addWidget(title)
        title_box.addWidget(self.subheader)
        head.addLayout(title_box, 1)
        self.resume_btn = QPushButton("Resume interrupted")
        self.resume_btn.clicked.connect(lambda: self.page_action.emit("resume"))

        self.retry_btn = QPushButton("Retry failed")
        self.retry_btn.clicked.connect(lambda: self.page_action.emit("retry"))

        self.clear_btn = QPushButton("Clear finished")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(lambda: self.page_action.emit("clear"))

        v.addLayout(head)
        page_actions = QHBoxLayout()
        for button in (self.resume_btn, self.retry_btn, self.clear_btn):
            page_actions.addWidget(button)
        page_actions.addStretch(1)
        v.addLayout(page_actions)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self._filters: dict[QPushButton, int] = {}
        for label, filt in (
            ("All", JobFilter.ALL),
            ("Active", JobFilter.ACTIVE),
            ("Needs attention", JobFilter.ATTENTION),
            ("Finished", JobFilter.FINISHED),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setAccessibleName(f"{label} downloads")
            btn.clicked.connect(lambda _=False, f=filt: self.set_filter(filt=f))
            self._filters[btn] = filt
            filters.addWidget(btn)
        filters.addStretch(1)
        self._filter_buttons = list(self._filters)
        self.set_filter(filt=JobFilter.ALL)
        v.addLayout(filters)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(94)
        self.table.verticalHeader().setMinimumSectionSize(62)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 170)
        self.table.horizontalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(94)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setCornerButtonEnabled(False)
        self.table.setAccessibleName("Download queue")

        self.empty_state = QLabel(
            "<b>No downloads yet.</b><br>"
            "Find a game in Games or use Import links to queue your first download."
        )
        self.empty_state.setStyleSheet(f"color: {theme.TEXT2}; font-size: 13px;")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.hide()

        stack = QStackedWidget()
        self._stack = stack
        stack.addWidget(self.table)
        stack.addWidget(self.empty_state)
        v.addWidget(stack, 1)
        self._sync_empty()

        self.table.selectionModel().selectionChanged.connect(
            lambda *a: self._emit_selected()
        )
        self.table.clicked.connect(
            lambda idx: self._dispatch_on_click(idx)
        )

        # selected-row action bar for accessibility + keyboard flows
        self.action_bar = QWidget()
        ab = QHBoxLayout(self.action_bar)
        ab.setContentsMargins(0, 2, 0, 0)
        ab.setSpacing(8)
        self.sel_label = QLabel("")
        self.sel_label.setMaximumWidth(190)
        self.sel_label.setStyleSheet(f"color: {theme.TEXT2};")
        ab.addWidget(self.sel_label)
        ab.addStretch(1)
        self.action_buttons: list[QPushButton] = []
        v.addWidget(self.action_bar)
        self.update_actions()  # ensure bar exists in an empty state

    # ------------------------------------------------------------ routing

    def _dispatch(self, job_id: str, action: str) -> None:
        self.action_requested.emit(job_id, action)

    def _dispatch_on_click(self, index) -> None:
        # clicks inside action buttons are consumed by the delegate; but let plain
        # row clicks simply move the selection bar.
        self._emit_selected()

    # -------------------------------------------------------------- state

    def upsert(self, snapshot) -> None:
        self.model.upsert(snapshot)
        self._sync_empty()
        self._sync_spans()
        self.update_counts()
        current = self.table.selectionModel().currentIndex()
        self.update_actions(current)

    def remove(self, job_id: str) -> None:
        self.model.remove(job_id)
        self._sync_empty()
        self._sync_spans()
        self.update_counts()

    def clear(self) -> None:
        self.model.clear()
        self._sync_empty()
        self._sync_spans()
        self.update_counts()

    def replace_all(self, jobs) -> None:
        self.model.replace_all(jobs)
        self._sync_empty()
        self._sync_spans()
        self.update_counts()

    def _sync_spans(self) -> None:
        """Paint one full-width row; the delegate draws every column itself."""
        if not hasattr(self, "table"):
            return
        self.table.clearSpans()
        columns = self.model.columnCount()
        for row in range(self.model.rowCount()):
            self.table.setSpan(row, 0, 1, columns)

    def update_counts(self) -> None:
        counts = self.model.counts()
        for btn, filt in self._filters.items():
            label = btn.text().split("  ")[0].strip()
            n = counts.get(filt, 0)
            btn.setText(f"{label}  {n}")
        self.clear_btn.setEnabled(counts.get(JobFilter.FINISHED, 0) > 0)
        from ..queue import JobState
        snapshots = list(self.model._snapshots.values())
        self.resume_btn.setEnabled(any(s.state is JobState.INTERRUPTED for s in snapshots))
        self.retry_btn.setEnabled(any(s.state is JobState.FAILED for s in snapshots))

    def set_filter(self, *, filt: int) -> None:
        self.model.set_filter(filt)
        for btn, value in self._filters.items():
            btn.setChecked(value == filt)
        self._sync_spans()
        if hasattr(self, "_stack"):
            self._sync_empty()
            self.update_actions()
        self.filter_changed.emit(filt)

    # ------------------------------------------------- selected-row bar

    def _emit_selected(self) -> None:
        current = self.table.selectionModel().currentIndex()
        self.update_actions(current)

    def update_actions(self, index=None) -> None:
        from .item_models import actions_for

        snap = self.model.snapshot(index.row()) if index is not None and index.isValid() else None
        labels = tuple(actions_for(snap)) if snap else ()
        key = (snap.id, labels) if snap else None
        self.sel_label.setText(
            self.fontMetrics().elidedText(snap.title, Qt.TextElideMode.ElideRight, 180)
            if snap else "Select a row to act on it…"
        )
        if hasattr(self, "_actions_key") and self._actions_key == key:
            return
        self._actions_key = key
        focused = QApplication.focusWidget()
        focus_label = focused.text() if focused in self.action_buttons else None
        bar = self.action_bar.layout()
        for button in list(self.action_buttons):
            bar.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.action_buttons.clear()
        for label in labels:
            btn = QPushButton(label)
            btn.setAccessibleName(f"{label} {snap.title}")
            btn.clicked.connect(
                lambda _=False, jid=snap.id, act=label: self.action_requested.emit(jid, act)
            )
            if label == "Cancel":
                btn.setStyleSheet(f"QPushButton {{ color: {theme.BAD}; }}")
            elif label in ("Retry", "Resume", "Retry with account"):
                btn.setStyleSheet(f"QPushButton {{ color: {theme.ACCENT}; }}")
            bar.addWidget(btn)
            self.action_buttons.append(btn)
        if focus_label and self.action_buttons:
            target = next((button for button in self.action_buttons if button.text() == focus_label),
                          self.action_buttons[0])
            target.setFocus()
        elif focus_label:
            self.table.setFocus()

    # ------------------------------------------------------------ empty

    def _sync_empty(self) -> None:
        empty = self.model.rowCount() == 0
        self._stack.setCurrentIndex(1 if empty else 0)
        if self.model._snapshots:
            self.empty_state.setText("No downloads match this filter.")
        else:
            self.empty_state.setText("<b>No downloads yet.</b><br>Find a game or import Workshop links to get started.")

    def set_concurrency(self, count):
        self.subheader.setText(
            f"Up to {count} games downloading at once · items for each game run one at a time."
            if count > 1 else "One download at a time · change concurrency in Settings."
        )
