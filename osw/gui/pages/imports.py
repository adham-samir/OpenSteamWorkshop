"""Imports workspace: resolve, review, exclude and queue Workshop content."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...bulk import DownloadResolution
from ...models import WorkshopItem
from ..components import (
    ImportTableModel,
    InlineNotice,
    StatePanel,
    configure_import_columns,
    table_view,
)
from ..theme import MUTED, icon, mono_font


class ImportsPage(QWidget):
    resolveRequested = Signal(str, object, bool)
    cancelRequested = Signal()
    invalidateRequested = Signal()
    queueRequested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resolution: DownloadResolution | None = None
        self._loading = False
        self._resolving = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("Import Workshop content")
        title.setProperty("role", "h2")
        titles.addWidget(title)
        sub = QLabel(
            "Resolve links before anything downloads. Collections and dependencies appear here "
            "for review; nothing is queued until you choose Queue selected."
        )
        sub.setProperty("role", "muted")
        sub.setWordWrap(True)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        layout.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setMinimumWidth(300)
        left_scroll.setMaximumWidth(404)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(10)

        source_panel = QFrame()
        source_panel.setProperty("panel", True)
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(14, 12, 14, 12)
        source_layout.setSpacing(8)
        source_caption = QLabel("SOURCES")
        source_caption.setProperty("role", "caption")
        source_layout.addWidget(source_caption)
        self.source = QPlainTextEdit()
        self.source.setPlaceholderText(
            "Paste Workshop item or collection links, one per line. Item IDs also work.\n"
            "https://steamcommunity.com/sharedfiles/filedetails/?id=…"
        )
        self.source.setAccessibleName("Workshop links or item IDs")
        self.source.setMinimumHeight(90)
        self.source.setMaximumHeight(170)
        self.source.setFont(mono_font())
        source_layout.addWidget(self.source, 1)
        self.file_button = QPushButton("Import text file…")
        self.file_button.setIcon(icon("file", MUTED, 15))
        self.file_button.clicked.connect(self._import_file)
        source_layout.addWidget(self.file_button)
        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        hint_label = QLabel("Game ID hint")
        hint_label.setProperty("role", "muted")
        hint_row.addWidget(hint_label)
        self.hint = QLineEdit()
        self.hint.setPlaceholderText("Optional")
        self.hint.setAccessibleName("Game ID hint")
        hint_row.addWidget(self.hint, 1)
        source_layout.addLayout(hint_row)
        self.dependencies = QCheckBox("Include required items recursively")
        self.dependencies.setAccessibleName("Include required items recursively")
        source_layout.addWidget(self.dependencies)
        action_row = QHBoxLayout()
        action_row.setSpacing(7)
        self.resolve_button = QPushButton("Resolve list")
        self.resolve_button.setProperty("role", "primary")
        self.resolve_button.setIcon(icon("refresh", "#071219", 15))
        self.resolve_button.clicked.connect(self._emit_resolve)
        action_row.addWidget(self.resolve_button, 1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setProperty("role", "danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        action_row.addWidget(self.stop_button)
        source_layout.addLayout(action_row)
        self.notice = InlineNotice()
        source_layout.addWidget(self.notice)
        left_layout.addWidget(source_panel)

        self.issues_caption = QLabel("ISSUES")
        self.issues_caption.setProperty("role", "caption")
        left_layout.addWidget(self.issues_caption)
        self.issues = QPlainTextEdit()
        self.issues.setReadOnly(True)
        self.issues.setMaximumHeight(150)
        self.issues.setPlaceholderText("Invalid entries and unresolved dependencies appear here.")
        self.issues.setAccessibleName("Import issues")
        self.issues.setFont(mono_font())
        left_layout.addWidget(self.issues)
        self.issues_caption.setVisible(False)
        self.issues.setVisible(False)
        left_layout.addStretch(1)
        left_scroll.setWidget(left)
        body.addWidget(left_scroll, 0)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        preview_head = QHBoxLayout()
        preview_head.setSpacing(8)
        preview_caption = QLabel("PREVIEW")
        preview_caption.setProperty("role", "caption")
        preview_head.addWidget(preview_caption)
        self.summary = QLabel("Resolve the list to preview downloads.")
        self.summary.setProperty("role", "muted")
        self.summary.setWordWrap(True)
        preview_head.addWidget(self.summary, 1)
        self.include_all = QPushButton("Include all")
        self.include_all.setProperty("role", "link")
        self.include_all.clicked.connect(lambda: self._set_all(True))
        self.include_all.setEnabled(False)
        preview_head.addWidget(self.include_all)
        self.include_none = QPushButton("Exclude all")
        self.include_none.setProperty("role", "link")
        self.include_none.clicked.connect(lambda: self._set_all(False))
        self.include_none.setEnabled(False)
        preview_head.addWidget(self.include_none)
        right_layout.addLayout(preview_head)

        self.model = ImportTableModel(self)
        self.table = table_view(self.model)
        self.table.setAccessibleName("Import preview")
        self.table.setSelectionMode(QTableView.NoSelection)
        self.table.verticalHeader().setDefaultSectionSize(34)
        configure_import_columns(self.table)
        self.table.clicked.connect(self._toggle_row)
        self.model.dataChanged.connect(self._update_footer)
        self.empty_state = StatePanel()
        self.empty_state.set_state(
            "empty",
            "Nothing resolved yet",
            "Paste Workshop links or import a text file, then choose Resolve list. "
            "Valid mods and any problems will appear here.",
        )
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.empty_state)
        self.table_stack.addWidget(self.table)
        right_layout.addWidget(self.table_stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.footer_label = QLabel("0 of 0 included")
        self.footer_label.setProperty("role", "muted")
        footer.addWidget(self.footer_label)
        footer.addStretch(1)
        self.queue_button = QPushButton("Queue selected")
        self.queue_button.setProperty("role", "primary")
        self.queue_button.setIcon(icon("downloads", "#071219", 15))
        self.queue_button.setEnabled(False)
        self.queue_button.clicked.connect(self.queue_selected)
        footer.addWidget(self.queue_button)
        right_layout.addLayout(footer)
        body.addWidget(right, 1)
        layout.addLayout(body, 1)

        self.source.textChanged.connect(self._invalidate)
        self.hint.textChanged.connect(self._invalidate)
        self.dependencies.toggled.connect(self._invalidate)

    # ------------------------------------------------------------- input

    def source_text(self) -> str:
        return self.source.toPlainText()

    def hint_value(self) -> int | None:
        text = self.hint.text().strip()
        return int(text) if text.isdigit() and int(text) > 0 else None

    def dependencies_enabled(self) -> bool:
        return self.dependencies.isChecked()

    def prefill(
        self,
        references: str = "",
        *,
        appid_hint=None,
        dependencies: bool = False,
        auto_resolve: bool = False,
    ) -> None:
        self._loading = True
        self.source.setPlainText(references)
        self.hint.setText(str(appid_hint or ""))
        self.dependencies.setChecked(dependencies)
        self._loading = False
        self._invalidate(emit=False)
        self.summary.setText(
            "Ready to resolve this list." if references.strip() else "Resolve the list to preview downloads."
        )
        self.source.setFocus()
        if auto_resolve and references.strip():
            QTimer.singleShot(0, self._emit_resolve)

    def _import_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Import Workshop list", "", "Text files (*.txt);;All files (*)"
        )
        if not name:
            return
        try:
            text = Path(name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.notice.show_message("error", f"Could not read list: {exc}")
            return
        self.source.appendPlainText(text)
        self.notice.show_message("success", f"Loaded {Path(name).name}.")

    def _invalidate(self, *, emit: bool = True) -> None:
        if self._loading:
            return
        self.resolution = None
        self.model.set_resolution(None)
        self.notice.dismiss()
        self.empty_state.set_state(
            "empty",
            "List changed — resolve to preview",
            "The previous preview was cleared so nothing stale can be queued.",
        )
        self.table_stack.setCurrentWidget(self.empty_state)
        self.issues.clear()
        self.issues.setVisible(False)
        self.issues_caption.setVisible(False)
        self.queue_button.setEnabled(False)
        self.include_all.setEnabled(False)
        self.include_none.setEnabled(False)
        self.footer_label.setText("0 of 0 included")
        if self._resolving:
            self._set_resolving(False)
        self.summary.setText("List changed — resolve it to preview downloads.")
        if emit:
            self.invalidateRequested.emit()

    def _emit_resolve(self) -> None:
        if self._resolving:
            return
        text = self.source.toPlainText().strip()
        if not text:
            self.notice.show_message("warning", "Paste at least one Workshop link or item ID.")
            self.source.setFocus()
            return
        hint_text = self.hint.text().strip()
        if hint_text and (not hint_text.isdigit() or int(hint_text) <= 0):
            self.notice.show_message("warning", "Game ID hint must be a positive integer.")
            self.hint.setFocus()
            return
        self.notice.dismiss()
        self._set_resolving(True)
        self.resolveRequested.emit(text, int(hint_text) if hint_text else None, self.dependencies.isChecked())

    def _stop(self) -> None:
        self.cancelRequested.emit()
        self._set_resolving(False)
        self.empty_state.set_state(
            "empty",
            "Resolution stopped",
            "Nothing was queued. Edit the list or resolve it again when you are ready.",
            [("Resolve again", "primary", self._emit_resolve)],
        )
        self.table_stack.setCurrentWidget(self.empty_state)
        self.summary.setText("Resolution stopped. Nothing was queued.")
        self.queue_button.setEnabled(False)

    def _set_resolving(self, resolving: bool) -> None:
        self._resolving = resolving
        self.resolve_button.setEnabled(not resolving)
        self.stop_button.setEnabled(resolving)
        if resolving:
            self.empty_state.set_state(
                "loading",
                "Resolving Workshop content",
                "Fetching metadata, expanding collections and following required items. "
                "No files are downloaded during preview.",
            )
            self.table_stack.setCurrentWidget(self.empty_state)
            self.summary.setText("Resolving items, collections and dependencies…")
            self.queue_button.setEnabled(False)
            self.include_all.setEnabled(False)
            self.include_none.setEnabled(False)
            self.issues.clear()
            self.issues.setVisible(False)
            self.issues_caption.setVisible(False)

    # ----------------------------------------------------------- results

    def show_resolution(self, resolution: DownloadResolution) -> None:
        self._set_resolving(False)
        self.resolution = resolution
        self.model.set_resolution(resolution)
        if resolution.items:
            self.table_stack.setCurrentWidget(self.table)
            self.table.setFocus()
        else:
            self.empty_state.set_state(
                "no-results",
                "No downloadable items",
                "The list resolved without any usable mods. Read the issues below and adjust "
                "the links or supply a game ID hint.",
                [("Edit list", "primary", self.source.setFocus)],
            )
            self.table_stack.setCurrentWidget(self.empty_state)
        self.queue_button.setEnabled(bool(resolution.items))
        self.include_all.setEnabled(bool(resolution.items))
        self.include_none.setEnabled(bool(resolution.items))
        issues = [
            f"{issue.reference}: {issue.message}" for issue in resolution.issues
        ]
        self.issues.setPlainText("\n".join(issues))
        self.issues.setVisible(bool(issues))
        self.issues_caption.setVisible(bool(issues))
        self.summary.setText(
            f"{len(resolution.items)} mods · {resolution.collections} collections · "
            f"{resolution.duplicates} duplicate references · {len(resolution.issues)} issues. "
            "Uncheck anything you do not want."
        )
        if resolution.items:
            self.notice.show_message(
                "success" if not resolution.issues else "warning",
                f"Preview ready. {len(resolution.items)} mods resolved"
                + (f", {len(resolution.issues)} issue(s) need review." if resolution.issues else "."),
            )
        self._update_footer()

    def show_error(self, message: str) -> None:
        self._set_resolving(False)
        self.empty_state.set_state(
            "offline",
            "Could not resolve the list",
            message,
            [("Try again", "primary", self._emit_resolve), ("Edit list", "", self.source.setFocus)],
        )
        self.table_stack.setCurrentWidget(self.empty_state)
        self.summary.setText("Resolution failed. Nothing was queued.")
        self.queue_button.setEnabled(False)
        self.notice.show_message("error", message)

    def _set_all(self, checked: bool) -> None:
        self.model.set_all(checked)
        self._update_footer()

    def _toggle_row(self, index) -> None:
        if index.column() != 0 or not index.isValid():
            return
        current = index.data(Qt.CheckStateRole)
        self.model.setData(
            index,
            Qt.Unchecked if current == Qt.Checked else Qt.Checked,
            Qt.CheckStateRole,
        )

    def _update_footer(self) -> None:
        total = self.model.rowCount()
        included = self.model.included_count()
        self.footer_label.setText(f"{included} of {total} included")
        self.queue_button.setEnabled(bool(total and included))

    def queue_selected(self) -> None:
        chosen = self.model.selected_items()
        if not chosen:
            self.notice.show_message(
                "warning", "Select at least one mod to queue, or use Include all."
            )
            return
        self.queueRequested.emit(chosen)

    def mark_queued(self, count: int) -> None:
        self.notice.show_message(
            "success",
            f"{count} mod{'s' if count != 1 else ''} added to Downloads. "
            "The status strip tracks progress from here.",
        )

    # --------------------------------------------------------- lifecycle

    def focus_primary(self) -> None:
        self.source.setFocus()

    def preferred_items(self) -> list[WorkshopItem]:
        return self.model.selected_items() if self.resolution else []


__all__ = ["ImportsPage"]
