"""A cancellable import preview: resolve first, then queue the chosen mods."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..bulk import resolve_downloads
from ..models import fmt_size


class BulkDialog(QDialog):
    def __init__(
        self, hub, enqueue, parent=None, *, references="", appid_hint=None, dependencies=False
    ):
        super().__init__(parent)
        self.hub, self.enqueue = hub, enqueue
        self._cancel = threading.Event()
        self._generation = 0
        self._closed = False
        self.resolution = None
        self.setWindowTitle("Import Workshop mods")
        self.resize(820, 680)
        layout = QVBoxLayout(self)
        label = QLabel("Paste Workshop item or collection links, or one item ID per line.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.source = QPlainTextEdit()
        self.source.setPlaceholderText("https://steamcommunity.com/sharedfiles/filedetails/?id=…")
        self.source.setMaximumHeight(130)
        self.source.setPlainText(references)
        layout.addWidget(self.source)
        options = QHBoxLayout()
        file_button = QPushButton("Import text file…")
        file_button.clicked.connect(self._import_file)
        options.addWidget(file_button)
        options.addWidget(QLabel("Game ID hint"))
        self.hint = QLineEdit(str(appid_hint or ""))
        self.hint.setPlaceholderText("Optional")
        self.hint.setMaximumWidth(110)
        options.addWidget(self.hint)
        self.dependencies = QCheckBox("Include required items recursively")
        self.dependencies.setChecked(dependencies)
        options.addWidget(self.dependencies)
        options.addStretch()
        layout.addLayout(options)
        self.summary = QLabel(
            "Resolve the list to preview downloads. No files are downloaded during preview."
        )
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Include", "Mod", "Game ID", "Source", "Size"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 95)
        self.table.setColumnWidth(4, 90)
        layout.addWidget(self.table, 1)
        self.issues = QPlainTextEdit()
        self.issues.setReadOnly(True)
        self.issues.setMaximumHeight(110)
        self.issues.setPlaceholderText(
            "Invalid entries and unresolved dependencies will be listed here."
        )
        layout.addWidget(self.issues)
        actions = QHBoxLayout()
        self.resolve_button = QPushButton("Resolve list")
        self.resolve_button.clicked.connect(self.resolve)
        actions.addWidget(self.resolve_button)
        self.cancel_resolution = QPushButton("Stop resolving")
        self.cancel_resolution.setEnabled(False)
        self.cancel_resolution.clicked.connect(self._stop)
        actions.addWidget(self.cancel_resolution)
        actions.addStretch()
        self.queue_button = QPushButton("Queue selected")
        self.queue_button.setEnabled(False)
        self.queue_button.clicked.connect(self._queue_selected)
        actions.addWidget(self.queue_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.source.textChanged.connect(self._invalidate)
        self.hint.textChanged.connect(self._invalidate)
        self.dependencies.toggled.connect(self._invalidate)
        if references:
            QTimer.singleShot(0, self.resolve)

    def _invalidate(self):
        self._stop()
        self.resolution = None
        self.queue_button.setEnabled(False)
        self.table.setRowCount(0)
        self.issues.clear()
        self.summary.setText("List changed — resolve it to preview downloads.")

    def _stop(self):
        self._cancel.set()
        self._generation += 1
        self.resolve_button.setEnabled(True)
        self.cancel_resolution.setEnabled(False)

    def _import_file(self):
        name, _ = QFileDialog.getOpenFileName(
            self, "Import Workshop list", "", "Text files (*.txt);;All files (*)"
        )
        if name:
            try:
                self.source.appendPlainText(Path(name).read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as exc:
                self.summary.setText(f"Could not read list: {exc}")

    def resolve(self):
        self._invalidate()
        hint = self.hint.text().strip()
        if hint and (not hint.isdigit() or int(hint) <= 0):
            self.summary.setText("Game ID hint must be a positive integer.")
            return
        if not self.source.toPlainText().strip():
            self.summary.setText("Paste at least one Workshop link or item ID.")
            return
        self._cancel = threading.Event()
        cancel, generation = self._cancel, self._generation
        references = self.source.toPlainText()
        dependencies = self.dependencies.isChecked()
        self.resolve_button.setEnabled(False)
        self.cancel_resolution.setEnabled(True)
        self.summary.setText("Resolving items, collections and dependencies…")
        self.issues.clear()

        def done(result):
            if self._closed or generation != self._generation:
                return
            self.resolution = result
            self.table.setRowCount(len(result.items))
            for row, item in enumerate(result.items):
                include = QTableWidgetItem()
                include.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                include.setCheckState(Qt.Checked)
                self.table.setItem(row, 0, include)
                values = (
                    item.title,
                    str(item.appid),
                    "Required" if item.publishedfileid in result.dependencies else "Import",
                    fmt_size(item.file_size) or "Unknown",
                )
                for col, value in enumerate(values, 1):
                    self.table.setItem(row, col, QTableWidgetItem(value))
            self.summary.setText(
                f"{len(result.items)} mods · {result.collections} collections · "
                f"{result.duplicates} duplicate references · {len(result.issues)} issues. "
                "Uncheck any mods you want to exclude."
            )
            self.issues.setPlainText(
                "\n".join(f"{i.reference}: {i.message}" for i in result.issues)
            )
            self.queue_button.setEnabled(bool(result.items))

        def failed(error):
            if not self._closed and generation == self._generation:
                self.summary.setText(f"Could not resolve list: {error}")

        def finished():
            if not self._closed and generation == self._generation:
                self.resolve_button.setEnabled(True)
                self.cancel_resolution.setEnabled(False)

        self.hub.call(
            lambda: resolve_downloads(
                references, int(hint) if hint else None, dependencies, cancel
            ),
            done,
            on_error=failed,
            on_done=finished,
        )

    def _queue_selected(self):
        if not self.resolution:
            return
        chosen = [
            item
            for row, item in enumerate(self.resolution.items)
            if self.table.item(row, 0).checkState() == Qt.Checked
        ]
        if not chosen:
            self.summary.setText("Select at least one mod to queue.")
            return
        self.enqueue(chosen)
        self.accept()

    def done(self, result):
        self._closed = True
        self._stop()
        super().done(result)
