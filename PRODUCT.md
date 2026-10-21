# Product Context — OpenWorkshop

## What this product is

OpenWorkshop is a Linux-first native desktop app for finding Steam games,
browsing their Workshop catalogues, reviewing content, and downloading it with
Valve's official SteamCMD without installing the game. The same engine is
available through the `osw` CLI. It is a game-focused download workspace, not a
game launcher or a system for profiles and mod enable/disable management.

## Who it is for

First-time users arrive with a Workshop link, a collection, or a game's name.
They need a clear path from finding a game or reviewing links to queueing mods.
Anonymous access is the default; the interface explains when Steam denies access.

Returning users need to revisit games, inspect installed content, review updates,
resolve bulk imports, and recover interrupted or failed transfers without losing
their browsing context.

## Core jobs

1. Find a game, pin it, revisit it, and browse its Workshop with search, sorting,
   paging, and cards or a compact list.
2. Inspect an item's author, size, popularity, description and required items.
3. Import Workshop links, IDs, collections, and text lists; resolve ownership and
   dependencies before reviewing the items to download.
4. Download through SteamCMD with a durable queue and configurable concurrency
   of one to three different games. Items from the same game remain serialized.
5. Recover from failures and interruptions with retry, account fallback, logs,
   output folders, cancellation, and explicit resume.
6. Inspect installed content in a selected game or the explicit All games scope;
   search, filter by update state, check updates, review duplicates, open folders,
   re-download, and delete with confirmation.
7. Choose the default mods root and optional per-game delivery folders.
8. Configure concurrent games, an optional session account, SteamCMD, and the
   Linux application-menu integration.

## Product principles

- **Make scope explicit.** Browse mods and Installed follow the current game;
  Installed also offers All games. Imports and Downloads are global workspaces.
- **One clear next action.** Discovery, resolution, queueing, retry, and resume
  should each be obvious in their relevant state.
- **Show actual work.** Progress, queue counts, and failures come from real
  snapshots. Concurrent work reflects the configured one-to-three-game limit.
- **Review before downloading.** The import preview includes dependency and
  resolution issues before a user commits. An app hint never overrides
  authoritative ownership returned by Workshop resolution.
- **Keep context.** Per-game Workshop query, sort, page, artwork, scroll, and
  selection survive navigation and game changes in the current session.
  Installed preserves its scope-specific filters, scroll, and selection.
- **Protect installed content.** Re-downloads and deletion retain their existing
  checks and confirmations. Filtered actions operate on the displayed scope.
- **Make recovery readable.** Empty, loading, offline, denied, authentication,
  interrupted, failed, and completed states use visible inline text.
- **Accessible desktop use.** Keyboard paths, accessible names, visible focus,
  non-color state indicators, and a usable 960 × 640 window are requirements.

## Workspaces

- **Games:** find Steam games and open pinned or recent games with landscape art.
- **Browse mods:** the current game's Workshop, search, sorting, pagination,
  cards/list choice, selection, item details, and a Mods folder menu.
- **Installed:** local Workshop content for the current game or All games, with
  proxy-backed search/update filters and scoped update/cleanup actions.
- **Downloads:** global active, waiting, interrupted, failed, and finished work,
  with state-specific selected-job recovery actions.
- **Import links:** a global draft preserved while moving between games and
  pages. Source, dependencies, and issues scroll beside a model-backed preview.
- **Settings:** scrolling Storage, Downloads, Steam account, and Application
  integration sections, with inline validation and save feedback.

A persistent searchable game switcher sits above Games, Browse mods, Installed,
and Downloads navigation. Settings sits at the bottom. Import links is available
from the global header. A transfer strip below the workspace opens Downloads.

The default window is 1150 × 740 with a minimum of 960 × 640. Navigation becomes
an icon rail below 1120 px. Details appear beside Browse results at 1280 px and
above; narrower windows show dismissible details within the page.

## Compatibility and boundaries

PySide6 remains the implementation stack. Linux is the validated visual platform;
Windows remains supported without a separate visual adaptation. No site build or
new runtime dependency is needed. Use the system UI font, packaged monochrome
icons, and relevant game/Workshop artwork.

The route IDs `browse`, `imports`, `library`, `downloads`, and `settings` remain;
`games` is added. Visible Installed continues to use the `library` route. Existing
keyboard paths remain: Ctrl+1 Browse, Ctrl+2 Import links, Ctrl+3 Downloads,
Ctrl+4 Settings, Ctrl+L Installed, Ctrl+F Games search, and / Workshop search.

The CLI, engine APIs, queue serialization, existing models, and settings remain
compatible. Optional `AppState.browse_presentation` persists cards/list across
launches; absent or invalid values fall back to cards with no migration. In-session
browse context is separate from this saved preference.

Steam's access rules remain authoritative. Passwords and Steam Guard codes stay
in memory for the session and are never written to settings or queue files.
Interrupted jobs restore without starting automatically: the user chooses Resume
interrupted. Existing queued jobs retain their captured destination and account
mode. No launching, profiles, or mod enable/disable behavior is introduced.

## Review evidence

The native implementation and Qt layouts are authoritative. `DESIGN.md` captures
its reusable visual system; `.impeccable/surfaces/desktop.md` captures the desktop
flow. `docs/screenshots/README.md` and the HTML gallery show actual runtime
captures at desktop sizes. Their queue, installed content, counts, and sample
metadata are illustrative fixtures, not live Steam results. Validation status
belongs in the implementation handoff rather than an unverified permanent test
count in product documentation.
