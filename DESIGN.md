# OpenSteamWorkshop — Design System ("Transfer Desk")

Visual system implemented by the PySide6 UI overhaul. The approved comp is
`docs/mockups/transfer-desk.html` with its 1440×900 render at
`docs/mockups/transfer-desk-1440x900.png`; it is the source of truth for spacing and
hierarchy. This document maps that direction to Qt widgets and defines the contract the
GUI tests assert against.

## 1. Direction

Dark-only. The window is a "transfer desk": a fixed left navigation, a content workspace,
a persistent bottom status strip, and dynamic side panels (inspector). Nothing about the
system introduces decoration: no gradients, no stock imagery; hierarchy comes from
elevation levels, the accent color, and spacing.

## 2. Color tokens

| Token | Hex | Use |
| --- | --- | --- |
| `BG` | `#101317` | Window background, page floor beneath content |
| `SURFACE` | `#171C22` | Cards, tables, nav rail, status strip |
| `RAISED` | `#1F2630` | Inputs, buttons, chips, secondary cells |
| `BORDER` | `#2E3742` | 1 px borders; subtle separators at 55% opacity |
| `TEXT` | `#F3F6F8` | Primary text |
| `TEXT2` | `#98A3AF` | Secondary text, placeholders, metadata |
| `ACCENT` | `#46B4E6` | Primary action, active nav, selection, progress |
| `ACCENT_TEXT` | `#07141C` | Text sitting on ACCENT |
| `OK` | `#4EC98A` | Done / success state |
| `WARN` | `#E8B84D` | Waiting-for-login / interrupted state |
| `BAD` | `#E5605C` | Failed / error state |

Rules:
- State is never color-only: every state color is paired with a monochrome icon or a text
  label (e.g. "Failed" chip includes the warning triangle).
- Text/surface contrast pairs used (WCAG AA on normal text): `#F3F6F8` on `#101317`,
  `#171C22`, `#1F2630`, `#2E3742`; `#98A3AF` on the same backgrounds for secondary text of
  ≥ 12 px; `#07141C` on `#46B4E6` for accent buttons.
- The accent is the *only* saturated hue for interaction. OK/WARN/BAD appear only as state
  chips, state dots, and progress fills.

## 3. Typography, icons, sizing

- Font: native system UI font (font family unset). No custom fonts packaged.
- Mono: system monospace for app IDs, item IDs, sizes, counts, and logs.
- Type scale (CSS px → pt at 96 dpi): page title 19 px/650 wt; section titles 13.5 px/650;
  body 13 px/1.45; secondary 12 px; mono metadata 11–12 px; card titles 12.8 px/570,
  max 2 lines with ellipsis.
- Icons: small packaged monochrome SVG set (`osw/gui/icons/*.svg`, loaded by
  `osw/gui/icons.py`), drawn on the 16 pt grid and tinted by state. They are included in
  the wheel via `[tool.setuptools.package-data]`.
- Touch/hit targets ≥ 24 px; buttons 29–34 px tall (sm 27 px, default 32 px, primary
  inspector download 34 px).

## 4. Layout

Window: default 1150×740, minimum 960×640, large reference 1440×900.

```
+--------+---------------------------------------------+-----------+
| nav    |  workspace content            (resizable    | inspector |
| 208 px |                               split)        | 300–440   |
|  rail  |                                             |           |
+--------+---------------------------------------------+-----------+
| status strip 52 px                                             |
+----------------------------------------------------------------+
```

- **Nav (208 px, 64 px collapsed).** Brand, then Browse / Imports / Library / Downloads
  with live counts, a flex gap, then a Secondary group with Settings. Below a 1120 px
  window width the nav collapses to a 64 px icon rail; counts become superscript bubbles;
  tooltips and accessible names stay on the icons.
- **Status strip (52 px, always visible).** One live transfer (spinner + title + progress
  + percentage), queued and failed chips, an interrupted/attention chip, and an
  "Open Downloads" hint. Activating any part of it opens Downloads. Built entirely from
  `JobSnapshot` updates.
- **Browse.** Page head (title + current-game chip + pin control + **Mods folder**
  menu + "Find a game" + "Import Workshop links"), workshop toolbar (search `/`,
  sort, pager), count line, card grid. The Mods folder menu shows the game's
  effective destination (override or default), and offers Change… / Clear (use
  default) / Open folder. First run replaces the grid with two hero actions plus up
  to six recent games and pinned favorites as compact chips; game results open in a
  focused results panel. Single selection → inspector (resizable side panel);
  multi-selection → bulk action bar.
- **Personal state.** Recent and pinned games persist in
  `~/.config/OpenSteamWorkshop/state.json`, separate from `settings.json` and
  `queue.json`; per-game mods folder overrides are additive in the same file.
  Pin/unpin from the current-game header or a game result’s context menu;
  pinned rows carry a star so state is never color-only. The landing caps each chip row
  at six entries and stays within 960×640.
- **Inspector (300–440 px, resizable).** Preview, title/byline, 2×2 stat grid (size,
  subscribers, rating, app id), collection/dependency notice, description clamp, ID line
  with copy, action stack (Download / Preview deps / In browser).
- **Downloads.** Filter chips (All / Active / Needs attention / Finished with counts),
  job rows (state dot, title + game/ID, size, state chip + progress, message, actions),
  page-level actions (Resume unfinished, Retry failed, Clear finished).
- **Imports.** Scrollable left column (source editor, options row, summary, issues list,
  action row) beside a preview table (checkbox, mod, game ID, source, size). The left
  column scrolls at 960×640 rather than clipping.
- **Library.** Model-backed table of directories under
  `<mods root>/steamapps/workshop/content/<appid>/<itemid>/` plus each configured
  per-game mods folder, with item title, game, location, installed size and modified
  date. Delivered rows win over leftover staged copies and are recognised by their
  `.opensteamworkshop.json` marker even when the folder is title-named. A cancelable
  background scan renders loading/empty /error states; titles and game names enrich
  in paced batches without delaying local rows. The selected-row action bar offers
  Open folder, Inspect in Browse, Re-download and a confirmation-gated Delete. The
  nav destination shows the installed count and `Ctrl+L` opens the workspace.
- **Settings.** Form with explicit labels; inline save errors; no dialog for the page
  itself.

## 5. Component behavior notes (Qt mapping)

- Cards and game results are `QAbstractListModel` rows rendered by delegates; thumbnails
  update by emitting `dataChanged` on the model, never touching item widgets.
- The download list is a `QAbstractTableModel` over `JobSnapshot` rows; filters are view
  sorts/proxies, actions dispatch through MainWindow controller slots.
- Import preview is a `QAbstractTableModel` (checkable Include column).
- All three render at 960×640 without clipping: grids reflow, the rail collapses, rows
  keep a 150 px message cell that elides with tooltips, and the strip drops sub-messages.
- Loading / empty / no-results / offline / private-item / dependency-issue /
  authentication / interrupted states are inline panels within the page that owns them,
  each with an icon + explanation + the action that resolves it.
- Progress is honest: queued jobs show an empty bar, running jobs show real progress, and
  only a running job with unknown progress shows an indeterminate sliver.

## 6. Motion & atmosphere

None by design (Qt limits aside): one indeterminate spinner (status strip + live row) and
instant state changes everywhere else.
