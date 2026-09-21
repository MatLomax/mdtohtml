#!/usr/bin/env bash
# Build the self-contained mdtohtml CLI binary with PyInstaller, then assemble
# the two release assets that ship to users: a themeless binary zip and a
# separate themes zip (mdtohtml-themes.zip).
#
# Re-runnable: wipes build/ and dist/ first, then runs PyInstaller on the
# onefile spec via the project venv. Reports the built binary and both zips.
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

# Assemble the two release assets: a themeless binary zip (binary + license
# notices) and a separate, OS-independent themes zip. The binary downloads the
# themes on demand, and `mdtohtml update` refreshes both.
echo ""
echo "Assembling release assets ..."
STAGE="$ROOT/dist/release-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp "$BIN" "$STAGE/"
# Ship the license notices as visible files beside the binary so the bundled
# third-party notices reach anyone who downloads the release zip.
cp "$ROOT/LICENSE" "$STAGE/"
cp "$ROOT/THIRD-PARTY-LICENSES" "$STAGE/"

# Name the binary zip per the host OS/arch. The Windows executable is the .exe
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

# Themes asset: a themes/ folder, not per-OS (the same zip serves every platform).
TSTAGE="$ROOT/dist/themes-stage"
rm -rf "$TSTAGE"
mkdir -p "$TSTAGE"
cp -r "$ROOT/mdtohtml/themes" "$TSTAGE/themes"
THEMES_ZIP="$ROOT/dist/mdtohtml-themes.zip"
rm -f "$THEMES_ZIP"
( cd "$TSTAGE" && zip -qr "$THEMES_ZIP" . )
rm -rf "$TSTAGE"

echo ""
echo "Binary zip: $ZIP_PATH ($(du -h "$ZIP_PATH" | cut -f1))"
echo "Themes zip: $THEMES_ZIP ($(du -h "$THEMES_ZIP" | cut -f1))"
