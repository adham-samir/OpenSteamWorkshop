# User guide

[← OpenWorkshop](../README.md)

## Quick start

1. Launch **OpenWorkshop** from your app menu (Linux) or with `openworkshop-gui`.
2. Open **Games**, search for a game, and browse its Workshop in **Browse mods**.
3. Inspect a mod and click **Download**; follow progress in **Downloads**.
4. Open **Installed** to search local mods, check updates, or review duplicates.

Use the game switcher to revisit pinned/recent games. Browse mods and Installed
follow the selected game; Installed also offers **All games**. **Import links**
in the global header accepts item/collection links and IDs for a reviewable
preview. Imports and Downloads remain global when you switch games. Settings
sits at the bottom of the navigation.

Cards/list preference is remembered across launches; each game's search, sort,
page, artwork, scroll, and selection stay available during the current session.
Details open beside results in wide windows and as a dismissible page in smaller
ones. The persistent transfer strip opens Downloads from any workspace.

![Native OpenWorkshop Browse mods workspace](screenshots/openworkshop-browse.png)

This native desktop capture uses real public Steam data. See the
[screenshot gallery and capture instructions](screenshots/README.md) for more
states and artwork attribution.

Keyboard shortcuts: **Ctrl+F** Games search, **Ctrl+1** Browse mods, **Ctrl+2**
Import links, **Ctrl+3** Downloads, **Ctrl+4** Settings, **Ctrl+L** Installed,
and **/** Workshop search while browsing. **Escape** closes item details.

## How it works

**Where mods go.** By default, downloads land in
`<mods root>/steamapps/workshop/content/<appid>/<itemid>/`, with the mods root
defaulting to `~/SteamMods`. To deliver into a game's own folder, open **Browse mods**
→ game header → **Mods folder → Change…**. Finished items are moved to
`<chosen folder>/<Item title>/` and get a hidden `.opensteamworkshop.json`
marker. **Clear (use default)** restores the default root.

**Queue and settings.** The GUI queue is saved to
`~/.config/OpenSteamWorkshop/queue.json` and restored as interrupted work after
a restart; choose **Resume interrupted** to continue. Pinned games and per-game
folders and the optional cards/list preference live in `state.json` next to it. The same `.config/OpenSteamWorkshop`
folder is used on Windows (`C:\Users\<you>\.config\OpenSteamWorkshop`).
Changing Settings affects new jobs only; queued jobs keep their destination.

**Parallel downloads.** **Settings → Downloads → Concurrent games** (or `--parallel N`)
runs up to three jobs at a time. Extra workers use sibling workspaces such as
`steamcmd-w1`/`steamcmd-w2`, created automatically. Different games can run
together; two items from the same game still take turns so SteamCMD's
`appworkshop_<appid>.acf` is never written concurrently. The default is three
workers; lower it to 1 in Settings or with `--parallel 1`.

**Duplicates.** If an item exists both in the default tree and in a per-game
folder, the delivered copy is the live one and the default copy is leftover.
**Installed → Cleanup (N)** lists these and pre-ticks the safe default copies;
you can untick anything or choose between two delivered copies. The CLI's
`openworkshop cleanup` reports the same groups, and `--prune` deletes only the safe
recommendation, never an ambiguous one.

**Updates.** Installed compares each installed item with Steam's latest public
revision. Default-folder items use SteamCMD's `appworkshop_<appid>.acf`;
delivered items use the revision recorded in their marker. Outdated rows show
**Update available**; **Update** re-downloads in place, and **Update all** lets
you untick items before queueing. Update checks, bulk updates, and duplicate cleanup follow the displayed
Installed scope and filters. Open mods folder opens the default mods root. Items with no recorded revision are shown as
**Version unknown** instead of being guessed at.

## Anonymous access and accounts

Anonymous login is the default. Whether it works depends on the game's Workshop
settings — it is not limited to free games — and Steam may deny some content.

To retry a failed download with an account, use **Retry with account** in
Downloads, or enable **Use this account for new downloads this session** in
Settings. The CLI needs an explicit `--username`; add `--anonymous` to force
anonymous mode. Passwords and Steam Guard codes are kept in memory only and are
never written to settings or queue files. For noninteractive scripts, `OSW_PASS`
can supply a password, but Steam Guard still needs a terminal.

## Troubleshooting

- **SteamCMD won't start on Linux** — install the 32-bit runtime:
  ```bash
  sudo apt install lib32gcc-s1        # Debian/Ubuntu
  sudo pacman -S lib32-gcc-libs       # Arch
  ```
- **`openworkshop-gui` is not recognized on Windows** — use
  `py -m osw.gui.main_window`, or add Python's `Scripts` folder to `PATH`.
- **No app-menu entry on Linux** — run `openworkshop desktop-install`, then search again.
  Some desktops need a log-out/log-in before the entry appears.
- **Access denied / No subscription** — Steam did not grant this login access.
  Retry with an account that owns the game or has Workshop access.
- **The first download quietly does nothing** — SteamCMD occasionally no-ops the
  first attempt; the app retries automatically.
- **The game has no Workshop** — some games publish mods elsewhere (for example
  Cities: Skylines II uses Paradox Mods); the app reports when a Workshop hub
  does not exist.
