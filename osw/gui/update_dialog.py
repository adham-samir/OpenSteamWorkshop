"""Review dialog for batch-updating outdated Workshop items."""

from __future__ import annotations

from PySide6.QtCore import Qt
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


class UpdateAllDialog(QDialog):
    """Pre-checked list of available updates with per-item opt-out.

    The caller passes ``(InstalledItem, UpdateInfo)`` pairs that are already
    known to be outdated; this dialog never invents or filters statuses.
    """

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        entries = sorted(
            entries,
            key=lambda entry: (
                entry[0].game_label.casefold(),
                entry[0].label.casefold(),
            ),
        )
        self._rows: list[tuple[object, object, QCheckBox]] = []

        self.setWindowTitle("Update installed mods")
        self.setAccessibleName("Review available Workshop mod updates")
        self.resize(720, min(240 + 64 * len(entries), 580))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        noun = "mod" if len(entries) == 1 else "mods"
        title = QLabel(f"Update {len(entries)} installed {noun}")
        title.setStyleSheet("font-size: 17px; font-weight: 650;")
        layout.addWidget(title)
        subtitle = QLabel(
            "Untick anything you want to keep at its installed revision."
        )
        subtitle.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        rows = QVBoxLayout(container)
        rows.setContentsMargins(0, 4, 6, 4)
        rows.setSpacing(0)
        for position, (item, update) in enumerate(entries):
            rows.addWidget(self._make_row(item, update))
            if position < len(entries) - 1:
                rule = QFrame()
                rule.setFrameShape(QFrame.Shape.HLine)
                rule.setStyleSheet(
                    f"background: {theme.BORDER}; max-height: 1px; border: none;"
                )
                rows.addWidget(rule)
        rows.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        note = QLabel(
            "Each update re-downloads the mod and overwrites its installed files."
        )
        note.setStyleSheet(f"color: {theme.WARN}; font-size: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        footer = QHBoxLayout()
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        footer.addWidget(self.selection_label, 1)

        self.buttons = QDialogButtonBox()
        cancel = self.buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        cancel.clicked.connect(self.reject)
        self.update_btn = self.buttons.addButton(
            "Update", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.update_btn.setProperty("role", "primary")
        self.update_btn.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)

        self._sync()

    def _make_row(self, item, update) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(2, 9, 2, 9)
        box.setSpacing(10)

        check = QCheckBox()
        check.setChecked(True)
        check.setAccessibleName(f"Update {item.label}")
        check.toggled.connect(self._sync)
        box.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(item.label)
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        text.addWidget(title)

        size = fmt_size(item.size) or "unknown size"
        meta = QLabel(f"{item.game_label} · {item.location_label} · {size}")
        meta.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11.5px;")
        meta.setWordWrap(True)
        text.addWidget(meta)

        revision = QLabel(
            f"Installed {update.installed_label} → latest {update.online_label}"
        )
        revision.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11.5px;")
        revision.setWordWrap(True)
        text.addWidget(revision)
        box.addLayout(text, 1)

        self._rows.append((item, update, check))
        return row

    def selected_items(self) -> list:
        return [item for item, _update, check in self._rows if check.isChecked()]

    def _sync(self) -> None:
        checked = [item for item, _update, check in self._rows if check.isChecked()]
        total = fmt_size(sum(item.size for item in checked)) or "unknown size"
        self.selection_label.setText(
            f"{len(checked)} of {len(self._rows)} selected · {total}"
        )
        self.update_btn.setText(f"Update {len(checked)} of {len(self._rows)}")
        self.update_btn.setEnabled(bool(checked))
