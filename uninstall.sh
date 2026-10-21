#!/usr/bin/env bash
# Remove an OpenWorkshop installation created by install.sh.
# Settings, the download queue and your mods are left untouched.
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/opensteamworkshop"
VENV="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }

for command in openworkshop osw; do
  if [ -x "$VENV/bin/$command" ]; then
    "$VENV/bin/$command" desktop-uninstall || true
    break
  fi
done

# Idempotent fallback in case the venv or CLI is already gone.
for app_id in openworkshop opensteamworkshop; do
  rm -f "$DATA_HOME/applications/$app_id.desktop"
  rm -f "$DATA_HOME/icons/hicolor/scalable/apps/$app_id.svg"
done
for name in openworkshop openworkshop-gui osw osw-gui; do
  link="$BIN_DIR/$name"
  if [ -L "$link" ]; then
    target="$(readlink "$link")"
    case "$target" in
      "$VENV"/*) rm -f "$link" ;;
    esac
  fi
done
rm -rf "$INSTALL_DIR"

say "Removed OpenWorkshop."
say "Your settings, download queue and mods were left untouched."
