"""Imports workspace: paste links/IDs, resolve, preview, queue. Replaces BulkDialog."""

from __future__ import annotations

import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .item_models import ImportPreviewModel


def _title() -> QLabel:
    return QLabel("")


class ImportPage(QWidget):
    """Intent: resolve_requested / stop_requested / queue_requested(list[item])."""

    resolve_requested = Signal(str, str, bool)  # references, hint, dependencies
    queue_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self._cancel = threading.Event()
        self._generation = 0
        self._closed = False
        self.resolution = None
        self._pending_hint = ""
        self._pending_dependencies = False

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 12)
        v.setSpacing(9)

        head = QVBoxLayout()
        head.setSpacing(2)
        self.title = QLabel("Imports")
        self.title.setStyleSheet("font-size: 19px; font-weight: 650;")
        self.subheader = QLabel("Paste Workshop item or collection links, or one item ID per line.")
        self.subheader.setStyleSheet("color: #98A3AF; font-size: 12.5px;")
        head.addWidget(self.title)
        head.addWidget(self.subheader)
        v.addLayout(head)

        self.source = QPlainTextEdit()
        self.source.setObjectName("ImportSource")
        self.source.setPlaceholderText("https://steamcommunity.com/sharedfiles/filedetails/?id=…")
        self.source.setMaximumHeight(130)
        self.source.setAccessibleName("Workshop references")
        v.addWidget(self.source)

        options = QHBoxLayout()
        self.file_button = QPushButton("Import text file…")
        self.file_button.clicked.connect(self._import_file)
        options.addWidget(self.file_button)
        options.addWidget(QLabel("Game ID hint"))
        self.hint = QLineEdit()
        self.hint.setPlaceholderText("Optional")
        self.hint.setMaximumWidth(110)
        options.addWidget(self.hint)
        self.dependencies = QCheckBox("Include required items recursively")
        options.addWidget(self.dependencies)
        options.addStretch(1)
        v.addLayout(options)

        self.summary = QLabel()
        self.summary.setText("Resolve the list to preview downloads. No files are downloaded during preview.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12.5px;")
        v.addWidget(self.summary)

        self.table = QTableView()
        self.tmodel = ImportPreviewModel(self)
        self.table.setModel(self.tmodel)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setFixedWidth(30)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 64)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(4, 92)
        self.table.setAccessibleName("Import preview")
        v.addWidget(self.table, 1)

        self.issues = QPlainTextEdit()
        self.issues.setReadOnly(True)
        self.issues.setMaximumHeight(96)
        self.issues.setPlaceholderText("Invalid entries and unresolved dependencies will be listed here.")
        v.addWidget(self.issues)

        actions = QHBoxLayout()
        self.resolve_button = QPushButton("Resolve list")
        self.resolve_button.clicked.connect(self.resolve)
        actions.addWidget(self.resolve_button)
        self.cancel_button = QPushButton("Stop resolving")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._stop)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        self.queue_button = QPushButton("Queue selected")
        self.queue_button.setAccessibleName("Queue checked mods for download")
        self.queue_button.setEnabled(False)
        self.queue_button.clicked.connect(self._queue_selected)
        actions.addWidget(self.queue_button)
        v.addLayout(actions)

        self.source.textChanged.connect(self._invalidate)
        self.hint.textChanged.connect(self._invalidate)
        self.dependencies.toggled.connect(self._invalidate)

    # ------------------------------------------------------------ preview

    def set_source(self, text: str, *, hint: str, dependencies: bool, auto_resolve: bool = True) -> None:
        """Entry point prefill (paste, URL import, context menu, hero)."""
        self._loading = True
        self.hint.setText(hint)
        self.dependencies.setChecked(dependencies)
        self.source.setPlainText(text)
        self._loading = False
        if auto_resolve and text.strip():
            self.resolve()

    def _import_file(self):
        name, _ = QFileDialog.getOpenFileName(
            self, "Import Workshop list", "", "Text files (*.txt);;All files (*)"
        )
        if name:
            try:
                self.source.appendPlainText(open(name, encoding="utf-8").read())
            except OSError as exc:
                self.summary.setText(f"Could not read {name}: {exc}")

    def _invalidate(self) -> None:
        if getattr(self, "_loading", False):
            return
        self._stop()
        self.resolution = None
        self.queue_button.setEnabled(False)
        self.tmodel.reset()
        self.issues.clear()
        self.summary.setText(
            "List changed — resolve it to preview downloads." if self.source.toPlainText().strip() else
            "Resolve the list to preview downloads. No files are downloaded during preview."
        )

    def _stop(self):
        self._cancel.set()
        self._generation += 1
        self.resolve_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def resolve(self) -> None:
        self._invalidate()
        hint = self.hint.text().strip()
        if hint and (not hint.isdigit() or int(hint) <= 0):
            self.summary.setText("Game ID hint must be a positive integer.")
            return
        references = self.source.toPlainText()
        if not references.strip():
            self.summary.setText("Paste at least one Workshop link or item ID.")
            return
        cancel, generation = threading.Event(), self._generation
        self._cancel, self._generation = cancel, generation
        dependencies = self.dependencies.isChecked()
        self.resolve_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.summary.setText("Resolving items, collections and dependencies…")
        self.issues.clear()
        self.resolve_requested.emit(references, hint, dependencies)

    def resolve_cancelled(self) -> None:
        self.summary.setText("Resolution stopped.")
        self.resolve_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def resolve_finished(self, result) -> None:
        """Controller callback on the UI thread: render the resolution."""
        self.resolution = result
        self.tmodel.set_resolution(result)
        self.summary.setText(
            f"{len(result.items)} mods · {result.collections} collections · "
            f"{result.duplicates} duplicate references · {len(result.issues)} issues. "
            "Uncheck any mods you want to exclude."
        )
        self.issues.setPlainText("\n".join(f"{i.reference}: {i.message}" for i in result.issues))
        self.queue_button.setEnabled(bool(result.items))
        self.resolve_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def resolve_failed(self, message: str) -> None:
        self.summary.setText(message)
        self.resolve_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    # ------------------------------------------------------------ queueing

    def _queue_selected(self) -> None:
        if not self.resolution:
            return
        chosen = self.tmodel.checked()
        if not chosen:
            self.summary.setText("Select at least one mod to queue.")
            return
        self.queue_button.setEnabled(False)
        self.queue_requested.emit(chosen)

    def queue_accepted(self, count: int) -> None:
        """Controller confirms; the page resets for the next import."""
        self.summary.setText(
            f"Queued {count} item(s) for download — see the Downloads workspace."
        )
        self.source.clear()
        self.tmodel.reset()
        self.issues.clear()
        self.resolution = None
        self.queue_button.setEnabled(False)
