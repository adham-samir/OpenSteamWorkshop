"""Downloads workspace: filters, serial queue actions and job detail."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...queue import ACTIVE, JobSnapshot, JobState
from ..components import (
    DownloadTableModel,
    InlineNotice,
    ProgressDelegate,
    StatePanel,
    configure_download_columns,
    table_view,
)
from ..theme import MUTED, icon, mono_font


class DownloadsPage(QWidget):
    cancelJob = Signal(str)
    retryJob = Signal(str)
    retryWithAccount = Signal(str)
    showLog = Signal(str)
    openFolder = Signal(str)
    resumeUnfinished = Signal()
    retryFailed = Signal()
    clearFinished = Signal()
    browseRequested = Signal()

    FILTERS = (
        (DownloadTableModel.ALL, "All"),
        (DownloadTableModel.ACTIVE, "Active"),
        (DownloadTableModel.ATTENTION, "Needs attention"),
        (DownloadTableModel.FINISHED, "Finished"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_id = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        sub = QLabel(
            "SteamCMD runs one job at a time. Progress, queue counts and failures here are "
            "driven by the live job snapshots."
        )
        sub.setProperty("role", "muted")
        sub.setWordWrap(True)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        self.resume_button = QPushButton("Resume unfinished")
        self.resume_button.setIcon(icon("play", MUTED, 14))
        self.resume_button.clicked.connect(lambda: self.resumeUnfinished.emit())
        self.resume_button.setAccessibleName("Resume unfinished downloads")
        head.addWidget(self.resume_button)
        self.retry_failed_button = QPushButton("Retry failed")
        self.retry_failed_button.setIcon(icon("refresh", MUTED, 14))
        self.retry_failed_button.clicked.connect(lambda: self.retryFailed.emit())
        self.retry_failed_button.setAccessibleName("Retry all failed downloads")
        head.addWidget(self.retry_failed_button)
        self.clear_button = QPushButton("Clear finished")
        self.clear_button.setIcon(icon("trash", MUTED, 14))
        self.clear_button.clicked.connect(lambda: self.clearFinished.emit())
        self.clear_button.setAccessibleName("Clear finished downloads")
        head.addWidget(self.clear_button)
        layout.addLayout(head)

        filters = QHBoxLayout()
        filters.setSpacing(7)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in self.FILTERS:
            button = QPushButton(label)
            button.setProperty("role", "chip")
            button.setCheckable(True)
            button.setAccessibleName(f"Show {label.lower()} downloads")
            button.clicked.connect(lambda checked=False, k=key: self.set_filter(k))
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filters.addWidget(button)
        self.filter_buttons[DownloadTableModel.ALL].setChecked(True)
        filters.addStretch(1)
        self.filter_summary = QLabel("")
        self.filter_summary.setProperty("role", "muted")
        filters.addWidget(self.filter_summary)
        layout.addLayout(filters)

        self.notice = InlineNotice()
        layout.addWidget(self.notice)

        self.model = DownloadTableModel(self)
        self.table = table_view(self.model)
        self.table.setAccessibleName("Download jobs")
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setItemDelegateForColumn(3, ProgressDelegate(self.table))
        self.table.doubleClicked.connect(self._double_clicked)
        configure_download_columns(self.table)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.empty_state = StatePanel()
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.empty_state)
        self.table_stack.addWidget(self.table)
        layout.addWidget(self.table_stack, 1)

        self.action_bar = QFrame()
        self.action_bar.setProperty("panel", "raised")
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(12, 8, 8, 8)
        action_layout.setSpacing(7)
        labels = QVBoxLayout()
        labels.setSpacing(1)
        self.selection_title = QLabel("Select a job to act on it")
        self.selection_title.setProperty("role", "h3")
        labels.addWidget(self.selection_title)
        self.selection_detail = QLabel("Completed jobs expose folders and logs.")
        self.selection_detail.setProperty("role", "muted")
        self.selection_detail.setFont(mono_font(9))
        self.selection_detail.setWordWrap(False)
        labels.addWidget(self.selection_detail)
        action_layout.addLayout(labels, 1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.setIcon(icon("cancel", "#FF7A7A", 14))
        self.cancel_button.clicked.connect(lambda: self._emit(self.cancelJob))
        action_layout.addWidget(self.cancel_button)
        self.retry_button = QPushButton("Retry")
        self.retry_button.setIcon(icon("refresh", MUTED, 14))
        self.retry_button.clicked.connect(lambda: self._emit(self.retryJob))
        action_layout.addWidget(self.retry_button)
        self.account_button = QPushButton("Retry with account…")
        self.account_button.setIcon(icon("user", MUTED, 14))
        self.account_button.clicked.connect(lambda: self._emit(self.retryWithAccount))
        action_layout.addWidget(self.account_button)
        self.log_button = QPushButton("Show log")
        self.log_button.setIcon(icon("log", MUTED, 14))
        self.log_button.clicked.connect(lambda: self._emit(self.showLog))
        action_layout.addWidget(self.log_button)
        self.folder_button = QPushButton("Open folder")
        self.folder_button.setIcon(icon("folder", MUTED, 14))
        self.folder_button.clicked.connect(lambda: self._emit(self.openFolder))
        action_layout.addWidget(self.folder_button)
        layout.addWidget(self.action_bar)
        self._update_actions()

    # -------------------------------------------------------------- data

    def set_jobs(self, jobs: list[JobSnapshot]) -> None:
        selected = self._selected_id or (self.selected_job().id if self.selected_job() else "")
        self.model.set_jobs(jobs)
        self._refresh_counts()
        self._refresh_empty()
        if selected:
            self.select_job(selected)
        else:
            self._update_actions()

    def update_job(self, job: JobSnapshot) -> None:
        """Apply a live snapshot; progress ticks keep the current selection."""
        selected = self._selected_id
        self.model.update_job(job)
        self._refresh_counts()
        self._refresh_empty()
        if selected and self.model.row_for_id(selected) >= 0:
            row = self.model.row_for_id(selected)
            if not self.table.selectionModel().selectedRows():
                self.table.selectRow(row)
        self._update_actions()

    def _refresh_counts(self) -> None:
        counts = self.model.counts()
        for key, label in self.FILTERS:
            self.filter_buttons[key].setText(f"{label}  {counts.get(key, 0)}")
        self.resume_button.setEnabled(counts.get("interrupted", 0) > 0)
        self.retry_failed_button.setEnabled(counts.get("failed", 0) > 0)
        self.clear_button.setEnabled(
            counts.get(DownloadTableModel.FINISHED, 0) > 0
            or counts.get("failed", 0) > 0
        )
        self.filter_summary.setText(
            f"{counts.get('queued', 0)} queued · {counts.get('failed', 0)} failed · "
            f"{counts.get('done', 0)} complete"
        )

    def _refresh_empty(self) -> None:
        if self.model.rowCount():
            self.table_stack.setCurrentWidget(self.table)
            return
        key = self.model.filter_key()
        if key == DownloadTableModel.ACTIVE:
            self.empty_state.set_state(
                "success",
                "No active downloads",
                "SteamCMD is idle. Queued and running jobs will appear here automatically.",
                [("Show all jobs", "", lambda: self.set_filter(DownloadTableModel.ALL))],
            )
        elif key == DownloadTableModel.ATTENTION:
            self.empty_state.set_state(
                "success",
                "Nothing needs attention",
                "There are no failed or interrupted jobs. Nice.",
                [("Show all jobs", "", lambda: self.set_filter(DownloadTableModel.ALL))],
            )
        elif key == DownloadTableModel.FINISHED:
            self.empty_state.set_state(
                "empty",
                "No finished downloads",
                "Completed and cancelled jobs collect here with their logs and output folders.",
                [("Show active", "", lambda: self.set_filter(DownloadTableModel.ACTIVE))],
            )
        else:
            self.empty_state.set_state(
                "empty",
                "No download jobs yet",
                "Find something to download in Browse, or resolve a Workshop link list in Imports. "
                "Nothing downloads without your confirmation.",
                [("Browse Workshop", "primary", self.browseRequested.emit)],
            )
        self.table_stack.setCurrentWidget(self.empty_state)

    def set_filter(self, key: str) -> None:
        self.model.set_filter(key)
        self.filter_buttons[key].setChecked(True)
        self._selected_id = ""
        self.table.clearSelection()
        self._refresh_counts()
        self._refresh_empty()
        self._update_actions()

    def current_filter(self) -> str:
        return self.model.filter_key()

    def select_job(self, job_id: str) -> None:
        row = self.model.row_for_id(job_id)
        if row < 0:
            self._update_actions()
            return
        self._selected_id = job_id
        self.table.selectRow(row)
        self.table.scrollTo(self.model.index(row, 0))
        self.table.setFocus()
        self._update_actions()

    def selected_job(self) -> JobSnapshot | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self.model.job_at(rows[0].row())

    def _selection_changed(self, selected, deselected) -> None:
        job = self.selected_job()
        self._selected_id = job.id if job else ""
        self._update_actions()

    def _update_actions(self) -> None:
        job = self.selected_job()
        has_job = job is not None
        active = bool(job and job.state in ACTIVE)
        needs_retry = bool(job and job.state not in ACTIVE and not job.inflight)
        access_issue = bool(
            job
            and job.state is JobState.FAILED
            and job.error_kind in ("access", "authentication")
        )
        self.cancel_button.setEnabled(active)
        self.retry_button.setEnabled(needs_retry)
        self.account_button.setVisible(access_issue)
        self.account_button.setEnabled(access_issue and not job.inflight)
        self.log_button.setEnabled(has_job)
        self.folder_button.setEnabled(bool(job and job.state is JobState.DONE and job.output_path))
        if not job:
            self.selection_title.setText("Select a job to act on it")
            self.selection_detail.setText("Completed jobs expose folders and logs.")
            self.selection_title.setToolTip("")
            return
        self.selection_title.setText(f"{job.title} · {job.state.value}")
        first_line = (job.message or "No detail yet").splitlines()[0]
        elapsed = f"attempt {job.attempts} · " if job.attempts else ""
        self.selection_detail.setText(f"{elapsed}{first_line}"[:220])
        self.selection_detail.setToolTip(job.message)
        self.selection_title.setToolTip(job.message)

    def _emit(self, signal) -> None:
        job = self.selected_job()
        if job is not None:
            signal.emit(job.id)

    def _double_clicked(self, index) -> None:
        job = self.model.job_at(index.row())
        if job is None:
            return
        self.select_job(job.id)
        if job.state in (JobState.FAILED, JobState.INTERRUPTED):
            self.retryJob.emit(job.id)
        else:
            self.showLog.emit(job.id)

    def mark_notice(self, kind: str, text: str) -> None:
        self.notice.show_message(kind, text)

    def focus_primary(self) -> None:
        if self.model.rowCount():
            current = self.table.currentIndex()
            if not current.isValid():
                self.table.selectRow(0)
            self.table.setFocus()

    def select_most_relevant(self) -> None:
        jobs = self.model.jobs()
        target = next((j for j in jobs if j.state in ACTIVE), None)
        target = target or next((j for j in jobs if j.state in (JobState.FAILED, JobState.INTERRUPTED)), None)
        if target is not None:
            if self.model.row_for_id(target.id) < 0:
                self.set_filter(DownloadTableModel.ALL)
            self.select_job(target.id)


__all__ = ["DownloadsPage"]
