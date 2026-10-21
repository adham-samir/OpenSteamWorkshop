"""Settings workspace: content folder, session-only account, SteamCMD folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from . import theme


class SettingsPage(QWidget):
    """Intent: save_requested(dict). The controller persists and applies."""

    save_requested = Signal(str, str, str, str, str, int)
    # content_root, username, use_account(bool→str), password, steamcmd_dir, parallel
    desktop_install_requested = Signal()
    desktop_uninstall_requested = Signal()

    def __init__(self):
        super().__init__()
        self._desktop_installed = False
        self._desktop_available = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 16)
        outer.setSpacing(14)
        title = QLabel("Settings")
        title.setProperty("role", "h1")
        outer.addWidget(title)
        self.subheader = QLabel("Choose where mods live and how downloads run.")
        self.subheader.setProperty("role", "muted")
        outer.addWidget(self.subheader)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 4, 16, 0)
        v.setSpacing(20)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        def section(title, description):
            box = QWidget()
            bv = QVBoxLayout(box)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(8)
            heading = QLabel(title)
            heading.setProperty("role", "h2")
            bv.addWidget(heading)
            note = QLabel(description)
            note.setWordWrap(True)
            note.setProperty("role", "muted")
            bv.addWidget(note)
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setSpacing(10)
            bv.addLayout(form)
            v.addWidget(box)
            return form

        storage = section("Storage", "The default mods folder is used unless a game has its own destination in Browse mods.")
        self.form = storage
        root_row = QHBoxLayout()
        root_row.setContentsMargins(0, 0, 0, 0)
        self.root_edit = QLineEdit()
        self.root_edit.setAccessibleName("Mods root folder")
        pick = QPushButton("Choose folder…")
        pick.clicked.connect(self._choose_root)
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(pick)
        holder = QWidget()
        holder.setLayout(root_row)
        storage.addRow("Default mods folder", holder)

        downloads = section("Downloads", "Different games can download together. Mods for the same game run one at a time.")
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 3)
        self.parallel_spin.setValue(3)
        self.parallel_spin.setAccessibleName("Concurrent downloads")
        downloads.addRow("Concurrent games", self.parallel_spin)
        self.steamcmd_edit = QLineEdit()
        self.steamcmd_edit.setPlaceholderText("Automatic — managed by OpenSteamWorkshop")
        self.steamcmd_edit.setAccessibleName("SteamCMD folder")
        downloads.addRow("SteamCMD folder", self.steamcmd_edit)

        account = section("Steam account", "Anonymous downloads are the default. Some Workshops require an account. Passwords and Steam Guard codes stay in memory for this session.")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Steam username")
        self.user_edit.setAccessibleName("Steam username")
        account.addRow("Username", self.user_edit)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Optional — prompted when needed, never saved")
        self.password_edit.setAccessibleName("Steam password")
        account.addRow("Password", self.password_edit)
        self.account_check = QCheckBox("Use this account for new downloads this session")
        self.account_checkbox = self.account_check
        account.addRow("", self.account_check)

        integration = section("Application integration", "Open the app from your desktop’s application menu.")
        self.desktop_status = QLabel("Not installed.")
        self.desktop_status.setWordWrap(True)
        self.desktop_status.setProperty("role", "muted")
        self.desktop_btn = QPushButton("Add to app menu")
        self.desktop_btn.setAccessibleName("Add OpenSteamWorkshop to the application menu")
        self.desktop_btn.clicked.connect(self._toggle_desktop)
        integration.addRow(self.desktop_status, self.desktop_btn)
        self.note = QLabel("Changes apply to new jobs. Running jobs keep their current settings.")
        self.note.setWordWrap(True)
        self.note.setProperty("role", "muted")
        v.addWidget(self.note)
        self.version_label = QLabel(f"OpenSteamWorkshop {__version__}")
        self.version_label.setProperty("role", "muted")
        self.version_label.setAccessibleName("Application version")
        v.addWidget(self.version_label)
        v.addStretch(1)
        footer = QHBoxLayout()
        self.saved_label = QLabel("")
        self.saved_label.setWordWrap(True)
        footer.addWidget(self.saved_label, 1)
        self.save_btn = QPushButton("Save settings")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.setAccessibleName("Save settings")
        self.save_button = self.save_btn
        footer.addWidget(self.save_btn)
        outer.addLayout(footer)

        self.save_btn.clicked.connect(self._emit_save)

    # ------------------------------------------------------------- api

    def load(
        self,
        content_root: str,
        username: str,
        use_account: bool,
        password: str,
        steamcmd_dir: str,
        parallel: int = 3,
    ) -> None:
        self.root_edit.setText(content_root)
        self.user_edit.setText(username)
        self.account_check.setChecked(use_account)
        self.password_edit.setText(password)
        self.steamcmd_edit.setText(steamcmd_dir)
        self.parallel_spin.setValue(max(1, min(3, int(parallel or 1))))
        self.saved_label.clear()

    def values(self) -> tuple[str, str, bool, str, str, int]:
        return (
            self.root_edit.text().strip(),
            self.user_edit.text().strip(),
            self.account_check.isChecked(),
            self.password_edit.text(),
            self.steamcmd_edit.text().strip(),
            self.parallel_spin.value(),
        )

    def _choose_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose mods root folder")
        if chosen:
            self.root_edit.setText(chosen)

    def set_desktop_available(self, available: bool) -> None:
        self._desktop_available = bool(available)
        self.desktop_btn.setVisible(self._desktop_available)
        self.set_desktop_installed(self._desktop_installed)

    def set_desktop_installed(self, installed: bool) -> None:
        self._desktop_installed = bool(installed)
        if not self._desktop_available:
            self.desktop_status.setText("Only available on Linux.")
            return
        if self._desktop_installed:
            self.desktop_status.setText(
                "Installed — search for OpenSteamWorkshop in your app menu."
            )
            self.desktop_btn.setText("Remove from app menu")
            self.desktop_btn.setAccessibleName(
                "Remove OpenSteamWorkshop from the application menu"
            )
        else:
            self.desktop_status.setText("Not in the application menu.")
            self.desktop_btn.setText("Add to app menu")
            self.desktop_btn.setAccessibleName(
                "Add OpenSteamWorkshop to the application menu"
            )

    def _toggle_desktop(self) -> None:
        if self._desktop_installed:
            self.desktop_uninstall_requested.emit()
        else:
            self.desktop_install_requested.emit()

    def _emit_save(self) -> None:
        content_root, username, use_account, password, steamcmd, parallel = self.values()
        if not content_root:
            self.show_error("Choose a default mods folder.")
            self.root_edit.setFocus()
            return
        if Path(content_root).expanduser().is_file():
            self.show_error("The mods folder points to a file. Choose a folder instead.")
            self.root_edit.setFocus()
            return
        if use_account and not username:
            self.show_error("Enter a Steam username to use an account.")
            self.user_edit.setFocus()
            return
        if steamcmd and Path(steamcmd).expanduser().is_file():
            self.show_error("Choose the folder containing SteamCMD, rather than the executable.")
            self.steamcmd_edit.setFocus()
            return
        self.save_requested.emit(
            content_root,
            username,
            "true" if use_account else "",
            password,
            steamcmd,
            parallel,
        )

    def confirm_saved(self, message: str = "Settings saved") -> None:
        self.saved_label.setStyleSheet(f"color: {theme.OK};")
        self.saved_label.setText(message)

    def show_error(self, message: str) -> None:
        self.saved_label.setStyleSheet(f"color: {theme.BAD}; font-size: 12.5px;")
        self.saved_label.setText(message)
