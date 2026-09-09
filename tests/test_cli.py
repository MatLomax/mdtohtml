"""Tests for the CLI (mdtohtml/cli.py).

All tests mock ``converter.convert`` so no real HTML rendering happens here
— these tests exercise CLI routing, I/O logic, and validation only. Real
end-to-end conversion is covered by tests/test_converter.py and the
project's smoke test.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mdtohtml.cli import (
    _is_file_output,
    _write_content,
    _write_stdout,
    main,
)
from mdtohtml.converter import THEMES_DIR, default_themes_dir

# ── Canned response for the mocked converter ──

_FAKE_HTML = "<html><body>fake</body></html>"


def _mock_convert(md_text, theme, themes_dir, **kwargs):
    """Stand-in for ``converter.convert``."""
    return _FAKE_HTML


# ── Fixtures ──


@pytest.fixture()
def md_file(tmp_path: Path) -> Path:
    """Create a single .md file."""
    f = tmp_path / "doc.md"
    f.write_text("# Test\n\nBody.\n", encoding="utf-8")
    return f


@pytest.fixture()
def md_files(tmp_path: Path) -> list[Path]:
    """Create three .md files."""
    files = []
    for i in range(3):
        f = tmp_path / f"doc{i}.md"
        f.write_text(f"# Part {i}\n\nBody {i}.\n", encoding="utf-8")
        files.append(f)
    return files


def _run_cli(args: list[str], tmp_themes: Path) -> None:
    """Run ``main()`` with patched sys.argv, themes dir, and converter."""
    with (
        patch("sys.argv", ["mdtohtml", *args]),
        patch("mdtohtml.cli.default_themes_dir", return_value=tmp_themes),
        patch("mdtohtml.cli.convert", side_effect=_mock_convert),
        # Re-build choices so --theme validation sees the tmp themes
        patch("mdtohtml.cli.list_themes", return_value=["test-theme", "another"]),
    ):
        main()


def _run_cli_exit(args: list[str], tmp_themes: Path) -> int:
    """Run ``main()`` expecting a SystemExit and return the exit code."""
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(args, tmp_themes)
    return exc_info.value.code


# ═══════════════════════════════════════════════════════════════════════
# Unit tests: _is_file_output
# ═══════════════════════════════════════════════════════════════════════


class TestIsFileOutput:
    def test_html_extension(self) -> None:
        assert _is_file_output(Path("report.html")) is True

    def test_no_extension(self) -> None:
        assert _is_file_output(Path("output")) is False

    def test_non_html_extension(self) -> None:
        assert _is_file_output(Path("notes.md")) is False

    def test_uppercase_extension(self) -> None:
        assert _is_file_output(Path("REPORT.HTML")) is True


# ═══════════════════════════════════════════════════════════════════════
# Unit tests: _write_content / _write_stdout
# ═══════════════════════════════════════════════════════════════════════


class TestWriteContent:
    def test_write_str(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.html"
        _write_content("<html>ok</html>", dest)
        assert dest.read_text(encoding="utf-8") == "<html>ok</html>"


class TestWriteStdout:
    def test_write_str(self) -> None:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _write_stdout("text-data")
        assert buf.getvalue() == "text-data"


# ═══════════════════════════════════════════════════════════════════════
# Input validation
# ═══════════════════════════════════════════════════════════════════════


class TestInputValidation:
    def test_file_not_found(self, tmp_path: Path) -> None:
        code = _run_cli_exit(["nonexistent.md"], tmp_path)
        assert code == 1

    def test_not_markdown_extension(self, tmp_path: Path) -> None:
        txt = tmp_path / "notes.txt"
        txt.write_text("hello", encoding="utf-8")
        code = _run_cli_exit([str(txt)], tmp_path)
        assert code == 1


# ═══════════════════════════════════════════════════════════════════════
# Stdout mode
# ═══════════════════════════════════════════════════════════════════════


class TestStdoutMode:
    def test_html_to_stdout(self, md_file: Path, tmp_path: Path) -> None:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _run_cli([str(md_file)], tmp_path)
        assert buf.getvalue() == _FAKE_HTML

    def test_multi_files_error(
        self,
        md_files: list[Path],
        tmp_path: Path,
    ) -> None:
        args = [str(f) for f in md_files]
        code = _run_cli_exit(args, tmp_path)
        assert code == 1

    def test_conversion_value_error(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        def _raise(md_text, theme, themes_dir, **kwargs):
            raise ValueError("Markdown text must not be empty.")

        with (
            patch("sys.argv", ["mdtohtml", str(md_file)]),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", side_effect=_raise),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "another"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_conversion_generic_error(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        def _raise(md_text, theme, themes_dir, **kwargs):
            raise RuntimeError("Something broke")

        with (
            patch("sys.argv", ["mdtohtml", str(md_file)]),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", side_effect=_raise),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "another"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


# ═══════════════════════════════════════════════════════════════════════
# File mode — single input
# ═══════════════════════════════════════════════════════════════════════


class TestFileModeSimple:
    def test_single_to_html_file(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        out = tmp_path / "out.html"
        _run_cli([str(md_file), "-o", str(out)], tmp_path)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == _FAKE_HTML

    def test_creates_parent_directory(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        out = tmp_path / "nested" / "deep" / "out.html"
        _run_cli([str(md_file), "-o", str(out)], tmp_path)
        assert out.exists()

    def test_stderr_log_message(
        self,
        md_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = tmp_path / "out.html"
        _run_cli([str(md_file), "-o", str(out)], tmp_path)
        captured = capsys.readouterr()
        assert "doc.md" in captured.err
        assert str(out) in captured.err


# ═══════════════════════════════════════════════════════════════════════
# File mode — multiple inputs with a single-file output is an error
# ═══════════════════════════════════════════════════════════════════════


class TestFileModeMultiInputError:
    def test_multi_inputs_with_file_output_errors(
        self,
        md_files: list[Path],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Multiple inputs with -o FILE.html exits 1 with a clean error."""
        out = tmp_path / "book.html"
        args = [str(f) for f in md_files] + ["-o", str(out)]
        code = _run_cli_exit(args, tmp_path)
        assert code == 1
        err = capsys.readouterr().err
        assert "Error:" in err
        assert "directory output" in err
        assert "Traceback" not in err
        assert not out.exists()


# ═══════════════════════════════════════════════════════════════════════
# Directory mode
# ═══════════════════════════════════════════════════════════════════════


class TestDirectoryMode:
    def test_individual_files_output(
        self,
        md_files: list[Path],
        tmp_path: Path,
    ) -> None:
        outdir = tmp_path / "out"
        args = [str(f) for f in md_files] + ["-o", str(outdir)]
        _run_cli(args, tmp_path)
        for f in md_files:
            assert (outdir / f"{f.stem}.html").exists()

    def test_single_file_to_dir(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        outdir = tmp_path / "out"
        _run_cli([str(md_file), "-o", str(outdir)], tmp_path)
        assert (outdir / "doc.html").exists()

    def test_creates_output_directory(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        outdir = tmp_path / "new" / "nested"
        _run_cli([str(md_file), "-o", str(outdir)], tmp_path)
        assert outdir.is_dir()
        assert (outdir / "doc.html").exists()

    def test_individual_conversion_error(
        self,
        md_files: list[Path],
        tmp_path: Path,
    ) -> None:
        outdir = tmp_path / "out"
        call_count = 0

        def _fail_second(md_text, theme, themes_dir, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Conversion failed")
            return _mock_convert(md_text, theme, themes_dir, **kwargs)

        args = [str(f) for f in md_files] + ["-o", str(outdir)]
        with (
            patch("sys.argv", ["mdtohtml", *args]),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", side_effect=_fail_second),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "another"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_stderr_log_format(
        self,
        md_files: list[Path],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        outdir = tmp_path / "out"
        args = [str(f) for f in md_files] + ["-o", str(outdir)]
        _run_cli(args, tmp_path)
        captured = capsys.readouterr()
        assert "Theme:" in captured.err
        assert "Output:" in captured.err
        assert "Done." in captured.err
        for f in md_files:
            assert f.name in captured.err


# ═══════════════════════════════════════════════════════════════════════
# Theme flag
# ═══════════════════════════════════════════════════════════════════════


class TestThemeFlag:
    def test_custom_theme_passed(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        """--theme value is forwarded to convert()."""
        out = tmp_path / "out.html"
        mock_conv = MagicMock(return_value=_FAKE_HTML)
        with (
            patch(
                "sys.argv",
                ["mdtohtml", str(md_file), "-o", str(out), "--theme", "test-theme"],
            ),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", mock_conv),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "another"]),
        ):
            main()
        mock_conv.assert_called_once()
        assert mock_conv.call_args[0][1] == "test-theme"

    def test_default_theme(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        """Default theme is 'default'."""
        out = tmp_path / "out.html"
        mock_conv = MagicMock(return_value=_FAKE_HTML)
        with (
            patch("sys.argv", ["mdtohtml", str(md_file), "-o", str(out)]),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", mock_conv),
            patch("mdtohtml.cli.list_themes", return_value=["print", "default"]),
        ):
            main()
        mock_conv.assert_called_once()
        assert mock_conv.call_args[0][1] == "default"

    def test_unknown_theme_error(
        self,
        md_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unrecognised --theme is a clean argparse error listing choices."""
        out = tmp_path / "out.html"
        code = _run_cli_exit(
            [str(md_file), "-o", str(out), "--theme", "does-not-exist"],
            tmp_path,
        )
        assert code == 2
        captured = capsys.readouterr()
        assert "does-not-exist" in captured.err
        assert "test-theme" in captured.err


# ═══════════════════════════════════════════════════════════════════════
# Missing/empty themes directory (bare-exe scenario)
# ═══════════════════════════════════════════════════════════════════════


class TestMissingThemesDir:
    def test_empty_themes_dir_clean_error(
        self,
        md_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An existing but empty themes dir fails cleanly, not with a traceback."""
        empty_themes = tmp_path / "themes"
        empty_themes.mkdir()
        with (
            patch("sys.argv", ["mdtohtml", str(md_file)]),
            patch("mdtohtml.cli.default_themes_dir", return_value=empty_themes),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No themes found" in captured.err
        assert "themes-dir" in captured.err

    def test_missing_themes_dir_clean_error(
        self,
        md_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A themes dir that does not exist at all also fails cleanly."""
        missing_themes = tmp_path / "does-not-exist"
        with (
            patch("sys.argv", ["mdtohtml", str(md_file)]),
            patch("mdtohtml.cli.default_themes_dir", return_value=missing_themes),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No themes found" in captured.err


# ═══════════════════════════════════════════════════════════════════════
# --ignore flag
# ═══════════════════════════════════════════════════════════════════════


class TestIgnoreFlag:
    def test_ignore_passed_to_convert(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        """--ignore is parsed and passed as ignore_callouts to convert()."""
        out = tmp_path / "out.html"
        mock_conv = MagicMock(return_value=_FAKE_HTML)
        with (
            patch(
                "sys.argv",
                ["mdtohtml", str(md_file), "-o", str(out), "--ignore", "info,tip"],
            ),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", mock_conv),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "default"]),
        ):
            main()
        mock_conv.assert_called_once()
        assert mock_conv.call_args[1]["ignore_callouts"] == {"info", "tip"}

    def test_ignore_not_set_by_default(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        """Without --ignore, ignore_callouts is None."""
        out = tmp_path / "out.html"
        mock_conv = MagicMock(return_value=_FAKE_HTML)
        with (
            patch("sys.argv", ["mdtohtml", str(md_file), "-o", str(out)]),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", mock_conv),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "default"]),
        ):
            main()
        mock_conv.assert_called_once()
        assert mock_conv.call_args[1]["ignore_callouts"] is None


# ═══════════════════════════════════════════════════════════════════════
# --toc flag
# ═══════════════════════════════════════════════════════════════════════


class TestTocFlag:
    def test_toc_passed_to_convert(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        """--toc is passed as toc=True to convert()."""
        out = tmp_path / "out.html"
        mock_conv = MagicMock(return_value=_FAKE_HTML)
        with (
            patch("sys.argv", ["mdtohtml", str(md_file), "-o", str(out), "--toc"]),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", mock_conv),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "default"]),
        ):
            main()
        mock_conv.assert_called_once()
        assert mock_conv.call_args[1]["toc"] is True

    def test_toc_not_set_by_default(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        """Without --toc, toc=False is passed to convert()."""
        out = tmp_path / "out.html"
        mock_conv = MagicMock(return_value=_FAKE_HTML)
        with (
            patch("sys.argv", ["mdtohtml", str(md_file), "-o", str(out)]),
            patch("mdtohtml.cli.default_themes_dir", return_value=tmp_path),
            patch("mdtohtml.cli.convert", mock_conv),
            patch("mdtohtml.cli.list_themes", return_value=["test-theme", "default"]),
        ):
            main()
        mock_conv.assert_called_once()
        assert mock_conv.call_args[1]["toc"] is False


# ═══════════════════════════════════════════════════════════════════════
# --themes-dir flag
# ═══════════════════════════════════════════════════════════════════════


class TestThemesDirFlag:
    def test_themes_dir_override_lists_custom_theme(
        self,
        tmp_path: Path,
    ) -> None:
        """--themes-dir points --theme choices at a custom directory."""
        custom_dir = tmp_path / "custom-themes"
        custom_dir.mkdir()
        (custom_dir / "mytheme.css").write_text("body { color: blue; }\n", encoding="utf-8")

        from mdtohtml.cli import build_parser, list_themes

        assert list_themes(custom_dir) == ["mytheme"]

        parser = build_parser(custom_dir)
        assert "mytheme" in parser._option_string_actions["--theme"].choices

    def test_themes_dir_override_used_for_conversion(
        self,
        md_file: Path,
        tmp_path: Path,
    ) -> None:
        """A real --themes-dir flag (not the default) reaches convert()."""
        custom_dir = tmp_path / "custom-themes"
        custom_dir.mkdir()
        (custom_dir / "mytheme.css").write_text("body { color: blue; }\n", encoding="utf-8")

        out = tmp_path / "out.html"
        mock_conv = MagicMock(return_value=_FAKE_HTML)
        with (
            patch(
                "sys.argv",
                [
                    "mdtohtml",
                    str(md_file),
                    "-o",
                    str(out),
                    "--theme",
                    "mytheme",
                    "--themes-dir",
                    str(custom_dir),
                ],
            ),
            patch("mdtohtml.cli.convert", mock_conv),
        ):
            main()
        mock_conv.assert_called_once()
        assert mock_conv.call_args[0][1] == "mytheme"
        assert mock_conv.call_args[0][2] == custom_dir


# ═══════════════════════════════════════════════════════════════════════
# default_themes_dir() — non-frozen behaviour
# ═══════════════════════════════════════════════════════════════════════


from mdtohtml.converter import THEMES_DIR


def _run_cli_real(args: list[str]) -> None:
    """Run ``main()`` against the REAL converter and shipped themes."""
    with patch("sys.argv", ["mdtohtml", *args, "--themes-dir", str(THEMES_DIR)]):
        main()


def _run_cli_real_exit(args: list[str]) -> int:
    with pytest.raises(SystemExit) as exc_info:
        _run_cli_real(args)
    return exc_info.value.code


# ═══════════════════════════════════════════════════════════════════════
# Output-path conflicts (L3)
# ═══════════════════════════════════════════════════════════════════════


class TestOutputPathConflicts:
    def test_l3_existing_dir_as_html_file_target(
        self,
        md_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`-o existingdir.html` where that path is a directory: clean error."""
        clash = tmp_path / "out.html"
        clash.mkdir()
        code = _run_cli_exit([str(md_file), "-o", str(clash)], tmp_path)
        assert code == 1
        err = capsys.readouterr().err
        assert "Error:" in err
        assert "Traceback" not in err

    def test_l3_existing_file_as_dir_target(
        self,
        md_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`-o existingplainfile` (existing file, no suffix): clean error."""
        clash = tmp_path / "outfile"
        clash.write_text("already here", encoding="utf-8")
        code = _run_cli_exit([str(md_file), "-o", str(clash)], tmp_path)
        assert code == 1
        err = capsys.readouterr().err
        assert "Error:" in err
        assert "Traceback" not in err


# ═══════════════════════════════════════════════════════════════════════
# Batch mode resilience (L4) — real converter
# ═══════════════════════════════════════════════════════════════════════


class TestBatchReal:
    def test_l4_batch_skips_bad_file_and_continues(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A failed (empty) file is skipped with a warning; the good files are
        still written, and the run exits nonzero."""
        good1 = tmp_path / "good.md"
        good1.write_text("# Good One\n\nBody.\n", encoding="utf-8")
        empty = tmp_path / "empty.md"
        empty.write_text("   \n", encoding="utf-8")
        good2 = tmp_path / "good2.md"
        good2.write_text("# Good Two\n\nBody.\n", encoding="utf-8")
        outdir = tmp_path / "out"

        code = _run_cli_real_exit(
            [str(good1), str(empty), str(good2), "-o", str(outdir)],
        )
        assert code == 1
        assert (outdir / "good.html").exists()
        assert (outdir / "good2.html").exists()
        assert not (outdir / "empty.html").exists()
        err = capsys.readouterr().err
        assert "empty.md" in err
        assert "WARNING" in err


class TestDefaultThemesDir:
    def test_non_frozen_returns_shipped_themes_dir(self) -> None:
        """Without a frozen executable, the shipped package themes dir is used."""
        result = default_themes_dir()
        assert result == THEMES_DIR
        assert result.is_dir()
        names = {p.stem for p in result.glob("*.css")}
        assert {"default", "dark", "print"} <= names

    def test_frozen_returns_exe_sibling_unconditionally(
        self, tmp_path: Path,
    ) -> None:
        """A frozen run always resolves to <exe dir>/themes, even if absent.

        No theme CSS is bundled inside the frozen binary, so there is no
        fallback to a bundled copy: the exe-sibling path is returned
        whether or not it currently exists.
        """
        fake_exe = tmp_path / "mdtohtml"
        fake_exe.write_text("", encoding="utf-8")
        with (
            patch("sys.frozen", True, create=True),
            patch("sys.executable", str(fake_exe)),
        ):
            result = default_themes_dir()
        assert result == tmp_path / "themes"
        assert not result.exists()
