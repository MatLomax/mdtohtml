"""In-place self-update for the mdtohtml release binary.

``mdtohtml update`` replaces the installed release binary *and its* ``themes/``
folder with the latest GitHub release, atomically and in place. It uses only
the Python standard library embedded in the frozen binary, so it needs no
external runtime.

Self-update applies only to a PyInstaller-frozen binary: a pip/dev install is
managed by pip, so ``update`` there is a no-op with a pointer to pip.

Subcommand surface (``mdtohtml update [FLAGS]``):

    (no flags)   Check the latest release and, if newer, download + verify +
                 replace the binary in place.  Reports ``old -> new`` or that
                 it is already current.
    --check      Report whether a newer release exists; change nothing.
    --themes     Download this release's themes asset into the install
                 directory (the on-demand path for a themeless binary).
    --auto       The background path a session-start hook calls: TTL-gated,
                 timeout-bounded, single-flight, and fully detached, so it
                 never blocks or fails the caller.  Opt out with
                 ``MDTOHTML_AUTO_UPDATE=0``.
    --force      Reinstall the latest release even when versions already match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import __version__

# ── Constants ──

REPO = "MatLomax/mdtohtml"
_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_API_TAG = "https://api.github.com/repos/{repo}/releases/tags/{tag}"
_DOWNLOAD_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
_UA = "mdtohtml-self-update"

# The themes/ folder ships as its own OS-independent release asset. The binary
# is themeless; it downloads this on demand (and `update` refreshes it), so the
# two are matched to the release the binary was built from.
THEMES_ASSET = "mdtohtml-themes.zip"

AUTO_UPDATE_ENV = "MDTOHTML_AUTO_UPDATE"
CHECK_TTL_ENV = "MDTOHTML_UPDATE_CHECK_TTL"
INSTALL_DIR_ENV = "MDTOHTML_INSTALL_DIR"

DEFAULT_TTL = 86_400  # a day
_HTTP_TIMEOUT = 20
_AUTO_HTTP_TIMEOUT = 3
_LOCK_STALE_SECS = 3_600


# ── Platform / asset resolution ──


def _os_token() -> str:
    """The OS token used in a release asset name (``linux``/``macos``/``windows``)."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _arch_token() -> str:
    """The architecture token used in a release asset name (verbatim ``uname -m``)."""
    import platform

    machine = platform.machine()
    # Normalise the common amd64 spelling to the x86_64 the release zips use.
    return "x86_64" if machine.lower() in {"amd64", "x86_64"} else machine


def asset_name(os_token: str | None = None, arch_token: str | None = None) -> str:
    """Release asset file name for this platform, e.g. ``mdtohtml-linux-x86_64.zip``."""
    return f"mdtohtml-{os_token or _os_token()}-{arch_token or _arch_token()}.zip"


def _binary_name() -> str:
    """The executable's file name on this platform."""
    return "mdtohtml.exe" if sys.platform.startswith("win") else "mdtohtml"


# ── Version comparison ──


def _norm(version: str) -> str:
    """Strip a leading ``v`` and surrounding whitespace from a version string."""
    return version.strip().lstrip("vV")


def semver_lt(a: str, b: str) -> bool:
    """True iff version *a* is strictly older than *b* (leading ``v`` optional).

    A non-numeric field in either version yields "not older", so a dev build or
    a pre-release is never treated as upgradable — self-update only ever moves a
    real release forward.
    """
    fa = _norm(a).split(".")
    fb = _norm(b).split(".")
    for x, y in zip(fa + ["0"] * (len(fb) - len(fa)), fb + ["0"] * (len(fa) - len(fb))):
        if not x.isdigit() or not y.isdigit():
            return False
        if int(x) < int(y):
            return True
        if int(x) > int(y):
            return False
    return False


# ── Install location ──


def is_frozen() -> bool:
    """True when running as a PyInstaller-frozen binary (the only self-updatable form)."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """The directory holding the running binary and its ``themes/`` folder.

    Resolves symlinks, so a ``~/.local/bin/mdtohtml`` symlink into the real
    install directory yields that directory (where ``themes/`` lives), not the
    symlink's directory.  An override via ``MDTOHTML_INSTALL_DIR`` supports
    tests and unusual layouts.
    """
    override = os.environ.get(INSTALL_DIR_ENV)
    if override:
        return Path(override)
    return Path(sys.executable).resolve().parent


# ── Cache / lock ──


def _cache_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "mdtohtml"


def _ttl() -> int:
    try:
        return int(os.environ.get(CHECK_TTL_ENV, DEFAULT_TTL))
    except ValueError:
        return DEFAULT_TTL


def auto_update_disabled() -> bool:
    """True when ``MDTOHTML_AUTO_UPDATE`` opts out of the automatic path."""
    return os.environ.get(AUTO_UPDATE_ENV, "1").strip().lower() in {"0", "false", "no", "off"}


# ── Network ──


def _request(url: str, timeout: int) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})


def _parse_release(data: dict) -> dict | None:
    """Shape a GitHub release JSON into ``{"tag", "assets": {name: {url, digest}}}``.

    Returns ``None`` when the payload carries no tag.
    """
    tag = data.get("tag_name")
    if not tag:
        return None
    assets = {}
    for a in data.get("assets", []):
        name = a.get("name")
        if not name:
            continue
        digest = a.get("digest") or ""
        assets[name] = {
            "url": a.get("browser_download_url", ""),
            "digest": digest[len("sha256:") :] if digest.startswith("sha256:") else "",
        }
    return {"tag": tag, "assets": assets}


def _fetch_json(url: str, timeout: int) -> dict | None:
    """GET *url* and parse JSON, or ``None`` on any network/parse failure."""
    try:
        with urllib.request.urlopen(_request(url, timeout), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def fetch_latest(repo: str = REPO, timeout: int = _HTTP_TIMEOUT) -> dict | None:
    """Latest release as ``{"tag": str, "assets": {name: {"url", "digest"}}}``.

    Returns ``None`` on any network/parse failure so callers can stay silent
    when offline.
    """
    data = _fetch_json(_API_LATEST.format(repo=repo), timeout)
    return _parse_release(data) if data is not None else None


def fetch_release(tag: str, repo: str = REPO, timeout: int = _HTTP_TIMEOUT) -> dict | None:
    """The release for a specific *tag* as ``{"tag", "assets"}``, or ``None``.

    Used to fetch the themes asset from the release the running binary was built
    from, keeping themes version-matched to the converter.
    """
    data = _fetch_json(_API_TAG.format(repo=repo, tag=tag), timeout)
    return _parse_release(data) if data is not None else None


def _download(url: str, dest: Path, timeout: int) -> bool:
    try:
        with urllib.request.urlopen(_request(url, timeout), timeout=timeout) as resp:
            with open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Atomic in-place swap ──


def _swap_file(new: Path, target: Path) -> None:
    """Move *new* onto *target*, tolerating a running executable.

    POSIX can replace a running binary directly (the open inode survives).
    Windows refuses to overwrite a running ``.exe`` but allows renaming it, so
    the current file is moved aside first; the leftover is cleared on the next
    run by :func:`_clear_stale`.
    """
    if sys.platform.startswith("win") and target.exists():
        aside = target.with_name(target.name + f".old-{os.getpid()}")
        os.replace(target, aside)
        try:
            os.replace(new, target)
        except OSError:
            # The move-in failed (AV lock, sharing violation): put the original
            # back so the install is never left without a runnable binary.
            os.replace(aside, target)
            raise
    else:
        os.replace(new, target)


def _swap_dir(new: Path, target: Path) -> None:
    """Replace directory *target* with *new* by renaming the old one aside first."""
    if target.exists():
        aside = target.with_name(target.name + f".old-{os.getpid()}")
        os.replace(target, aside)
        shutil.rmtree(aside, ignore_errors=True)
    os.replace(new, target)


def _clear_stale(directory: Path) -> None:
    """Remove ``*.old-*`` leftovers a prior Windows swap could not delete in place."""
    for leftover in directory.glob("*.old-*"):
        try:
            if leftover.is_dir():
                shutil.rmtree(leftover, ignore_errors=True)
            else:
                leftover.unlink()
        except OSError:
            pass


def apply_binary(zip_path: Path, dest: Path) -> None:
    """Extract the binary from *zip_path* and swap it into *dest*.

    Staging is unpacked on the same filesystem as *dest* so the swap is a
    rename, not a cross-device copy.  Raises ``ValueError`` if the archive has
    no binary.
    """
    _clear_stale(dest)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".mdtohtml-update-") as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(stage)
        new_bin = stage / _binary_name()
        if not new_bin.is_file():
            raise ValueError(f"release archive has no {_binary_name()}")
        new_bin.chmod(0o755)
        _swap_file(new_bin, dest / _binary_name())
        for extra in ("LICENSE", "THIRD-PARTY-LICENSES"):
            src = stage / extra
            if src.is_file():
                try:
                    shutil.copyfile(src, dest / extra)
                except OSError:
                    pass


def apply_themes(zip_path: Path, dest: Path) -> None:
    """Extract the ``themes/`` folder from *zip_path* and swap it into *dest*.

    Staging is unpacked on *dest*'s filesystem so the swap is a rename.  Raises
    ``ValueError`` if the archive has no ``themes/`` directory.
    """
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".mdtohtml-themes-") as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(stage)
        new_themes = stage / "themes"
        if not new_themes.is_dir():
            raise ValueError("themes archive has no themes/ directory")
        _swap_dir(new_themes, dest / "themes")


# ── Commands ──


class UpdateError(Exception):
    """A self-update could not be completed (network, checksum, or write failure)."""


def _download_verified(asset: dict, dest: Path, tag: str, timeout: int) -> Path:
    """Download *asset* to *dest* and verify its sha256; raise on any failure."""
    if not _download(asset["url"], dest, timeout):
        raise UpdateError(f"download failed: {asset['url']}")
    expected = asset.get("digest")
    if expected:
        actual = _sha256(dest)
        if actual != expected:
            raise UpdateError(
                f"checksum mismatch for {dest.name} {tag}: expected {expected}, got {actual}"
            )
    return dest


def _resolve_update(force: bool, timeout: int) -> tuple[str, str, dict, dict] | None:
    """Return ``(current, tag, binary_asset, themes_asset)`` when an update should
    proceed, else ``None``.

    ``None`` means nothing to do (already current).  Raises :class:`UpdateError`
    for a genuine, reportable problem (offline, or a release missing an asset
    this platform needs).
    """
    current = __version__
    latest = fetch_latest(REPO, timeout)
    if latest is None:
        raise UpdateError("could not reach the latest release (offline or GitHub unavailable)")
    tag = latest["tag"]
    if not force and not semver_lt(current, tag):
        return None
    name = asset_name()
    binary_asset = latest["assets"].get(name)
    if not binary_asset or not binary_asset.get("url"):
        raise UpdateError(
            f"the latest release ({tag}) has no asset for this platform ({name}); "
            "download a release manually from "
            f"https://github.com/{REPO}/releases"
        )
    themes_asset = latest["assets"].get(THEMES_ASSET)
    if not themes_asset or not themes_asset.get("url"):
        raise UpdateError(
            f"the latest release ({tag}) has no {THEMES_ASSET}; "
            "download a release manually from "
            f"https://github.com/{REPO}/releases"
        )
    return current, tag, binary_asset, themes_asset


def do_update(force: bool = False, timeout: int = _HTTP_TIMEOUT) -> tuple[str, str] | None:
    """Perform the update if newer (or *force*); return ``(old, new)`` or ``None``.

    Downloads and verifies both the binary and themes assets, then swaps them in
    place -- themes before the binary, so an interruption leaves the safe
    inconsistency (old binary + new themes, which still renders) rather than a
    new binary against stale or missing themes.  ``None`` means already current.
    Raises :class:`UpdateError` on failure.
    """
    if not is_frozen():
        raise UpdateError(
            "this is not a release binary (a pip/dev install); upgrade with "
            "`pipx upgrade mdtohtml` or your package manager"
        )
    resolved = _resolve_update(force, timeout)
    if resolved is None:
        return None
    current, tag, binary_asset, themes_asset = resolved
    dest = install_dir()
    if not os.access(dest, os.W_OK):
        raise UpdateError(
            f"{dest} is not writable by you; re-run with write access, or reinstall "
            f"the release from https://github.com/{REPO}/releases"
        )
    with tempfile.TemporaryDirectory(prefix="mdtohtml-dl-") as tmp:
        tmpp = Path(tmp)
        bin_zip = _download_verified(binary_asset, tmpp / asset_name(), tag, timeout)
        themes_zip = _download_verified(themes_asset, tmpp / THEMES_ASSET, tag, timeout)
        try:
            apply_themes(themes_zip, dest)
            apply_binary(bin_zip, dest)
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            raise UpdateError(f"could not apply the update: {exc}") from exc
    return current, _norm(tag)


def ensure_themes(dest: Path | None = None, timeout: int = _HTTP_TIMEOUT) -> None:
    """Download this binary's matching themes asset into *dest*``/themes``.

    Fetches :data:`THEMES_ASSET` from the release matching the running binary's
    own version (its tag), verifies the sha256, and swaps it into place, so the
    themes match the converter that will use them.  *dest* defaults to the
    install directory.  Raises :class:`UpdateError` on any failure (offline, no
    matching release/asset, unwritable target, or checksum mismatch).
    """
    if dest is None:
        dest = install_dir()
    tag = f"v{_norm(__version__)}"
    release = fetch_release(tag, REPO, timeout)
    if release is None:
        raise UpdateError(
            f"could not reach the {tag} release to download themes (offline, or no "
            f"such release); download {THEMES_ASSET} manually from "
            f"https://github.com/{REPO}/releases"
        )
    asset = release["assets"].get(THEMES_ASSET)
    if not asset or not asset.get("url"):
        raise UpdateError(
            f"the {tag} release has no {THEMES_ASSET}; download it manually from "
            f"https://github.com/{REPO}/releases/tag/{tag}"
        )
    if not os.access(dest, os.W_OK):
        raise UpdateError(f"{dest} is not writable by you; cannot install themes there")
    with tempfile.TemporaryDirectory(prefix="mdtohtml-themes-dl-") as tmp:
        zip_path = _download_verified(asset, Path(tmp) / THEMES_ASSET, tag, timeout)
        try:
            apply_themes(zip_path, dest)
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            raise UpdateError(f"could not install themes: {exc}") from exc


def _cmd_update(force: bool) -> int:
    try:
        result = do_update(force=force)
    except UpdateError as exc:
        print(f"mdtohtml: {exc}", file=sys.stderr)
        return 1
    if result is None:
        print(f"mdtohtml is already up to date ({__version__}).")
    else:
        old, new = result
        print(f"mdtohtml updated {old} -> {new}.")
    return 0


def _cmd_themes() -> int:
    if not is_frozen():
        print("mdtohtml is a pip/dev install; its themes ship with the package.")
        return 0
    try:
        ensure_themes()
    except UpdateError as exc:
        print(f"mdtohtml: {exc}", file=sys.stderr)
        return 1
    print(f"mdtohtml: themes for {__version__} installed in {install_dir() / 'themes'}.")
    return 0


def _cmd_check() -> int:
    if not is_frozen():
        print("mdtohtml is a pip/dev install; upgrade with pipx or your package manager.")
        return 0
    latest = fetch_latest(REPO, _HTTP_TIMEOUT)
    if latest is None:
        print("mdtohtml: could not reach the latest release.", file=sys.stderr)
        return 1
    tag = latest["tag"]
    if semver_lt(__version__, tag):
        print(f"mdtohtml: a newer release is available ({__version__} -> {_norm(tag)}). Run `mdtohtml update`.")
    else:
        print(f"mdtohtml is up to date ({__version__}).")
    return 0


# ── Automatic (session-start) path ──


def _read_cache_tag(cache: Path, now: float) -> str | None:
    try:
        ts_str, tag = cache.read_text(encoding="utf-8").split()
        if now - float(ts_str) < _ttl():
            return tag
    except (OSError, ValueError):
        pass
    return None


def _write_cache_tag(cache: Path, now: float, tag: str) -> None:
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(f"{now} {tag}\n", encoding="utf-8")
    except OSError:
        pass


def _fetch_latest_bounded(timeout: int) -> dict | None:
    """``fetch_latest`` bounded by a hard wall-clock deadline.

    A socket timeout does not cover DNS resolution, so a stalled resolver could
    otherwise hang the session-start hook indefinitely. Running the fetch in a
    daemon thread and joining with a deadline bounds the delay no matter where
    the network stalls — on overrun the thread is abandoned (it is a daemon, so
    the process can still exit) and we act as if offline.
    """
    box: dict = {}

    def run() -> None:
        box["result"] = fetch_latest(REPO, timeout)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout + 1)
    return box.get("result")


def _spawn_detached(args: list[str], log: Path) -> bool:
    """Launch ``mdtohtml <args>`` fully detached; return whether it started."""
    kwargs: dict = {"stdin": subprocess.DEVNULL}
    try:
        out = open(log, "ab")
    except OSError:
        out = subprocess.DEVNULL
    kwargs["stdout"] = out
    kwargs["stderr"] = out
    if sys.platform.startswith("win"):
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, *args], **kwargs)
        return True
    except OSError:
        return False


def _cmd_auto() -> int:
    """Session-start path: never blocks, never fails the caller (always exit 0)."""
    if not is_frozen() or auto_update_disabled():
        return 0
    now = time.time()
    cache_dir = _cache_dir()
    cache = cache_dir / "update-check"

    tag = _read_cache_tag(cache, now)
    if tag is None:
        latest = _fetch_latest_bounded(_AUTO_HTTP_TIMEOUT)
        if latest is None:
            return 0  # offline, unreachable, or slow: stay silent, retry next session
        tag = latest["tag"]
        _write_cache_tag(cache, now, tag)

    if not semver_lt(__version__, tag):
        return 0  # already current

    dest = install_dir()
    if not os.access(dest, os.W_OK):
        print(
            f"mdtohtml: a newer release is available ({__version__} -> {_norm(tag)}), "
            f"but {dest} is not writable. Run `mdtohtml update` with write access."
        )
        return 0

    # Single-flight: one background update across concurrent session starts.
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0
    lock = cache_dir / "auto-update.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        try:
            age = now - lock.stat().st_mtime
        except OSError:
            return 0
        if age < _LOCK_STALE_SECS:
            return 0  # another session is already updating
        # Reclaim a crashed run's lock, then re-acquire.
        try:
            lock.rmdir()
            lock.mkdir()
        except OSError:
            return 0
    except OSError:
        return 0

    # The detached child runs the synchronous update, then drops the lock. Its
    # own re-check is cheap and keeps this path free of the download itself.
    if _spawn_detached(["update", "--release-lock", str(lock)], cache_dir / "auto-update.log"):
        print(
            f"mdtohtml: updating {__version__} -> {_norm(tag)} in the background; "
            f"the new version is used from your next run "
            f"(set {AUTO_UPDATE_ENV}=0 to disable)."
        )
    else:
        # The background update never started: release the lock so the next
        # session retries, and don't leave a false "updating..." impression.
        try:
            lock.rmdir()
        except OSError:
            pass
    return 0


# ── Entry point ──


def main(argv: list[str]) -> int:
    """Handle ``mdtohtml update`` and its flags. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="mdtohtml update",
        description="Update the mdtohtml release binary in place.",
    )
    parser.add_argument("--check", action="store_true", help="Report whether a newer release exists; change nothing.")
    parser.add_argument("--themes", action="store_true", help="Download this release's themes into the install directory.")
    parser.add_argument("--auto", action="store_true", help="Background, TTL-gated path for a session-start hook.")
    parser.add_argument("--force", action="store_true", help="Reinstall the latest release even when versions match.")
    # Internal: a detached --auto child passes the lock dir to release when done.
    parser.add_argument("--release-lock", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.auto:
        return _cmd_auto()
    if args.check:
        return _cmd_check()
    if args.themes:
        return _cmd_themes()

    try:
        return _cmd_update(args.force)
    finally:
        if args.release_lock:
            try:
                Path(args.release_lock).rmdir()
            except OSError:
                pass
