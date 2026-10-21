#!/usr/bin/env bash
# Install OpenWorkshop from the latest GitHub release (Linux, no root).
# curl -fsSL https://raw.githubusercontent.com/adham-samir/openworkshop/main/install.sh | bash
# Override the release with OSW_VERSION=0.6.1 ./install.sh.
set -euo pipefail

REPO="adham-samir/openworkshop"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
# Reuse the existing installation directory so upgrades do not leave two apps.
INSTALL_DIR="$DATA_HOME/opensteamworkshop"
VENV="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || fail "python3 is required (install python3 first)."
command -v curl >/dev/null 2>&1 || fail "curl is required."

VERSION="${OSW_VERSION:-}"
if [ -n "$VERSION" ]; then
  RELEASE_URL="https://api.github.com/repos/$REPO/releases/tags/v${VERSION#v}"
else
  RELEASE_URL="https://api.github.com/repos/$REPO/releases/latest"
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
say "Looking up the release…"
curl -fsSL "$RELEASE_URL" -o "$TMP/release.json" \
  || fail "Could not read the release. Set OSW_VERSION to an existing release and retry."
# Prefer the renamed wheel, but keep releases from before the rename installable.
URL="$(python3 - "$TMP/release.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)
for prefix in ("openworkshop-", "opensteamworkshop-"):
    for asset in release.get("assets", []):
        if asset["name"].startswith(prefix) and asset["name"].endswith("-py3-none-any.whl"):
            print(asset["browser_download_url"])
            raise SystemExit(0)
raise SystemExit("No supported wheel asset was found in this release.")
PY
)" || fail "The selected release has no supported wheel."
WHEEL="${URL##*/}"

say "Downloading $WHEEL…"
curl -fsSL "$URL" -o "$TMP/$WHEEL" || fail "Download failed: $URL"
say "Installing into $INSTALL_DIR…"
python3 -m venv "$VENV" \
  || fail "Could not create a virtualenv. On Debian/Ubuntu install python3-venv."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
# Both distributions own the osw module. Remove the previous distribution first
# so a later uninstall cannot remove files belonging to the replacement.
if [[ "$WHEEL" == openworkshop-* ]]; then
  "$VENV/bin/python" -m pip uninstall --quiet --yes opensteamworkshop
else
  "$VENV/bin/python" -m pip uninstall --quiet --yes openworkshop
fi
"$VENV/bin/python" -m pip install --quiet --upgrade "$TMP/$WHEEL"

CLI="openworkshop"
GUI="openworkshop-gui"
if [ ! -x "$VENV/bin/$CLI" ]; then
  CLI="osw"
  GUI="osw-gui"
fi
mkdir -p "$BIN_DIR"
for name in openworkshop osw; do
  ln -sf "$VENV/bin/$CLI" "$BIN_DIR/$name"
done
for name in openworkshop-gui osw-gui; do
  ln -sf "$VENV/bin/$GUI" "$BIN_DIR/$name"
done

say "Adding the application to the menu…"
"$VENV/bin/$CLI" desktop-install
say ""
say "Installed OpenWorkshop ($WHEEL)."
if [[ "$WHEEL" == opensteamworkshop-* ]]; then
  say "This older release still appears as OpenSteamWorkshop in the application menu."
else
  say "Application menu: search for OpenWorkshop"
fi
say "Terminal: openworkshop --version"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "Note: $BIN_DIR is not on PATH; add it to use openworkshop from a terminal." ;;
esac
say "Uninstall later with the repository's uninstall.sh."
