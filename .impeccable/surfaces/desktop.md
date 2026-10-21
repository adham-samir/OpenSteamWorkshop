# Desktop surface — OpenSteamWorkshop

Status: implemented native PySide6 workspace. The approved Thunderstore/Gale
reference informs its game focus, charcoal palette, soft white text, restrained
blue, system font, and compact monochrome controls. `DESIGN.md` captures shared
visual tokens; the Qt implementation governs actual rendering.

## Composition and navigation

The persistent left rail starts with a searchable current-game switcher. Its
primary destinations are Games, Browse mods, Installed, and Downloads. Settings
anchors the bottom; Import links is a global header action. The bottom transfer
strip stays present and opens Downloads.

| Visible workspace | Route | Scope |
| --- | --- | --- |
| Games | `games` | Steam game discovery, pinned and recent games |
| Browse mods | `browse` | Current game |
| Installed | `library` | Current game or explicit All games |
| Import links | `imports` | Global draft and resolved preview |
| Downloads | `downloads` | Global queue |
| Settings | `settings` | Application preferences and session credentials |

Game switching preserves each game's Workshop search, sort, page, artwork,
scroll, and selected items during the session. Returning from Downloads,
Settings, Imports, or item details keeps that context. Cards/list presentation is
an optional persisted AppState preference, defaulting to cards for older state.
Installed preserves scope-specific filters, scroll, and selection. The global
import draft survives game and workspace changes.

## Workflows

Games supports search, pinned/recent landscape cards, loading, and first-use
states. Opening a game selects it for Browse mods and Installed. The switcher's
search filters recent/pinned entries and can start a wider Steam game search.

Browse mods places game identity, pinning, and Mods folder actions above Workshop
search, sort, cards/list controls, pagination, and concise result context. Cards
show real previews when available and labelled placeholders otherwise. Inspect a
mod without losing the result set; close details to return. Multi-selection and
queueing use the shared item model. Already-installed protection remains active.

Installed exposes the current-game or All games scope, search, and update-state
filters above a model-backed table. Check updates, Update all, and Cleanup
target the displayed scope; selected actions resolve the authoritative
item through the proxy model. Bulk actions include the active filters. Open mods folder opens the default
mods root. Deletion
and reinstallation preserve confirmation and path protections.

Import links keeps source input, dependency choice, resolution issues, and
resolution controls in a scrolling column beside the review table. The global
draft is independent of the selected game. Workshop resolution supplies the
actual owner game; an app hint cannot silently reassign content. Review resolved
items before queueing selected rows.

Downloads exposes global queue filters and a selected-job footer for recovery.
Progress and counts come from job snapshots. Account retry, explicit resume,
cancel, logs, output folders, and clear-finished actions retain their existing
semantics. Settings applies the real concurrency limit of one to three different
games; two jobs for one game never run together.

Settings scrolls through Storage, Downloads, Steam account, and Application
integration. SteamCMD lives in Downloads; the application-menu controls live in
Application integration. Validation and save feedback are inline. Passwords and Guard
codes stay in session memory. Changing settings applies to new work; queued jobs
keep their recorded destination and account mode.

## Window behavior

| Window condition | Behavior |
| --- | --- |
| Default | 1150 × 740 logical pixels |
| Minimum | 960 × 640 logical pixels |
| Width below 1120 | 208 px navigation contracts to a 64 px icon rail |
| Width below 1080 | Transfer strip uses its narrow form |
| Width at least 1280 | Item details sit beside Browse results |
| Width below 1280 | Dismissible item details replace Browse results in-page |
| Scale factor 2 | Same logical layout, doubled screenshot pixel dimensions |

Compact navigation retains tooltips and accessible names. Scroll regions keep
Settings and import controls reachable at minimum height. Essential actions stay
visible in text rather than relying on hover-only discovery.

## Keyboard contract

| Key | Action |
| --- | --- |
| Ctrl+F | Open Games and focus game search |
| Ctrl+1 | Browse mods |
| Ctrl+2 | Import links |
| Ctrl+3 | Downloads |
| Ctrl+4 | Settings |
| Ctrl+L | Installed |
| / | Focus Workshop search while Browse is active |
| Escape | Dismiss Browse item details |

No game launch, profile, or mod enable/disable controls are implied by this
surface. The earlier transfer-desk mockup is superseded by the native runtime
screenshots in `docs/screenshots/`; the HTML at its historical path is a gallery.

## Evidence and regeneration

`tools/capture_ui.py` captures native first-use, games, cards, list, details,
installed, downloads, imports, and settings states at 960 × 640, 1150 × 740, and
1440 × 900, including a scale-factor-2 pass. `docs/screenshots/README.md` documents
commands, fixture limits, and artwork origins. Full review captures remain local
under ignored `.impeccable/review/`; a compact representative set is checked in.
