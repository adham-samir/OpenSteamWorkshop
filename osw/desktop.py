"""Per-user Linux desktop integration: application-menu entry and icon.

Everything lands under the XDG data directory, so no root is required and the
entry can be removed cleanly. The module is Qt-free so the CLI can use it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ID = "openworkshop"
LEGACY_APP_ID = "opensteamworkshop"
APP_NAME = "OpenWorkshop"
APP_COMMENT = "Browse and download Steam Workshop content without installing the game"


def desktop_supported() -> bool:
    return sys.platform.startswith("linux")


def _data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "share"
    )


def applications_dir() -> Path:
    return _data_home() / "applications"


def entry_path() -> Path:
    return applications_dir() / f"{APP_ID}.desktop"


def icon_path() -> Path:
    return (
        _data_home()
        / "icons"
        / "hicolor"
        / "scalable"
        / "apps"
        / f"{APP_ID}.svg"
    )


def entry_installed() -> bool:
    return entry_path().is_file() or (applications_dir() / f"{LEGACY_APP_ID}.desktop").is_file()


def _icon_source() -> Path:
    return Path(__file__).resolve().parent / "gui" / "icons" / "app.svg"


def _exec_quote(value: str) -> str:
    """Quote one Exec argument using the desktop-entry rules (not shell rules)."""
    if not any(char in value for char in ' \t"\'\\'):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def gui_command() -> str:
    """Command that launches the GUI of *this* installation.

    Sibling entry points win because PATH may point at a different install;
    the module invocation keeps venv and pipx installs working either way.
    """
    for name in ("openworkshop-gui", "osw-gui"):
        sibling = Path(sys.executable).with_name(name)
        if sibling.is_file():
            return _exec_quote(str(sibling))
    for name in ("openworkshop-gui", "osw-gui"):
        found = shutil.which(name)
        if found:
            return _exec_quote(found)
    return f"{_exec_quote(sys.executable or 'python3')} -m osw.gui.main_window"


def entry_text() -> str:
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            f"Name={APP_NAME}",
            "GenericName=Steam Workshop Mod Manager",
            f"Comment={APP_COMMENT}",
            f"Exec={gui_command()}",
            f"Icon={icon_path()}",
            "Terminal=false",
            "Categories=Game;Network;Utility;",
            "Keywords=steam;workshop;mods;download;",
            "StartupNotify=true",
            f"StartupWMClass={APP_NAME}",
            "",
        ]
    )


def _refresh_databases() -> None:
    for command in (
        ["update-desktop-database", str(applications_dir())],
        [
            "gtk-update-icon-cache",
            "-f",
            "-t",
            str(icon_path().parent.parent.parent),
        ],
    ):
        try:
            subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass  # optional helpers; the entry works without them


def install_desktop_entry() -> tuple[Path, Path]:
    """Install the launcher entry and icon for the current user."""
    if not desktop_supported():
        raise OSError("application-menu integration is only available on Linux")
    source = _icon_source()
    if not source.is_file():
        raise OSError(f"launcher icon is missing from the installation: {source}")

    icon = icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, icon)

    entry = entry_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(entry_text(), encoding="utf-8")
    for legacy in _legacy_paths():
        legacy.unlink(missing_ok=True)
    _refresh_databases()
    return entry, icon


def _legacy_paths() -> tuple[Path, Path]:
    return (
        applications_dir() / f"{LEGACY_APP_ID}.desktop",
        icon_path().with_name(f"{LEGACY_APP_ID}.svg"),
    )


def uninstall_desktop_entry() -> list[Path]:
    """Remove only the files this module owns; safe to call repeatedly."""
    if not desktop_supported():
        raise OSError("application-menu integration is only available on Linux")
    removed: list[Path] = []
    for path in (entry_path(), icon_path(), *_legacy_paths()):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path)
    if removed:
        _refresh_databases()
    return removed
