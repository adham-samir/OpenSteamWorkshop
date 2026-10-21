"""Shared Transfer Desk widgets that are not page-specific."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, AMBER, GREEN, MUTED, RED, icon

__all__ = ["StatePanel", "fit_wrap"]


def fit_wrap(label: QLabel, width: int) -> None:
    """Pin a word-wrapped label to ``width`` and reserve its real text height.

    Qt's box layouts can collapse centred word-wrapped labels to a single line;
    this makes their minimum height match the wrapped text.
    """
    label.setFixedWidth(width)
    label.ensurePolished()
    label.setMinimumHeight(max(label.fontMetrics().lineSpacing(), label.heightForWidth(width)))


class StatePanel(QWidget):
    """A visible loading / empty / no-results / error / permission state."""

    ICONS = {
        "loading": ("clock", ACCENT),
        "empty": ("folder", MUTED),
        "no-results": ("search", MUTED),
        "error": ("alert", RED),
        "offline": ("alert", RED),
        "permission": ("shield", AMBER),
        "success": ("check", GREEN),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(8)
        layout.addStretch(1)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setProperty("role", "h2")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.body_label = QLabel()
        self.body_label.setAlignment(Qt.AlignCenter)
        self.body_label.setProperty("role", "muted")
        self.body_label.setWordWrap(True)
        self.body_label.setMaximumWidth(540)
        layout.addWidget(self.body_label, 0, Qt.AlignHCenter)
        self.actions = QWidget()
        self.action_layout = QHBoxLayout(self.actions)
        self.action_layout.setContentsMargins(0, 8, 0, 0)
        self.action_layout.setSpacing(8)
        self.action_layout.addStretch(1)
        layout.addWidget(self.actions, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self.kind = "empty"

    def set_state(self, kind: str, title: str, body: str = "", actions=None) -> None:
        self.kind = kind
        icon_name, colour = self.ICONS.get(kind, ("info", MUTED))
        self.icon_label.setPixmap(icon(icon_name, colour, 34).pixmap(34, 34))
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.body_label.setVisible(bool(body))
        fit_wrap(self.title_label, 540)
        fit_wrap(self.body_label, 540)
        while self.action_layout.count() > 1:
            item = self.action_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for label, role, callback in actions or []:
            button = QPushButton(label)
            if role:
                button.setProperty("role", role)
            button.clicked.connect(callback)
            self.action_layout.insertWidget(self.action_layout.count() - 1, button)
        self.setAccessibleName(f"{title}. {body}".strip())
