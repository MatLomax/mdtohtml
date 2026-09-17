"""Tests for the self-update subcommand (mdtohtml/updater.py).

No real network or release download happens here: the HTTP seams
(``fetch_latest`` / ``_download``) are monkeypatched, and the atomic swap is
exercised against a fake install directory built from a locally-made zip.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from mdtohtml import updater


# ── Version comparison ──


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("0.1.0", "0.2.0", True),
        ("0.1.0", "0.1.1", True),
        ("0.1.0", "1.0.0", True),
        ("0.2.0", "0.1.0", False),
        ("0.1.0", "0.1.0", False),
        ("v0.1.0", "v0.2.0", True),  # leading v tolerated
        ("0.1", "0.1.0", False),  # shorter equals padded
        ("0.1", "0.1.1", True),
        ("dev", "0.2.0", False),  # dev never upgrades
        ("0.1.0", "dev", False),  # non-numeric target never upgrades
        ("0.1.0-rc1", "0.2.0", True),  # earlier field (1<2) decides before -rc1 is reached
        ("0.2.0-rc1", "0.2.0", False),  # same version + pre-release: non-numeric guard engages
    ],
)
def test_semver_lt(a, b, expected):
    assert updater.semver_lt(a, b) is expected


def test_norm_strips_v_and_space():
    assert updater._norm("  v1.2.3 ") == "1.2.3"
    assert updater._norm("1.2.3") == "1.2.3"


# ── Asset / platform resolution ──


def test_asset_name_shape():
    assert updater.asset_name("linux", "x86_64") == "mdtohtml-linux-x86_64.zip"
    assert updater.asset_name("windows", "x86_64") == "mdtohtml-windows-x86_64.zip"


def test_arch_token_normalises_amd64(monkeypatch):
    import platform

    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    assert updater._arch_token() == "x86_64"
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert updater._arch_token() == "arm64"


@pytest.mark.parametrize(
    "plat,expected",
    [("linux", "linux"), ("linux2", "linux"), ("darwin", "macos"), ("win32", "windows")],
)
def test_os_token(monkeypatch, plat, expected):
    monkeypatch.setattr(updater.sys, "platform", plat)
    assert updater._os_token() == expected


# ── auto-update opt-out ──


@pytest.mark.parametrize("val,disabled", [("0", True), ("false", True), ("NO", True), ("off", True), ("1", False), ("", False)])
def test_auto_update_disabled(monkeypatch, val, disabled):
    monkeypatch.setenv(updater.AUTO_UPDATE_ENV, val)
    assert updater.auto_update_disabled() is disabled


def test_auto_update_enabled_by_default(monkeypatch):
    monkeypatch.delenv(updater.AUTO_UPDATE_ENV, raising=False)
    assert updater.auto_update_disabled() is False


# ── fetch_latest parsing ──


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_latest_parses_tag_and_assets(monkeypatch):
    payload = json.dumps(
        {
            "tag_name": "v0.3.0",
            "assets": [
                {
                    "name": "mdtohtml-linux-x86_64.zip",
                    "browser_download_url": "https://example/zip",
                    "digest": "sha256:abc123",
                },
                {"name": "no-url-asset.zip"},
            ],
        }
    ).encode()
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _FakeResp(payload))
    out = updater.fetch_latest("owner/repo", timeout=1)
    assert out["tag"] == "v0.3.0"
    assert out["assets"]["mdtohtml-linux-x86_64.zip"] == {"url": "https://example/zip", "digest": "abc123"}
    # digest prefix stripped; missing url -> empty string
    assert out["assets"]["no-url-asset.zip"]["url"] == ""


def test_fetch_latest_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise updater.urllib.error.URLError("offline")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    assert updater.fetch_latest("owner/repo", timeout=1) is None


def test_fetch_latest_none_without_tag(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"{}"))
    assert updater.fetch_latest("owner/repo", timeout=1) is None


# ── Building a fake release zip ──


def _make_release_zip(dest: Path, binary_bytes: bytes = b"NEW-BINARY", theme_css: str = "body{}") -> Path:
    """Write a release zip (binary + themes/ + LICENSE) laid out like the real one."""
    zpath = dest / "release.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(updater._binary_name(), binary_bytes)
        zf.writestr("themes/report.css", theme_css)
        zf.writestr("LICENSE", "MIT")
    return zpath


def _fake_install(dest: Path) -> Path:
    """A pre-existing install dir with an old binary + old themes + a stale leftover."""
    inst = dest / "install"
    inst.mkdir()
    (inst / updater._binary_name()).write_bytes(b"OLD-BINARY")
    (inst / "themes").mkdir()
    (inst / "themes" / "old.css").write_text("old")
    (inst / f"{updater._binary_name()}.old-999").write_bytes(b"leftover")
    return inst


# ── apply_release ──


def test_apply_release_swaps_binary_and_themes(tmp_path):
    inst = _fake_install(tmp_path)
    zpath = _make_release_zip(tmp_path, binary_bytes=b"NEW-BINARY", theme_css="body{color:red}")

    updater.apply_release(zpath, inst)

    assert (inst / updater._binary_name()).read_bytes() == b"NEW-BINARY"
    # new themes replaced the old ones entirely
    assert (inst / "themes" / "report.css").read_text() == "body{color:red}"
    assert not (inst / "themes" / "old.css").exists()
    # license copied over
    assert (inst / "LICENSE").read_text() == "MIT"
    # stale *.old-* leftover cleared
    assert not (inst / f"{updater._binary_name()}.old-999").exists()


def test_apply_release_rejects_archive_without_binary(tmp_path):
    inst = _fake_install(tmp_path)
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("themes/report.css", "body{}")
    with pytest.raises(ValueError, match="no mdtohtml"):
        updater.apply_release(zpath, inst)


def test_apply_release_rejects_archive_without_themes(tmp_path):
    inst = _fake_install(tmp_path)
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(updater._binary_name(), b"x")
    with pytest.raises(ValueError, match="no themes"):
        updater.apply_release(zpath, inst)


def test_apply_release_without_license_ok(tmp_path):
    """A release archive missing the optional LICENSE files still applies."""
    inst = _fake_install(tmp_path)
    zpath = tmp_path / "nolicense.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(updater._binary_name(), b"NEW")
        zf.writestr("themes/report.css", "body{}")
    updater.apply_release(zpath, inst)
    assert (inst / updater._binary_name()).read_bytes() == b"NEW"


def test_swap_file_windows_rolls_back_on_failed_move(monkeypatch, tmp_path):
    """On Windows, if moving the new binary in fails, the original is restored."""
    monkeypatch.setattr(updater.sys, "platform", "win32")
    target = tmp_path / "mdtohtml.exe"
    target.write_bytes(b"OLD")
    new = tmp_path / "new.exe"
    new.write_bytes(b"NEW")

    real_replace = updater.os.replace

    def flaky_replace(src, dst):
        # Fail only the move-in step (new -> target); let the aside + rollback succeed.
        if Path(src) == new:
            raise OSError("sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="sharing violation"):
        updater._swap_file(new, target)
    # The install is never left binary-less: the original is back in place.
    assert target.read_bytes() == b"OLD"


# ── do_update ──


def test_do_update_refuses_when_not_frozen(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    with pytest.raises(updater.UpdateError, match="not a release binary"):
        updater.do_update()


def _prime_frozen(monkeypatch, inst: Path):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setenv(updater.INSTALL_DIR_ENV, str(inst))


def test_do_update_none_when_current(monkeypatch, tmp_path):
    inst = _fake_install(tmp_path)
    _prime_frozen(monkeypatch, inst)
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": f"v{updater.__version__}", "assets": {}})
    assert updater.do_update() is None


def test_do_update_downloads_verifies_and_applies(monkeypatch, tmp_path):
    inst = _fake_install(tmp_path)
    _prime_frozen(monkeypatch, inst)

    zpath = _make_release_zip(tmp_path, binary_bytes=b"FRESH")
    digest = updater._sha256(zpath)
    name = updater.asset_name()
    monkeypatch.setattr(
        updater,
        "fetch_latest",
        lambda *a, **k: {"tag": "v99.0.0", "assets": {name: {"url": "https://x/zip", "digest": digest}}},
    )

    import shutil as _shutil

    def fake_download(url, dest, timeout):
        _shutil.copyfile(zpath, dest)
        return True

    monkeypatch.setattr(updater, "_download", fake_download)

    result = updater.do_update()
    assert result == (updater.__version__, "99.0.0")
    assert (inst / updater._binary_name()).read_bytes() == b"FRESH"


def test_do_update_checksum_mismatch_raises(monkeypatch, tmp_path):
    inst = _fake_install(tmp_path)
    _prime_frozen(monkeypatch, inst)
    zpath = _make_release_zip(tmp_path)
    name = updater.asset_name()
    monkeypatch.setattr(
        updater,
        "fetch_latest",
        lambda *a, **k: {"tag": "v99.0.0", "assets": {name: {"url": "https://x/zip", "digest": "deadbeef"}}},
    )

    import shutil as _shutil

    monkeypatch.setattr(updater, "_download", lambda url, dest, timeout: bool(_shutil.copyfile(zpath, dest)) or True)
    with pytest.raises(updater.UpdateError, match="checksum mismatch"):
        updater.do_update()


def test_do_update_bad_zip_raises_cleanly(monkeypatch, tmp_path):
    """A corrupt download (BadZipFile) surfaces as a clean UpdateError, not a traceback."""
    inst = _fake_install(tmp_path)
    _prime_frozen(monkeypatch, inst)
    name = updater.asset_name()
    monkeypatch.setattr(
        updater,
        "fetch_latest",
        lambda *a, **k: {"tag": "v99.0.0", "assets": {name: {"url": "https://x/zip", "digest": ""}}},
    )

    def write_garbage(url, dest, timeout):
        Path(dest).write_bytes(b"this is not a zip file")
        return True

    monkeypatch.setattr(updater, "_download", write_garbage)
    with pytest.raises(updater.UpdateError, match="could not apply the update"):
        updater.do_update()
    # The pre-existing binary is untouched (validation/extraction failed before any swap).
    assert (inst / updater._binary_name()).read_bytes() == b"OLD-BINARY"


def test_do_update_no_asset_for_platform_raises(monkeypatch, tmp_path):
    inst = _fake_install(tmp_path)
    _prime_frozen(monkeypatch, inst)
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": "v99.0.0", "assets": {}})
    with pytest.raises(updater.UpdateError, match="no asset for this platform"):
        updater.do_update()


def test_do_update_offline_raises(monkeypatch, tmp_path):
    inst = _fake_install(tmp_path)
    _prime_frozen(monkeypatch, inst)
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: None)
    with pytest.raises(updater.UpdateError, match="could not reach"):
        updater.do_update()


def test_do_update_not_writable_raises(monkeypatch, tmp_path):
    inst = _fake_install(tmp_path)
    _prime_frozen(monkeypatch, inst)
    name = updater.asset_name()
    monkeypatch.setattr(
        updater,
        "fetch_latest",
        lambda *a, **k: {"tag": "v99.0.0", "assets": {name: {"url": "https://x/zip", "digest": ""}}},
    )
    monkeypatch.setattr(updater.os, "access", lambda *a, **k: False)
    with pytest.raises(updater.UpdateError, match="not writable"):
        updater.do_update()


# ── command wrappers ──


def test_cmd_update_reports_change(monkeypatch, capsys):
    monkeypatch.setattr(updater, "do_update", lambda force=False: ("0.1.0", "0.2.0"))
    assert updater._cmd_update(force=False) == 0
    assert "updated 0.1.0 -> 0.2.0" in capsys.readouterr().out


def test_cmd_update_reports_current(monkeypatch, capsys):
    monkeypatch.setattr(updater, "do_update", lambda force=False: None)
    assert updater._cmd_update(force=False) == 0
    assert "already up to date" in capsys.readouterr().out


def test_cmd_update_error_exit_1(monkeypatch, capsys):
    def boom(force=False):
        raise updater.UpdateError("nope")

    monkeypatch.setattr(updater, "do_update", boom)
    assert updater._cmd_update(force=False) == 1
    assert "mdtohtml: nope" in capsys.readouterr().err


def test_cmd_check_newer(monkeypatch, capsys):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": "v99.0.0", "assets": {}})
    assert updater._cmd_check() == 0
    assert "newer release is available" in capsys.readouterr().out


def test_cmd_check_current(monkeypatch, capsys):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": f"v{updater.__version__}", "assets": {}})
    assert updater._cmd_check() == 0
    assert "up to date" in capsys.readouterr().out


# ── auto path ──


def test_cmd_auto_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setenv(updater.AUTO_UPDATE_ENV, "0")
    called = []
    monkeypatch.setattr(updater, "_spawn_detached", lambda *a, **k: called.append(a))
    assert updater._cmd_auto() == 0
    assert called == []


def test_cmd_auto_noop_when_not_frozen(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    called = []
    monkeypatch.setattr(updater, "_spawn_detached", lambda *a, **k: called.append(a))
    assert updater._cmd_auto() == 0
    assert called == []


def test_cmd_auto_spawns_when_newer(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.delenv(updater.AUTO_UPDATE_ENV, raising=False)
    inst = tmp_path / "install"
    inst.mkdir()
    monkeypatch.setenv(updater.INSTALL_DIR_ENV, str(inst))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": "v99.0.0", "assets": {}})
    spawned = []

    def fake_spawn(args, log):
        spawned.append(args)
        return True

    monkeypatch.setattr(updater, "_spawn_detached", fake_spawn)

    assert updater._cmd_auto() == 0
    assert spawned and spawned[0][0] == "update"
    # a lock directory was created for single-flight
    assert (tmp_path / "cache" / "mdtohtml" / "auto-update.lock").is_dir()


def test_cmd_auto_releases_lock_when_spawn_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.delenv(updater.AUTO_UPDATE_ENV, raising=False)
    inst = tmp_path / "install"
    inst.mkdir()
    monkeypatch.setenv(updater.INSTALL_DIR_ENV, str(inst))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": "v99.0.0", "assets": {}})
    monkeypatch.setattr(updater, "_spawn_detached", lambda args, log: False)  # spawn fails
    assert updater._cmd_auto() == 0
    # lock must NOT be left held, or auto-update stalls for an hour
    assert not (tmp_path / "cache" / "mdtohtml" / "auto-update.lock").exists()


def test_cmd_auto_noop_when_current(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.delenv(updater.AUTO_UPDATE_ENV, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": f"v{updater.__version__}", "assets": {}})
    spawned = []
    monkeypatch.setattr(updater, "_spawn_detached", lambda args, log: spawned.append(args))
    assert updater._cmd_auto() == 0
    assert spawned == []


def test_cmd_auto_single_flight_when_lock_held(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.delenv(updater.AUTO_UPDATE_ENV, raising=False)
    inst = tmp_path / "install"
    inst.mkdir()
    monkeypatch.setenv(updater.INSTALL_DIR_ENV, str(inst))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: {"tag": "v99.0.0", "assets": {}})
    # Pre-create a fresh lock: the run must back off and not spawn.
    lockdir = tmp_path / "cache" / "mdtohtml"
    lockdir.mkdir(parents=True)
    (lockdir / "auto-update.lock").mkdir()
    spawned = []
    monkeypatch.setattr(updater, "_spawn_detached", lambda args, log: spawned.append(args))
    assert updater._cmd_auto() == 0
    assert spawned == []


# ── main() dispatch ──


def test_main_dispatches_check(monkeypatch):
    monkeypatch.setattr(updater, "_cmd_check", lambda: 7)
    assert updater.main(["--check"]) == 7


def test_main_dispatches_auto(monkeypatch):
    monkeypatch.setattr(updater, "_cmd_auto", lambda: 5)
    assert updater.main(["--auto"]) == 5


def test_main_dispatches_update_and_releases_lock(monkeypatch, tmp_path):
    lock = tmp_path / "lock"
    lock.mkdir()
    monkeypatch.setattr(updater, "_cmd_update", lambda force: 0)
    assert updater.main(["--release-lock", str(lock)]) == 0
    assert not lock.exists()  # lock released in finally


def test_main_releases_lock_even_when_update_raises(monkeypatch, tmp_path):
    """A raise out of _cmd_update must still release the lock via the finally."""
    lock = tmp_path / "lock"
    lock.mkdir()

    def boom(force):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(updater, "_cmd_update", boom)
    with pytest.raises(RuntimeError, match="unexpected"):
        updater.main(["--release-lock", str(lock)])
    assert not lock.exists()


def test_cli_routes_update_subcommand(monkeypatch):
    """`mdtohtml update ...` reaches updater.main via the CLI first-token dispatch."""
    from mdtohtml import cli

    monkeypatch.setattr(updater, "main", lambda argv: 0)
    monkeypatch.setattr(cli.sys, "argv", ["mdtohtml", "update", "--check"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
