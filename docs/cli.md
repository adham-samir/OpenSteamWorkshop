# Command line

[← OpenWorkshop](../README.md)

`openworkshop` exposes the same engine as the GUI:

```bash
openworkshop search project zomboid
openworkshop browse 108600 --sort toprated
openworkshop browse 108600 --search "maps"
openworkshop info 3820938264

# Download one or more items
openworkshop download 108600 3820938264
openworkshop download 108600 3820938264 --out ~/SteamMods

# Bulk downloads and collections
openworkshop batch "https://steamcommunity.com/sharedfiles/filedetails/?id=..."
openworkshop batch --input workshop-links.txt --with-dependencies

# Run up to three downloads at once (same-game items stay serialized)
openworkshop batch --input workshop-links.txt --with-dependencies --parallel 2
openworkshop settings --parallel 3   # default is already 3; lower it if needed

# Check for newer Workshop revisions, or fetch them all
openworkshop updates 108600
openworkshop updates 108600 --apply

# Report duplicate copies; --prune removes only the safe default copies
openworkshop cleanup
openworkshop cleanup --prune

# Installed items are skipped; --reinstall downloads them again
openworkshop download 108600 3820938264 --reinstall

# Optional Steam account (password/Steam Guard are prompted when needed)
openworkshop download 108600 3820938264 --username YOUR_STEAM_USERNAME

# Linux application-menu entry
openworkshop desktop-install
openworkshop desktop-uninstall
```
