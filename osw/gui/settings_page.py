"""Settings workspace: content folder, session-only account, SteamCMD folder."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 12)
        v.setSpacing(10)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 19px; font-weight: 650;")
        self.subheader = QLabel(
            "Applies to new download jobs; running jobs keep their settings. "
            "Per-game mods folders are set from Browse."
        )
        self.subheader.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12.5px;")
        v.addWidget(title)
        v.addWidget(self.subheader)

        form_wrap = QWidget()
        self.form = QFormLayout(form_wrap)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.form.setContentsMargins(0, 6, 0, 0)
        self.form.setSpacing(10)

        root_row = QHBoxLayout()
        self.root_edit = QLineEdit()
        self.root_edit.setAccessibleName("Mods root folder")
        pick = QPushButton("…")
        pick.setFixedWidth(34)
        pick.setAccessibleName("Choose mods root folder")
        pick.clicked.connect(self._choose_root)
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(pick)
        holder = QFrame()
        holder.setLayout(root_row)
        self.form.addRow("Mods root folder (default)", holder)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("(empty = anonymous downloads only)")
        self.user_edit.setAccessibleName("Steam username")
        self.form.addRow("Steam username", self.user_edit)

        self.account_check = QCheckBox("Use this account for new downloads this session")
        self.account_checkbox = self.account_check
        self.form.addRow("", self.account_check)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Optional; prompted when needed. Never saved.")
        self.password_edit.setAccessibleName("Steam password")
        self.form.addRow("Steam password", self.password_edit)

        self.steamcmd_edit = QLineEdit()
        self.steamcmd_edit.setPlaceholderText("Empty = automatically managed SteamCMD")
        self.steamcmd_edit.setAccessibleName("SteamCMD folder")
        self.form.addRow("SteamCMD folder", self.steamcmd_edit)

        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 3)
        self.parallel_spin.setValue(1)
        self.parallel_spin.setAccessibleName("Parallel SteamCMD downloads")
        self.parallel_spin.setToolTip(
            "Download different games at the same time. Items from the same "
            "game still run one at a time. Extra workers use their own "
            "SteamCMD workspace."
        )
        self.form.addRow("Parallel downloads", self.parallel_spin)

        menu_row = QHBoxLayout()
        menu_row.setSpacing(8)
        self.desktop_status = QLabel("Not installed.")
        self.desktop_status.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        self.desktop_status.setWordWrap(True)
        self.desktop_btn = QPushButton("Add to app menu")
        self.desktop_btn.setAccessibleName(
            "Add OpenSteamWorkshop to the application menu"
        )
        self.desktop_btn.clicked.connect(self._toggle_desktop)
        menu_row.addWidget(self.desktop_status, 1)
        menu_row.addWidget(self.desktop_btn)
        menu_holder = QFrame()
        menu_holder.setLayout(menu_row)
        self.form.addRow("Application menu", menu_holder)

        v.addWidget(form_wrap)

        self.note = QLabel(
            "Anonymous is the default; access depends on each game's Workshop settings.\n"
            "Passwords and Steam Guard codes stay in memory for this session only.\n"
            "Parallel downloads run different games at once; same-game items stay serialized."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
        v.addWidget(self.note)

        self.saved_label = QLabel("")
        self.saved_label.setStyleSheet(f"color: {theme.OK}; font-size: 12.5px;")
        v.addWidget(self.saved_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("accent", True)
        self.save_btn.setAccessibleName("Save settings")
        self.save_button = self.save_btn
        buttons.addWidget(self.save_btn)
        v.addLayout(buttons)
        v.addStretch(1)

        self.version_label = QLabel(f"OpenSteamWorkshop {__version__}")
        self.version_label.setAccessibleName("Application version")
        self.version_label.setStyleSheet(f"color: {theme.TEXT2}; font-size: 11.5px;")
        v.addWidget(self.version_label)

        self.save_btn.clicked.connect(self._emit_save)

    # ------------------------------------------------------------- api

    def load(
        self,
        content_root: str,
        username: str,
        use_account: bool,
        password: str,
        steamcmd_dir: str,
        parallel: int = 1,
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
        self.save_requested.emit(
            content_root,
            username,
            "true" if use_account else "",
            password,
            steamcmd,
            parallel,
        )

    def confirm_saved(self, message: str = "Settings saved") -> None:
        self.saved_label.setText(message)

    def show_error(self, message: str) -> None:
        self.saved_label.setStyleSheet(f"color: {theme.BAD}; font-size: 12.5px;")
        self.saved_label.setText(message)
