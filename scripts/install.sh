#!/usr/bin/env sh
# Install the mdtohtml release binary on Linux.
#
# Downloads the latest release zip for this platform, unpacks the binary and
# its themes/ folder into an install directory, and symlinks the binary onto
# your PATH. Re-runnable (idempotent). No sudo and no Python: everything goes
# under $HOME by default. After this, `mdtohtml update` keeps the binary
# current itself.
#
#   curl -fsSL https://raw.githubusercontent.com/MatLomax/mdtohtml/main/scripts/install.sh | sh
#
# Environment overrides:
#   MDTOHTML_INSTALL_DIR  where the binary + themes/ live (default: ~/.local/share/mdtohtml)
#   MDTOHTML_BIN_DIR      the PATH directory to symlink into (default: ~/.local/bin)
#   MDTOHTML_REPO         owner/repo to install from (default: MatLomax/mdtohtml)
set -eu

REPO="${MDTOHTML_REPO:-MatLomax/mdtohtml}"
INSTALL_DIR="${MDTOHTML_INSTALL_DIR:-$HOME/.local/share/mdtohtml}"
BIN_DIR="${MDTOHTML_BIN_DIR:-$HOME/.local/bin}"

die() { echo "install: $*" >&2; exit 1; }

# Refuse to treat a home directory or a filesystem root as the install dir:
# the installer replaces this directory wholesale, so a stray override must not
# point it at something precious.
case "$INSTALL_DIR" in
    "" | "/" | "$HOME" | "$HOME/") die "refusing to install into '$INSTALL_DIR'; set MDTOHTML_INSTALL_DIR to a dedicated directory" ;;
esac

# --- Resolve this platform's release asset name ---
case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) die "no prebuilt macOS binary is published yet; build from source: https://github.com/$REPO#building-binaries" ;;
    *) die "unsupported OS $(uname -s); build from source: https://github.com/$REPO" ;;
esac
case "$(uname -m)" in
    x86_64 | amd64) arch=x86_64 ;;
    *) die "no prebuilt binary for $(uname -s)/$(uname -m); build from source: https://github.com/$REPO" ;;
esac
asset="mdtohtml-${os}-${arch}.zip"

# --- HTTP helpers (curl or wget) ---
if command -v curl >/dev/null 2>&1; then
    http_get() { curl -fsSL "$1"; }
    http_dl() { curl -fsSL -o "$2" "$1"; }
elif command -v wget >/dev/null 2>&1; then
    http_get() { wget -qO- "$1"; }
    http_dl() { wget -qO "$2" "$1"; }
else
    die "need curl or wget"
fi
command -v unzip >/dev/null 2>&1 || die "need unzip"

# --- Latest release: one API call, reused for the tag and the asset digest ---
json="$(http_get "https://api.github.com/repos/${REPO}/releases/latest")" \
    || die "could not reach the latest release (offline?)"
tag="$(printf '%s\n' "$json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
[ -n "$tag" ] || die "could not determine the latest release (offline?)"
# The digest sits inside this asset's object. Scope the search to that object:
# `here` latches on our asset's "name" line and clears at the next asset's, so a
# missing digest degrades to empty rather than picking a later asset's hash.
digest="$(printf '%s\n' "$json" | awk -v n="\"name\": \"$asset\"" '
    /"name"/ { here = (index($0, n) > 0) }
    here && /"digest"/ { if (match($0, /sha256:[0-9a-f]+/)) { print substr($0, RSTART + 7, RLENGTH - 7); exit } }
')"

echo "Installing mdtohtml $tag ($asset) ..."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
zip="$tmp/$asset"
http_dl "https://github.com/${REPO}/releases/download/${tag}/${asset}" "$zip" \
    || die "download failed (does the release have $asset?)"

# --- SHA-256 verification (skipped with a notice when no digest/tool) ---
if [ -n "$digest" ]; then
    if command -v sha256sum >/dev/null 2>&1; then actual="$(sha256sum "$zip" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then actual="$(shasum -a 256 "$zip" | awk '{print $1}')"
    else actual=""; fi
    if [ -n "$actual" ] && [ "$actual" != "$digest" ]; then
        die "checksum mismatch for $asset: expected $digest, got $actual"
    fi
    [ -n "$actual" ] && echo "  sha256 verified" || echo "  (no sha256 tool; verification skipped, downloaded over HTTPS)"
else
    echo "  (release digest unavailable; verification skipped, downloaded over HTTPS)"
fi

# --- Unpack into a sibling of the install dir (same filesystem), then swap ---
parent="$(dirname "$INSTALL_DIR")"
mkdir -p "$parent"
newdir="$(mktemp -d "$parent/.mdtohtml-new.XXXXXX")"
trap 'rm -rf "$tmp" "$newdir"' EXIT
unzip -q "$zip" -d "$newdir"
[ -f "$newdir/mdtohtml" ] || die "release archive has no mdtohtml binary"
[ -d "$newdir/themes" ] || die "release archive has no themes/ directory"
chmod 0755 "$newdir/mdtohtml"

# Only ever replace an empty dir or a prior mdtohtml install, never someone
# else's populated directory.
if [ -e "$INSTALL_DIR" ]; then
    if [ ! -e "$INSTALL_DIR/mdtohtml" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
        die "refusing to overwrite non-empty $INSTALL_DIR (not a prior mdtohtml install)"
    fi
    olddir="$(mktemp -d "$parent/.mdtohtml-old.XXXXXX")"
    mv "$INSTALL_DIR" "$olddir/prev"
    if mv "$newdir" "$INSTALL_DIR"; then
        rm -rf "$olddir"
    else
        mv "$olddir/prev" "$INSTALL_DIR"  # restore the previous install on failure
        rm -rf "$olddir"
        die "could not place the new install at $INSTALL_DIR"
    fi
else
    mv "$newdir" "$INSTALL_DIR"
fi

# --- Symlink onto PATH (themes resolve through the symlink, via resolve()) ---
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/mdtohtml" "$BIN_DIR/mdtohtml"

echo "Installed: $INSTALL_DIR/mdtohtml"
echo "Linked:    $BIN_DIR/mdtohtml"
case ":$PATH:" in
    *":$BIN_DIR:"*) : ;;
    *)
        echo ""
        echo "NOTE: $BIN_DIR is not on your PATH. Add it, e.g.:"
        echo "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.profile && . ~/.profile"
        ;;
esac
echo ""
echo "Done. Run 'mdtohtml --help' to get started."
