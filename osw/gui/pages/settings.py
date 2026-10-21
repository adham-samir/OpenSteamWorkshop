"""Settings workspace: storage, session account and SteamCMD configuration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..components import InlineNotice
from ..theme import MUTED, icon


class SettingsPage(QWidget):
    saveRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(12)
        scroll.setWidget(content)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        sub = QLabel(
            "Storage, an optional session account, and SteamCMD. "
            "Changes apply to new jobs; queued jobs keep the settings they were created with."
        )
        sub.setProperty("role", "muted")
        sub.setWordWrap(True)
        titles.addWidget(sub)
        layout.addLayout(titles)

        layout.addWidget(
            self._section(
                "Storage",
                "Workshop downloads are written to "
                "<root>/steamapps/workshop/content/<appid>/<itemid>/.",
                [
                    self._field(
                        "Mods root folder",
                        self._make_root_row(),
                        "Select the folder that will hold every game's downloaded mods.",
                    ),
                    self._hint_label(
                        "The queue is saved separately and restored as interrupted work."
                    ),
                    self._mono_row("Queue file", self._queue_label()),
                ],
            )
        )

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("(empty = anonymous downloads only)")
        self.user_edit.setAccessibleName("Steam username")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Optional; prompted when needed. Never saved.")
        self.password_edit.setAccessibleName("Steam password")
        self.account_checkbox = QCheckBox("Use this account for new downloads this session")
        self.account_checkbox.setAccessibleName("Use this account for new downloads this session")
        self.account_state = QLabel()
        self.account_state.setWordWrap(True)
        self.account_state.setProperty("role", "muted")
        self.user_edit.textChanged.connect(self._refresh_account_state)
        self.account_checkbox.toggled.connect(self._refresh_account_state)

        account_body = QVBoxLayout()
        account_body.setSpacing(8)
        account_body.addWidget(self.user_edit)
        account_body.addWidget(self.account_checkbox)
        account_body.addWidget(self.password_edit)
        account_body.addWidget(self.account_state)
        account_wrap = QWidget()
        account_wrap.setLayout(account_body)
        layout.addWidget(
            self._section(
                "Account",
                "Anonymous is the default. Some Workshop items require an account with access; "
                "you can also retry individual failures from Downloads.",
                [account_wrap],
            )
        )

        self.steamcmd_edit = QLineEdit()
        self.steamcmd_edit.setPlaceholderText("Empty = automatically managed SteamCMD")
        self.steamcmd_edit.setAccessibleName("SteamCMD folder")
        layout.addWidget(
            self._section(
                "SteamCMD",
                "Valve's official downloader. It is fetched on first use when this is empty. "
                "Only one SteamCMD job runs at a time to avoid workspace and login conflicts.",
                [
                    self._field(
                        "SteamCMD folder",
                        self._make_steamcmd_row(),
                        "Leave empty to let OpenSteamWorkshop manage SteamCMD.",
                    ),
                ],
            )
        )

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.notice = InlineNotice()
        footer.addWidget(self.notice, 1)
        self.save_button = QPushButton("Save settings")
        self.save_button.setProperty("role", "primary")
        self.save_button.setIcon(icon("check", "#071219", 15))
        self.save_button.setAccessibleName("Save settings")
        self.save_button.clicked.connect(lambda: self.saveRequested.emit(self.values()))
        footer.addWidget(self.save_button, 0, Qt.AlignRight)
        layout.addLayout(footer)
        note = QLabel(
            "Passwords and Steam Guard codes are kept in memory for this session only. "
            "They are never written to settings, the queue, or process arguments."
        )
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    # ----------------------------------------------------------- building

    def _section(self, title: str, body: str, rows: list[QWidget]) -> QFrame:
        panel = QFrame()
        panel.setProperty("panel", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        heading = QLabel(title)
        heading.setProperty("role", "h3")
        layout.addWidget(heading)
        description = QLabel(body)
        description.setProperty("role", "muted")
        description.setWordWrap(True)
        layout.addWidget(description)
        for row in rows:
            layout.addWidget(row)
        return panel

    def _field(self, label: str, field: QWidget, hint: str = "") -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        caption = QLabel(label)
        caption.setProperty("role", "caption")
        layout.addWidget(caption)
        layout.addWidget(field)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "muted")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)
        return wrapper

    def _hint_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "muted")
        label.setWordWrap(True)
        return label

    def _make_root_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.root_edit = QLineEdit()
        self.root_edit.setAccessibleName("Mods root folder")
        self.root_edit.textChanged.connect(self._refresh_root_hint)
        layout.addWidget(self.root_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_root)
        browse.setAccessibleName("Browse for mods root folder")
        layout.addWidget(browse)
        return row

    def _make_steamcmd_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(self.steamcmd_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_steamcmd)
        browse.setAccessibleName("Browse for SteamCMD folder")
        layout.addWidget(browse)
        return row

    def _mono_row(self, label: str, value: QLabel) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        caption = QLabel(label)
        caption.setProperty("role", "caption")
        caption.setMinimumWidth(80)
        layout.addWidget(caption)
        layout.addWidget(value, 1)
        return row

    def _queue_label(self) -> QLabel:
        self.queue_label = QLabel("—")
        self.queue_label.setProperty("role", "muted")
        self.queue_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.queue_label.setWordWrap(True)
        self.queue_label.setStyleSheet(f"font-family:monospace; color:{MUTED};")
        return self.queue_label

    # ------------------------------------------------------------- values

    def values(self) -> dict:
        return {
            "content_root": self.root_edit.text().strip(),
            "username": self.user_edit.text().strip(),
            "steamcmd_dir": self.steamcmd_edit.text().strip(),
            "use_account": self.account_checkbox.isChecked(),
            "password": self.password_edit.text(),
        }

    def set_values(
        self,
        *,
        content_root: str,
        username: str = "",
        steamcmd_dir: str = "",
        use_account: bool = False,
        password: str = "",
        queue_path: str = "",
    ) -> None:
        self.root_edit.setText(content_root)
        self.user_edit.setText(username)
        self.steamcmd_edit.setText(steamcmd_dir)
        self.account_checkbox.setChecked(use_account)
        self.password_edit.setText(password)
        self.queue_label.setText(queue_path or "—")
        self._refresh_root_hint()
        self._refresh_account_state()
        self.notice.dismiss()

    def set_notice(self, kind: str, message: str) -> None:
        self.notice.show_message(kind, message)

    def focus_primary(self) -> None:
        self.root_edit.setFocus()
        self.root_edit.selectAll()

    def _refresh_root_hint(self) -> None:
        root = self.root_edit.text().strip()
        if not root:
            return
        try:
            resolved = Path(root).expanduser()
        except (OSError, ValueError):
            return
        sample = resolved / "steamapps" / "workshop" / "content" / "<appid>" / "<itemid>"
        self.root_edit.setToolTip(f"Downloads go to {sample}")

    def _refresh_account_state(self) -> None:
        if self.account_checkbox.isChecked() and self.user_edit.text().strip():
            self.account_state.setText(
                f"New downloads this session use {self.user_edit.text().strip()!r}. "
                "Steam may still prompt for a password or Guard code."
            )
            self.account_state.setProperty("role", "good")
        else:
            self.account_state.setText(
                "New downloads use anonymous access. Restored jobs always start anonymous."
            )
            self.account_state.setProperty("role", "muted")
        self.account_state.style().unpolish(self.account_state)
        self.account_state.style().polish(self.account_state)
        self.password_edit.setEnabled(self.account_checkbox.isChecked())

    def _browse_root(self) -> None:
        current = self.root_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose mods root folder", current)
        if chosen:
            self.root_edit.setText(chosen)

    def _browse_steamcmd(self) -> None:
        current = self.steamcmd_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose SteamCMD folder", current)
        if chosen:
            self.steamcmd_edit.setText(chosen)


__all__ = ["SettingsPage"]
