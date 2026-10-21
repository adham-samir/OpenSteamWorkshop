#!/usr/bin/env bash
# Install OpenSteamWorkshop from the latest GitHub release (Linux, no root).
#
#   curl -fsSL https://raw.githubusercontent.com/adham-samir/OpenSteamWorkshop/main/install.sh | bash
#
# Override the version with OSW_VERSION=0.6.1 ./install.sh
set -euo pipefail

REPO="adham-samir/OpenSteamWorkshop"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/opensteamworkshop"
VENV="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || fail "python3 is required (install python3 first)."
command -v curl >/dev/null 2>&1 || fail "curl is required."

VERSION="${OSW_VERSION:-}"
if [ -z "$VERSION" ]; then
  say "Looking up the latest release…"
  VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')" \
    || fail "Could not read the latest release. Set OSW_VERSION and retry."
fi
[ -n "$VERSION" ] || fail "Could not determine the release version. Set OSW_VERSION and retry."

WHEEL="opensteamworkshop-${VERSION}-py3-none-any.whl"
URL="https://github.com/$REPO/releases/download/v${VERSION}/${WHEEL}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say "Downloading $WHEEL…"
curl -fsSL "$URL" -o "$TMP/$WHEEL" || fail "Download failed: $URL"

say "Installing into $INSTALL_DIR…"
python3 -m venv "$VENV" \
  || fail "Could not create a virtualenv. On Debian/Ubuntu install python3-venv."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "$TMP/$WHEEL"

mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/osw" "$BIN_DIR/osw"
ln -sf "$VENV/bin/osw-gui" "$BIN_DIR/osw-gui"

say "Adding OpenSteamWorkshop to the application menu…"
"$VENV/bin/osw" desktop-install

say ""
say "Installed OpenSteamWorkshop $VERSION."
say "  Application menu: search for OpenSteamWorkshop"
say "  Terminal:         osw --version"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "Note: $BIN_DIR is not on PATH; add it to use osw from a terminal." ;;
esac
say "Uninstall later with the repository's uninstall.sh."
