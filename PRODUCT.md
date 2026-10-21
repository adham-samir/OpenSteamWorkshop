# Product Context — OpenSteamWorkshop

## What this product is

OpenSteamWorkshop is a Linux-first desktop app for finding Steam games, browsing
their Workshop catalogues, reviewing Workshop content, and downloading it with
Valve's official SteamCMD — without installing the game. The same engine is
available through the `osw` CLI.

The interface is called **Transfer Desk**. It is a dark, focused workspace for
moving public Workshop content into a local mods folder. It is not a game
launcher, a mod manager, or a replacement for Steam.

## Who it is for

**First-time users** arrive with a Workshop link, a collection, or the name of a
game. They need to understand, without documentation, that they can find a game,
browse its Workshop, select a mod, and queue a download. Anonymous access is the
default and must be explained honestly: some games or items will deny it.

**Returning power users** arrive with queues, interrupted jobs, private items,
and bulk lists. They need to triage failures, resume work, inspect logs, retry
with an account, and queue collections without losing the game or search context
they were browsing.

## Core jobs

1. **Discover** a game and browse its Workshop with search, sorting, and paging.
2. **Inspect** a Workshop item: author, size, subscribers, rating, tags,
   description, and required items.
3. **Import** Workshop links, IDs, collections, and text lists; preview exactly
   what will be downloaded, including dependencies, before committing.
4. **Download** serially through SteamCMD, with visible progress and a durable,
   restart-safe queue.
5. **Recover** from failures and interruptions: retry, retry with a Steam
   account, open logs, open output folders, and clear finished work.
6. **Manage installed content** downloaded by SteamCMD: scan the default mods
   root and per-game folders, inspect local location, size and dates, open
   folders, re-download, and delete with confirmation.
7. **Choose where each game's mods live.** The default mods root is always the
   fallback; a per-game override moves finished downloads into a folder the game
   actually reads.
8. **Configure** the mods root, optional session account, and SteamCMD location.

## Product principles

- **One clear next action.** Every state should make the next safe action
  obvious: find a game, resolve a list, queue selected mods, retry, or resume.
- **Show, don't tell.** Loading, empty, no-results, offline, private,
  authentication, interrupted, failed, and completed states are visible inline.
  Tooltips are supplementary, never the only home for essential information.
- **Review before download.** Imports are a workspace, not a blocking dialog.
  Collections and dependencies resolve into a reviewable table.
- **Serially honest.** SteamCMD runs one job at a time. Progress, queue counts,
  and failures are always derived from real job snapshots, never invented.
- **Browse context is durable.** Queueing, inspecting, changing settings, and
  triaging failures should not discard the game, search, or selection.
- **Accessible by default.** Keyboard paths, accessible names, non-colour state
  indicators, readable contrast, and a 960 px-wide layout are requirements.

## Workspaces

- **Browse** — landing actions, game search results, Workshop search, model-
  backed cards, and a resizable side inspector. The current-game header carries
  the **Mods folder** menu for opting that game into a custom destination.
- **Imports** — paste links or load a file, choose dependency handling, resolve,
  review a model-backed table, read issues, and queue selected items.
- **Library** — scan the default mods root and per-game folders; inspect game,
  location, size and dates, open folders, re-download, or delete with confirmation.
- **Downloads** — active, needs-attention, and finished jobs; retry, cancel,
  account fallback, logs, folders, resume, and clear.
- **Settings** — storage, session account, and SteamCMD configuration.

A persistent compact status strip sits below every workspace and opens Downloads
when activated. Navigation collapses to an icon rail below 1120 px while keeping
tooltips and accessible names.

## Scope boundaries

- PySide6 remains the implementation stack. Linux is the validated visual
  platform; Windows remains functional without a separate visual adaptation.
- Authentication rules, Steam access rules, scraping, download semantics, and
  CLI behaviour do not change.
- The CLI commands, download engine APIs, queue serialization, data models, and
  settings keys remain compatible. No data migration is required.
- Passwords and Steam Guard codes remain session-only. They are never written to
  settings or queue files.
- Interrupted jobs restore without starting automatically. The user must choose
  **Resume unfinished**.
- No new runtime dependencies, gradients, or decorative imagery. The visual
  system uses a small packaged monochrome SVG icon set and the system UI font.

## Success criteria

A new user can discover or import content and queue a download without reading
documentation. A returning user can manage failures and bulk work without losing
browse context. All existing tests and Ruff checks pass, alongside new GUI tests
for the workspace system, state coverage, large lists, keyboard workflows, and
responsive renders at 960×640, 1150×740, and 1440×900.
