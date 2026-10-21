#!/usr/bin/env bash
# Remove an OpenSteamWorkshop installation created by install.sh.
#
# Settings, the download queue and your mods are left untouched.
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/opensteamworkshop"
VENV="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }

if [ -x "$VENV/bin/osw" ]; then
  "$VENV/bin/osw" desktop-uninstall || true
fi

# Idempotent fallback in case the venv or CLI is already gone.
rm -f "$DATA_HOME/applications/opensteamworkshop.desktop"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/opensteamworkshop.svg"

for name in osw osw-gui; do
  link="$BIN_DIR/$name"
  if [ -L "$link" ]; then
    target="$(readlink "$link")"
    case "$target" in
      "$VENV"/*) rm -f "$link" ;;
    esac
  fi
done

rm -rf "$INSTALL_DIR"

say "Removed OpenSteamWorkshop."
say "Your settings, download queue and mods were left untouched."
