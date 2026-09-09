#!/usr/bin/env bash
# Build the self-contained mdtohtml CLI binary with PyInstaller, then
# assemble the release zip (binary + themes/) that ships to users.
#
# Re-runnable: wipes build/ and dist/ first, then runs PyInstaller on the
# onefile spec via the project venv. Reports the built binary and the
# resulting zip path and size.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYINSTALLER="$ROOT/.venv/bin/pyinstaller"
if [[ ! -x "$PYINSTALLER" ]]; then
    # Fall back to a PATH-resolved pyinstaller (e.g. in CI without .venv).
    PYINSTALLER="pyinstaller"
fi

echo "Cleaning build/ and dist/ ..."
rm -rf "$ROOT/build" "$ROOT/dist"

echo "Running PyInstaller ..."
"$PYINSTALLER" --clean --noconfirm mdtohtml.spec

# The onefile binary is named per the spec (mdtohtml, or mdtohtml.exe on Windows).
BIN="$ROOT/dist/mdtohtml"
[[ -f "$BIN" ]] || BIN="$ROOT/dist/mdtohtml.exe"

if [[ ! -f "$BIN" ]]; then
    echo "ERROR: expected binary not found in dist/" >&2
    exit 1
fi

SIZE="$(du -h "$BIN" | cut -f1)"
echo ""
echo "Built: $BIN ($SIZE)"

# Assemble the release zip: binary + themes/ at the same level, so extracting
# it next to the executable is all a user needs to do (no rebuild required
# to add a theme afterward).
echo ""
echo "Assembling release zip ..."
STAGE="$ROOT/dist/release-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp "$BIN" "$STAGE/"
cp -r "$ROOT/mdtohtml/themes" "$STAGE/themes"

# Name the zip per the host OS/arch. The Windows executable is the .exe
# special case; otherwise derive the OS token from uname (Linux->linux,
# Darwin->macos) and the arch verbatim from uname -m.
ARCH="$(uname -m)"
if [[ "$BIN" == *.exe ]]; then
    OS="windows"
else
    case "$(uname -s)" in
        Linux) OS="linux" ;;
        Darwin) OS="macos" ;;
        *) OS="$(uname -s | tr '[:upper:]' '[:lower:]')" ;;
    esac
fi
ZIP_NAME="mdtohtml-${OS}-${ARCH}.zip"
ZIP_PATH="$ROOT/dist/$ZIP_NAME"
rm -f "$ZIP_PATH"

( cd "$STAGE" && zip -qr "$ZIP_PATH" . )
rm -rf "$STAGE"

ZIP_SIZE="$(du -h "$ZIP_PATH" | cut -f1)"
echo ""
echo "Release zip: $ZIP_PATH ($ZIP_SIZE)"
