"""Linux application-menu integration (XDG entry + icon)."""

import sys

import pytest

from osw import desktop
from osw.cli import main

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="application-menu integration is Linux-only",
)


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    home = tmp_path / "share"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setattr(desktop, "_refresh_databases", lambda: None)
    return home


def test_install_writes_entry_and_icon(data_home):
    entry, icon = desktop.install_desktop_entry()

    assert entry == data_home / "applications" / "openworkshop.desktop"
    assert icon == (
        data_home / "icons" / "hicolor" / "scalable" / "apps" / "openworkshop.svg"
    )
    assert entry.is_file()
    assert icon.is_file()
    assert icon.read_text(encoding="utf-8").startswith("<svg")

    text = entry.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in text
    assert "Name=OpenWorkshop" in text
    assert "Exec=" in text
    assert "openworkshop-gui" in text or "osw-gui" in text or "-m osw.gui.main_window" in text
    assert f"Icon={icon}" in text
    assert "Terminal=false" in text
    assert "StartupWMClass=OpenWorkshop" in text
    assert desktop.entry_installed()


def test_install_is_idempotent_and_uninstall_removes_only_owned_files(data_home):
    stray = data_home / "applications" / "other.desktop"
    stray.parent.mkdir(parents=True)
    stray.write_text("keep me", encoding="utf-8")

    desktop.install_desktop_entry()
    desktop.install_desktop_entry()
    removed = desktop.uninstall_desktop_entry()

    assert set(removed) == {desktop.entry_path(), desktop.icon_path()}
    assert not desktop.entry_installed()
    assert not desktop.icon_path().exists()
    assert stray.exists()
    assert desktop.uninstall_desktop_entry() == []


def test_exec_quoting():
    assert desktop._exec_quote("/usr/bin/python3") == "/usr/bin/python3"
    assert desktop._exec_quote("/opt/my apps/python") == '"/opt/my apps/python"'
    assert desktop._exec_quote('/opt/a"b') == '"/opt/a\\"b"'


def test_gui_command_falls_back_to_module(monkeypatch, tmp_path):
    fake = tmp_path / "python3"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(desktop.sys, "executable", str(fake))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)

    assert desktop.gui_command() == f"{fake} -m osw.gui.main_window"


def test_install_replaces_legacy_launcher_and_preserves_other_entries(data_home):
    legacy_entry, legacy_icon = desktop._legacy_paths()
    legacy_entry.parent.mkdir(parents=True)
    legacy_icon.parent.mkdir(parents=True)
    legacy_entry.write_text("Name=OpenSteamWorkshop", encoding="utf-8")
    legacy_icon.write_text("old icon", encoding="utf-8")
    other = legacy_entry.with_name("other.desktop")
    other.write_text("keep me", encoding="utf-8")

    assert desktop.entry_installed()
    desktop.install_desktop_entry()

    assert not legacy_entry.exists()
    assert not legacy_icon.exists()
    assert other.read_text(encoding="utf-8") == "keep me"
    assert desktop.entry_path().is_file()


def test_uninstall_removes_legacy_only_installation(data_home):
    legacy_entry, legacy_icon = desktop._legacy_paths()
    for path in (legacy_entry, legacy_icon):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("legacy", encoding="utf-8")

    assert desktop.entry_installed()
    assert set(desktop.uninstall_desktop_entry()) == {legacy_entry, legacy_icon}
    assert not desktop.entry_installed()


@pytest.mark.parametrize("commands, chosen", [
    (("openworkshop-gui", "osw-gui"), "openworkshop-gui"),
    (("osw-gui",), "osw-gui"),
])
def test_gui_command_prefers_own_installation(monkeypatch, tmp_path, commands, chosen):
    fake = tmp_path / "python3"
    fake.touch()
    for command in commands:
        (tmp_path / command).touch()
    monkeypatch.setattr(desktop.sys, "executable", str(fake))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/other/bin/{name}")

    assert desktop.gui_command() == str(tmp_path / chosen)


def test_cli_desktop_install_print_does_not_write(data_home, capsys):
    assert main(["desktop-install", "--print"]) == 0

    output = capsys.readouterr().out
    assert "Exec=" in output
    assert "Icon=" in output
    assert not desktop.entry_installed()


def test_cli_desktop_install_and_uninstall(data_home, capsys):
    assert main(["desktop-install"]) == 0
    assert desktop.entry_installed()
    assert "application-menu entry" in capsys.readouterr().out.lower()

    assert main(["desktop-uninstall"]) == 0
    assert not desktop.entry_installed()
    assert "removed the application-menu entry" in capsys.readouterr().out.lower()
