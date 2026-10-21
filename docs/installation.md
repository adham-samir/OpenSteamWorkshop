# Installation

[← OpenWorkshop](../README.md)

OpenWorkshop requires **Python 3.10 or newer** and supports Linux and Windows.

## Linux

### One-line installer

```bash
curl -fsSL https://raw.githubusercontent.com/adham-samir/openworkshop/main/install.sh | bash
openworkshop-gui
```

The installer downloads the latest GitHub release, creates a private Python
environment, and adds the application-menu entry. It does not need `sudo`.

| What | Where |
| --- | --- |
| Application environment | `~/.local/share/opensteamworkshop/venv/` |
| Commands and compatibility aliases | `~/.local/bin/` |
| Launcher | Your desktop's application menu |

The installation directory retains its original name for upgrade compatibility.
If `~/.local/bin` is not on `PATH`, use `~/.local/bin/openworkshop-gui` or add that
folder to your shell's `PATH`.

Re-run the installer to update. Select an older release with `OSW_VERSION`, for
example `OSW_VERSION=0.6.1 bash install.sh` from a checkout. The installer supports
both `openworkshop-*.whl` and earlier `opensteamworkshop-*.whl` release assets.
Earlier releases still appear as **OpenSteamWorkshop**; the installer provides
the new command names for those releases too.

To uninstall an installation made by this script:

```bash
curl -fsSL https://raw.githubusercontent.com/adham-samir/openworkshop/main/uninstall.sh | bash
```

Settings, the queue, and downloaded mods are preserved.

### pipx

To get the renamed app directly from the repository (requires Git):

```bash
pipx install 'git+https://github.com/adham-samir/openworkshop.git'
openworkshop-gui
openworkshop desktop-install   # optional application-menu entry
```

You can instead download a wheel from [Releases](https://github.com/adham-samir/openworkshop/releases)
and run `pipx install /path/to/the-downloaded-wheel.whl`. Wheels named
`opensteamworkshop-*` use the old `osw` / `osw-gui` commands when installed directly.

The `openworkshop` PyPI distribution has not been published yet; use Git or a
release asset until it is available.

## Windows

1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/windows/)
   and enable **Add python.exe to PATH**.
2. Open the [latest release](https://github.com/adham-samir/openworkshop/releases/latest)
   and download its `.whl` file.
3. Install the downloaded file in PowerShell. Replace the example path with its
   actual filename:

```powershell
py -m pip install "$HOME\Downloads\openworkshop-<version>-py3-none-any.whl"
openworkshop-gui
```

For an older `opensteamworkshop-*.whl`, use that exact filename in the install
command and launch with `osw-gui`. To use the renamed app before its first release,
follow [From source](#from-source).

If the command is not found, run:

```powershell
py -m osw.gui.main_window
```

Dependencies, including PySide6, are installed automatically. Application-menu
integration is Linux-only. On Windows, locate the scripts folder with
`py -c "import sysconfig; print(sysconfig.get_path('scripts'))"`, then create a
shortcut to `openworkshop-gui.exe` (or `osw-gui.exe` for older wheels).

Install a newer wheel with `py -m pip install --upgrade <path-to-wheel>`.
Remove the renamed distribution with `py -m pip uninstall openworkshop`.
Settings, the queue, and mods remain on disk.

## From source

```bash
git clone https://github.com/adham-samir/openworkshop.git
cd openworkshop
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
openworkshop-gui
```

On Windows, use `py -m venv .venv` and `.venv\Scripts\Activate.ps1` instead of
the `python3` and `source` lines. Other commands are the same.

## Upgrading from OpenSteamWorkshop

The new distribution is `openworkshop`, and the primary commands are
`openworkshop` and `openworkshop-gui`. The `osw` and `osw-gui` aliases are included.
The internal Python module remains `osw`.

For a manual pip upgrade in the **same environment**, remove the old distribution
before installing the new one because they share Python module files:

```bash
python -m pip uninstall opensteamworkshop
python -m pip install /path/to/openworkshop-<version>-py3-none-any.whl
```

For pipx, uninstall the old app and then install the new one. The Linux installer
handles this transition automatically. Installations made from source can
uninstall the old distribution and run `python -m pip install -e .` again.

Existing settings and queue files continue to use `~/.config/OpenSteamWorkshop/`
(on Windows, `C:\Users\<you>\.config\OpenSteamWorkshop\`). SteamCMD storage and
mod delivery markers also keep their original names. No data migration is needed.
To refresh a Linux launcher after a manual upgrade, run
`openworkshop desktop-install`; this replaces the old launcher and icon.
