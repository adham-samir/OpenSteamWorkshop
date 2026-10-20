# OpenSteamWorkshop

Browse a game's Steam Workshop from a desktop app and download mods with
Valve's official **SteamCMD**.

## What it does

- **Find a game** by name (public store search) or paste an
  appid / workshop / store URL.
- **Browse Workshop content**: thumbnail grid with search, sorting
  (most popular / top rated / most recent), paging, subscriber counts,
  file sizes, tags and dependencies.
- **Download items** with SteamCMD into a per-game folder under your mods
  root (default `~/SteamMods`), with retries and a visible queue.
- CLI included (`osw`) for automation — same engine under the hood.

## Install

```bash
python -m venv --system-site-packages .venv   # recommended
source .venv/bin/activate       # bash / zsh
source .venv/bin/activate.fish  # fish
pip install -e .                # GUI + CLI
```

## Run

```bash
osw-gui        # desktop app (PySide6)
python main.py # same thing
```

CLI:

```bash
osw search project zomboid
osw browse 108600 --sort topsubscribed 2>/dev/null | head    # list mods
osw browse 108600 --search "maps"
osw info 3820938264
osw download 108600 3820938264 --out ~/SteamMods
osw url "https://steamcommunity.com/sharedfiles/filedetails/?id=..."
```

## Owning the game

SteamCMD's `workshop_download_item` has one access rule: an **anonymous**
login may download a limited set of apps; anything else needs a login of an
account that owns the app in question. The app supports both:
Settings → Steam account (or `osw download --username` for the CLI).
Passwords are only sent to Valve via SteamCMD locally and are never stored
unless you explicitly opt in.

## Troubleshooting

- **SteamCMD won't start on Linux** — missing 32-bit runtime:
  ```bash
  sudo apt install lib32gcc-s1        # Debian/Ubuntu
  sudo pacman -S lib32-gcc-libs       # Arch
  ```
- **"This account does not own app …"** — expected for games you don't own
  with the selected login. Anonymous works only for a few free apps.
- SteamCMD occasionally no-ops the first download attempt; the app retries
  automatically.
- **Some games have no Steam Workshop** (e.g. Cities: Skylines II publishes
  through Paradox Mods) — the app will tell you when a workshop hub
  doesn't exist for the game you picked.

## Legal / ethics note

Workshop items belong to their authors. This tool is for personal use within
Steam's terms; don't redistribute other people's content.

## License

MIT.
