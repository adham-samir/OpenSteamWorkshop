# Native desktop screenshots

These are actual PySide6 runtime captures of the desktop implementation. The
native Qt source is authoritative. The [HTML gallery](../mockups/transfer-desk.html)
uses these same images; it replaces the obsolete static mockup.

Queue states, installed rows, counts, sizes, long sample titles, and dependency
relationships are illustrative fixtures. They are not current Steam data or a
claim that the pictured items are installed. Wiremod and PAC3 use real Workshop
artwork; the remaining placeholder previews deliberately exercise missing art.

| Capture | Demonstrates |
| --- | --- |
| [First use, 1440 × 900](1440x900-games-first-use.png) | Game discovery before pinned/recent games |
| [Games, 1440 × 900](1440x900-games.png) | Game-focused navigation and landscape art |
| [Browse, 1440 × 900](1440x900-browse.png) | Cards, search, sort, selection and pagination |
| [Details, 1440 × 900](1440x900-details.png) | Adjacent details pane at wide widths |
| [Details, 960 × 640](960x640-details.png) | Dismissible in-page details and compact rail |
| [List, 1150 × 740](1150x740-list.png) | Compact alternative to cards |
| [Installed, 1150 × 740](1150x740-installed.png) | Scope, filters, updates and selected-item actions |
| [Downloads, 960 × 640](960x640-downloads.png) | Queue states and selected-job recovery |
| [Import links, 1150 × 740](1150x740-imports.png) | Source/issues column beside the preview |
| [Settings, 1440 × 900](1440x900-settings.png) | Scrolling preference sections |
| [Details, logical 960 × 640 at 2×](960x640-details@2x.png) | High-DPI rendering at 1920 × 1280 pixels |

## Regenerate

From a source checkout with development dependencies installed:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/capture_ui.py --art-dir /tmp
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 .venv/bin/python tools/capture_ui.py --art-dir /tmp --suffix @2x
```

The default output is `.impeccable/review/`, ignored by Git. `--out PATH` selects
another output directory. Each pass captures all nine states at three logical
window sizes. Copy selected images to this directory after reviewing them.

The script uses fixture metadata, disables hub requests and real workers, and
performs no network requests or real downloads. It redirects settings and queue
paths to `/tmp/osw-ui-capture`. It loads optional artwork from `--art-dir`; the
default `/tmp` expects these pre-existing files:

- `/tmp/osw-garry.jpg`
- `/tmp/osw-rimworld.jpg`
- `/tmp/osw-wiremod.jpg`
- `/tmp/osw-pac3.jpg`

Omit the files to exercise the native missing-artwork placeholders. The capture
script does not fetch artwork automatically.

## Artwork attribution

Game and Workshop artwork belongs to its respective owners and item authors.
The checked-in runtime captures use:

- [Garry's Mod Steam header](https://cdn.cloudflare.steamstatic.com/steam/apps/4000/header.jpg)
- [RimWorld Steam header](https://cdn.cloudflare.steamstatic.com/steam/apps/294100/header.jpg)
- [Wiremod Workshop item](https://steamcommunity.com/sharedfiles/filedetails/?id=160250458)
- [PAC3 Workshop item](https://steamcommunity.com/sharedfiles/filedetails/?id=104691717)

These attribution links identify the supplied artwork sources. No claim of
affiliation or redistribution rights over Workshop content is implied.
