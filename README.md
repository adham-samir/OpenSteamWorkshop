# OpenSteamWorkshop

Browse a game's Steam Workshop from a desktop app and download mods with
Valve's official **SteamCMD**, without installing the game.
Anonymous downloads also work without owning the game when its publisher permits them.

## What it does

- **Find a game** by name (public store search) or paste an
  appid / workshop / store URL.
- **Browse Workshop content**: thumbnail grid with search, sorting
  (most popular / top rated / most recent), paging, subscriber counts,
  file sizes, tags and dependencies.
- **Download items** with SteamCMD into your mods root (default `~/SteamMods`), or
  opt in to a **per-game mods folder** so finished items are moved into
  `<chosen folder>/<Item title>/` (e.g. `RimWorld/Mods/Wiremod/`), with retries
  and a visible queue.
- CLI included (`osw`) for automation — same engine under the hood.
- **Bulk imports**: use the **Imports** workspace to paste item/collection URLs
  or load a text file, preview the resolved mods, optionally include recursive
  dependencies, and exclude items before queueing.
- **Recoverable queue**: cancel running jobs, retry failures, open their folders
  and logs, and resume unfinished jobs after restarting the app.
- **Skips what is already installed**: if a mod is already on disk, the app asks
  before re-downloading it; the Imports preview flags installed rows and leaves
  them unchecked unless you re-check them. `osw` skips installed items and
  prints where they live unless you pass `--reinstall`.
- **Installed library**: the Library workspace scans your default mods root and
  any per-game mods folders for content already downloaded. See each item's game,
  location (default or delivered), size and modified date; open its folder,
  inspect it in Browse, re-download it, or delete it with a confirmation.
- **Recent and pinned games**: the Browse landing remembers the last six games you
  opened and keeps pinned favorites one click away. Pin from the current-game header
  or a game result’s context menu.

Linux is the primary release target. Windows code is retained, but this release's
automated process and GUI checks run on Linux.

The desktop app is organized into five workspaces — **Browse**, **Imports**,
**Library**, **Downloads**, and **Settings** — with a persistent download status
strip.

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
osw browse 108600 --sort toprated
osw browse 108600 --search "maps"
osw info 3820938264
osw download 108600 3820938264 --out ~/SteamMods
osw url "https://steamcommunity.com/sharedfiles/filedetails/?id=..."
osw batch "https://steamcommunity.com/sharedfiles/filedetails/?id=..."
osw batch --input workshop-links.txt --with-dependencies --out ~/SteamMods
# Already-installed items are skipped; --reinstall downloads them again:
osw download 108600 3820938264 --reinstall
# Optional account fallback (password and Steam Guard are prompted when needed):
osw download 108600 3820938264 --username YOUR_STEAM_USERNAME
```

## Bulk downloads and recovery

Open the **Imports** workspace for a mix of Workshop item and collection URLs,
or Ctrl/Shift-select mods in Browse and use the bulk action bar to queue them.
Bare numbers in an import are Workshop item IDs; bare numbers in game search are game IDs.
The optional game ID hint is used only when an item's own metadata lacks its game ID.

**Resolve list** fetches metadata, expands nested collections and, if enabled,
required items. It does not download mod files. Review any invalid/private items
or unresolved dependencies, uncheck unwanted mods, then choose **Queue selected**.
Valid items can still be queued when other entries have problems. Mods that are
already installed are marked **Installed** and left unchecked — re-check one to
reinstall it.

SteamCMD jobs run one at a time to avoid workspace/login conflicts. Browsing and
preview images continue in the background. Cancel stops the running process;
it is not a promise of byte-for-byte pause/resume. Retry may reuse SteamCMD's
cached data but always validates the current download result.

Downloads use `<mods root>/steamapps/workshop/content/<appid>/<itemid>/` by
default. For a game whose mods must live elsewhere, open **Browse** and use the
game header's **Mods folder** menu: *Change…* selects the folder (e.g. the game's
own `Mods`/`addons` directory), and finished items are then moved there as
`<chosen folder>/<Item title>/` with a hidden `.opensteamworkshop.json` marker.
*Clear (use default)* restores the default root. The move happens after SteamCMD
succeeds, so queued and running downloads are unaffected by later changes.

The GUI queue is saved in `~/.config/OpenSteamWorkshop/queue.json` and restored
as interrupted work. Choose **Resume unfinished** to restart it; nothing
automatically downloads at launch. CLI batch queues are transient.
Changing Settings affects new jobs, while already queued jobs retain their destination.
Queue files from earlier versions load unchanged; jobs without a per-game folder
keep using the default mods root.

The **Library** workspace scans the default content tree plus every configured
per-game mods folder without touching SteamCMD, marking delivered rows in a
**Location** column. **Open folder** reveals the installed files, **Inspect in
Browse** loads the item's metadata into the Browse inspector, **Re-download**
queues it through the normal download pipeline (delivering to the game's current
folder when one is set), and **Delete** asks for confirmation before removing the
item's folder. Non-numeric or unreadable entries are ignored, and a missing
content folder shows an empty state rather than an error.

Recent and pinned games and per-game mods folders live in
`~/.config/OpenSteamWorkshop/state.json`. That file is deliberately separate from
settings and contains only game IDs, names and folder paths. Delete it to reset
the Browse landing and per-game folders without touching your queue.

## Anonymous access and optional accounts

Anonymous login is the default. Whether it can download a particular game's
mods depends on the game's Workshop configuration, not whether the game is
installed locally. Steam may deny access to some content. This app reports that
response without treating every timeout or missing manifest as an ownership problem.

For an access/authentication failure, use **Retry with account**. Alternatively,
enable **Use this account for new downloads this session** in Settings. The GUI
prompts for passwords, Steam Guard codes or mobile approval when required.
In the CLI, explicitly pass `--username`; `--anonymous` always overrides it.
For noninteractive automation, `OSW_PASS` can supply the password when a username
is specified; interactive Steam Guard challenges still need a terminal.

Passwords and codes are never saved in application settings or queue files and
are not passed in process arguments. Old plaintext password settings are ignored
and removed the next time Settings is saved. SteamCMD may retain its own cached
login/session files in its managed workspace. Restored jobs default to anonymous
access; use **Retry with account** again when needed.

## Troubleshooting

- **SteamCMD won't start on Linux** — missing 32-bit runtime:
  ```bash
  sudo apt install lib32gcc-s1        # Debian/Ubuntu
  sudo pacman -S lib32-gcc-libs       # Arch
  ```
- **Access denied / No subscription** — Steam did not grant this login access.
  You can explicitly retry with an account that has access. Anonymous eligibility
  varies by game; it is not limited to free games.
- SteamCMD occasionally no-ops the first download attempt; the app retries
  automatically.
- **Some games have no Steam Workshop** (e.g. Cities: Skylines II publishes
  through Paradox Mods) — the app will tell you when a workshop hub
  doesn't exist for the game you picked.

## Development and verification

```bash
pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

The tests use fake SteamCMD processes and fixture metadata: no Steam account,
game installation, API key or live mod downloads are needed. Before publishing
a release, manually check an anonymous-compatible public mod and collection,
plus account/Steam Guard login with an authorized test account.

## Legal / ethics note

Workshop items belong to their authors. This tool is for personal use within
Steam's terms; don't redistribute other people's content.

## License

MIT.
