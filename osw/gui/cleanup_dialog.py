"""Review dialog for duplicate installed copies (Library → Cleanup)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import fmt_size
from . import theme


class CleanupDialog(QDialog):
    """Tick the duplicate copies to delete; at least one copy stays behind.

    The safe recommendation is pre-selected: when a delivered copy exists, the
    leftover copy in the default mods root is redundant. Two delivered copies
    start unticked, so the user chooses which one goes.
    """

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        groups = sorted(
            groups,
            key=lambda group: (group.game_label.casefold(), group.label.casefold()),
        )
        self._rows: list[tuple[object, list[tuple[object, QCheckBox]]]] = []

        self.setWindowTitle("Clean up duplicate installs")
        self.setAccessibleName("Review duplicate installed Workshop copies")
        self.resize(760, min(260 + 110 * len(groups), 640))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        noun = "item" if len(groups) == 1 else "items"
        title = QLabel(f"{len(groups)} duplicate installed {noun}")
        title.setStyleSheet("font-size: 17px; font-weight: 650;")
        layout.addWidget(title)
        subtitle = QLabel(
            "These Workshop items exist in more than one managed location. "
            "Tick the copies to remove; every item keeps at least one copy."
        )
        subtitle.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        rows = QVBoxLayout(container)
        rows.setContentsMargins(0, 4, 6, 4)
        rows.setSpacing(0)
        for position, group in enumerate(groups):
            rows.addWidget(self._make_row(group))
            if position < len(groups) - 1:
                rule = QFrame()
                rule.setFrameShape(QFrame.Shape.HLine)
                rule.setStyleSheet(
                    f"background: {theme.BORDER}; max-height: 1px; border: none;"
                )
                rows.addWidget(rule)
        rows.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        self.warning = QLabel("")
        self.warning.setStyleSheet(f"color: {theme.WARN}; font-size: 12px;")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

        footer = QHBoxLayout()
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        footer.addWidget(self.selection_label, 1)

        self.buttons = QDialogButtonBox()
        cancel = self.buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        cancel.clicked.connect(self.reject)
        self.delete_btn = self.buttons.addButton(
            "Delete selected", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.delete_btn.setProperty("role", "danger")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)

        self._sync()

    def _make_row(self, group) -> QWidget:
        row = QWidget()
        box = QVBoxLayout(row)
        box.setContentsMargins(2, 9, 2, 9)
        box.setSpacing(4)

        title = QLabel(group.label)
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        box.addWidget(title)

        meta = QLabel(
            f"{group.game_label} · Workshop ID {group.fileid} · "
            f"{len(group.copies)} copies"
        )
        meta.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11.5px;")
        meta.setWordWrap(True)
        box.addWidget(meta)

        note = (
            "The delivered copy is in use; the default-root copy is redundant."
            if group.redundant is not None
            else "Two delivered copies exist — choose which one to remove."
        )
        hint = QLabel(note)
        hint.setStyleSheet(
            f"color: {theme.WARN if group.redundant is None else theme.TEXT2}; "
            "font-size: 11.5px;"
        )
        hint.setWordWrap(True)
        box.addWidget(hint)

        choices: list[tuple[object, QCheckBox]] = []
        for copy in group.copies:
            check = QCheckBox()
            check.setChecked(copy is group.redundant)
            check.toggled.connect(self._sync)
            kind = "delivered" if copy.delivered else "default"
            check.setAccessibleName(f"Delete {kind} copy of {group.label}")
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            line.addWidget(check, 0)
            text = QVBoxLayout()
            text.setSpacing(1)
            label = QLabel(
                "Delete delivered copy" if copy.delivered else "Delete default copy"
            )
            label.setStyleSheet("font-size: 12px;")
            text.addWidget(label)
            detail = QLabel(f"{copy.path} · {fmt_size(copy.size) or 'unknown size'}")
            detail.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11px;")
            detail.setWordWrap(True)
            text.addWidget(detail)
            line.addLayout(text, 1)
            box.addLayout(line)
            choices.append((copy, check))

        self._rows.append((group, choices))
        return row

    def selected_copies(self) -> list:
        """Copies the user marked for deletion, excluding all-copy groups."""
        selected = []
        for _group, choices in self._rows:
            picked = [copy for copy, check in choices if check.isChecked()]
            if picked and len(picked) < len(choices):
                selected.extend(picked)
        return selected

    def _sync(self) -> None:
        selected = self.selected_copies()
        blocked = any(
            all(check.isChecked() for _copy, check in choices)
            for _group, choices in self._rows
        )
        total = fmt_size(sum(copy.size for copy in selected)) or "unknown size"
        noun = "copy" if len(selected) == 1 else "copies"
        self.selection_label.setText(f"{len(selected)} {noun} selected · {total}")
        self.warning.setText(
            "Keep at least one copy of every item before deleting."
            if blocked
            else ""
        )
        self.warning.setVisible(blocked)
        self.delete_btn.setText(f"Delete {len(selected)}")
        self.delete_btn.setEnabled(bool(selected) and not blocked)
