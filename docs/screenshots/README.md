# Screenshots

Captured from the running app on KDE using Spectacle, with real Steam game
results, Workshop data, and artwork. The window frame and title bar are included.

| Screenshot | View |
| --- | --- |
| [Browse mods](openworkshop-browse.png) | Garry’s Mod Workshop, sorted by Top rated |
| [Games](openworkshop-games.png) | Steam game search |
| [Mod details](openworkshop-details.png) | Selected mod alongside the results |

## Capture again

On a KDE desktop, with Spectacle and the app’s dependencies installed:

```bash
QT_QPA_PLATFORM=xcb .venv/bin/python tools/capture_ui.py --live --desktop --out .impeccable/review/desktop
```

The tool opens the app with a temporary profile, searches and browses through
mouse/keyboard events, and saves the visible window. Review the captures before
copying them here.

Captured: **2026-10-21T22:22:52.719623+00:00**.
Artwork belongs to the game publishers and mod authors.
[Capture metadata and artwork sources](live-capture.json).
