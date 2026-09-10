from unittest.mock import patch

import pytest

from ocbox import cli
from ocbox.cli import build_parser, main
from ocbox.config import ConfigError
from ocbox.podman_client import PodmanError
from ocbox.preflight import PreflightError
from ocbox.sandbox import NoSandboxError


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.tui is False
    assert args.yes is False
    assert args.apt is None
    assert args.uv is None
    assert args.web_port is None


def test_parser_tui_flag() -> None:
    args = build_parser().parse_args(["--tui"])
    assert args.tui is True


def test_parser_apt_and_uv_are_independent() -> None:
    args = build_parser().parse_args(["--uv", "black"])
    assert args.apt is None
    assert args.uv == ["black"]


@patch("ocbox.cli.run_preflight", side_effect=PreflightError("podman missing"))
def test_main_reports_preflight_error_cleanly(mock_preflight, capsys) -> None:
    exit_code = main([])
    assert exit_code == 1
    assert "ocbox: podman missing" in capsys.readouterr().err


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config", side_effect=ConfigError("no LLM_HOST"))
def test_main_reports_config_error_cleanly(mock_config, mock_preflight, capsys) -> None:
    exit_code = main([])
    assert exit_code == 1
    assert "ocbox: no LLM_HOST" in capsys.readouterr().err


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", side_effect=PodmanError("podman build failed for tag x"))
def test_main_reports_podman_error_cleanly_instead_of_traceback(
    mock_run, mock_config, mock_preflight, capsys
) -> None:
    exit_code = main([])
    assert exit_code == 1
    assert "ocbox: podman build failed for tag x" in capsys.readouterr().err


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", return_value=0)
def test_main_passes_tui_mode_through(mock_run, mock_config, mock_preflight) -> None:
    main(["--tui"])
    assert mock_run.call_args.kwargs["mode"] == "tui"


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", return_value=0)
def test_main_defaults_to_web_mode(mock_run, mock_config, mock_preflight) -> None:
    main([])
    assert mock_run.call_args.kwargs["mode"] == "web"


def test_split_opencode_args_without_separator() -> None:
    assert cli.split_opencode_args(["--tui", "--yes"]) == (["--tui", "--yes"], [])


def test_split_opencode_args_forwards_the_tail() -> None:
    ocbox_argv, opencode_args = cli.split_opencode_args(
        ["--tui", "--", "--model", "local/qwen", "--agent", "chat"]
    )
    assert ocbox_argv == ["--tui"]
    assert opencode_args == ["--model", "local/qwen", "--agent", "chat"]


def test_split_opencode_args_keeps_later_separators_for_opencode() -> None:
    """Only the first `--` is ocbox's; `opencode run -- ...` must survive."""
    _, opencode_args = cli.split_opencode_args(["--", "run", "--", "hello"])
    assert opencode_args == ["run", "--", "hello"]


@patch("ocbox.cli.run_preflight")
def test_main_rejects_opencode_args_without_tui(mock_preflight, capsys) -> None:
    exit_code = main(["--", "--print-logs"])
    assert exit_code == 1
    assert "--tui" in capsys.readouterr().err


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", return_value=0)
def test_main_allows_opencode_args_with_tui(mock_run, mock_config, mock_preflight) -> None:
    exit_code = main(["--tui", "--", "--agent", "chat"])
    assert exit_code == 0
    assert mock_run.call_args.kwargs["opencode_args"] == ["--agent", "chat"]


def test_main_rejects_detach_with_tui(capsys) -> None:
    exit_code = main(["--tui", "--detach"])
    assert exit_code == 1
    assert "--detach" in capsys.readouterr().err


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", return_value=0)
def test_main_passes_detach_through(mock_run, mock_config, mock_preflight) -> None:
    main(["--detach"])
    assert mock_run.call_args.kwargs["detach"] is True


@patch("ocbox.cli.update_check.check_for_update", return_value="v9.9.9")
@patch("ocbox.cli.run_preflight", side_effect=PreflightError("podman missing"))
def test_main_prints_a_notice_when_a_newer_release_exists(
    mock_preflight, mock_check, capsys
) -> None:
    main([])
    assert "v9.9.9" in capsys.readouterr().err


@patch("ocbox.cli.update_check.check_for_update", return_value=None)
@patch("ocbox.cli.run_preflight", side_effect=PreflightError("podman missing"))
def test_main_prints_nothing_when_up_to_date(mock_preflight, mock_check, capsys) -> None:
    main([])
    assert "newer version" not in capsys.readouterr().err


@patch("ocbox.cli.run_no_sandbox", return_value=0)
def test_main_no_sandbox_skips_podman_preflight(mock_run_no_sandbox) -> None:
    with patch("ocbox.cli.run_preflight") as mock_preflight:
        exit_code = main(["--no-sandbox"])
    assert exit_code == 0
    mock_preflight.assert_not_called()
    mock_run_no_sandbox.assert_called_once()


@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run_no_sandbox", return_value=0)
def test_main_no_sandbox_never_loads_conf_py(mock_run_no_sandbox, mock_load_config) -> None:
    """--no-sandbox needs no LLM_HOST/LLM_PORT - there's no relay to dial, so
    it must not require a conf.py at all, unlike the sandboxed modes."""
    exit_code = main(["--no-sandbox"])
    assert exit_code == 0
    mock_load_config.assert_not_called()


@patch("ocbox.cli.run_no_sandbox", return_value=0)
def test_main_no_sandbox_forwards_opencode_args(mock_run_no_sandbox) -> None:
    main(["--no-sandbox", "--", "run", "hello"])
    assert mock_run_no_sandbox.call_args.kwargs["opencode_args"] == ["run", "hello"]


@patch("ocbox.cli.run_no_sandbox", return_value=0)
def test_main_no_sandbox_forwards_instructions_dir(mock_run_no_sandbox) -> None:
    main(["--no-sandbox", "--instructions-dir", "/tmp/my-instructions"])
    assert str(mock_run_no_sandbox.call_args.kwargs["instructions_dir"]) == "/tmp/my-instructions"


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", return_value=0)
def test_main_forwards_instructions_dir(mock_run, mock_config, mock_preflight) -> None:
    main(["--instructions-dir", "/tmp/my-instructions"])
    assert str(mock_run.call_args.kwargs["instructions_dir"]) == "/tmp/my-instructions"


@pytest.mark.parametrize(
    "flag",
    [
        "--tui",
        "--detach",
        "--web-port=1234",
        "--rebuild",
        "--apt",
        "--uv",
        "--yes",
        "--config=x",
        "--mount=/tmp",
    ],
)
def test_main_rejects_no_sandbox_combined_with_sandbox_only_flags(flag, capsys) -> None:
    exit_code = main(["--no-sandbox", flag])
    assert exit_code == 1
    assert "--no-sandbox" in capsys.readouterr().err


@patch("ocbox.cli.run_no_sandbox", side_effect=NoSandboxError("~/.config/opencode/agents exists"))
def test_main_reports_no_sandbox_error_cleanly(mock_run_no_sandbox, capsys) -> None:
    exit_code = main(["--no-sandbox"])
    assert exit_code == 1
    assert "ocbox: ~/.config/opencode/agents exists" in capsys.readouterr().err


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", return_value=0)
def test_main_forwards_extra_mounts(mock_run, mock_config, mock_preflight, tmp_path) -> None:
    extra = tmp_path / "other-repo"
    extra.mkdir()
    main(["--mount", str(extra)])
    assert mock_run.call_args.kwargs["extra_mounts"] == [extra.resolve()]


@patch("ocbox.cli.run_preflight")
@patch("ocbox.cli.load_config")
@patch("ocbox.cli.run", return_value=0)
def test_main_supports_multiple_mount_flags(
    mock_run, mock_config, mock_preflight, tmp_path
) -> None:
    a = tmp_path / "repo-a"
    b = tmp_path / "repo-b"
    a.mkdir()
    b.mkdir()
    main(["--mount", str(a), "--mount", str(b)])
    assert mock_run.call_args.kwargs["extra_mounts"] == [a.resolve(), b.resolve()]


def test_main_rejects_mount_of_a_nonexistent_directory(tmp_path, capsys) -> None:
    missing = tmp_path / "does-not-exist"
    exit_code = main(["--mount", str(missing)])
    assert exit_code == 1
    assert "not a directory" in capsys.readouterr().err


def test_main_rejects_mount_of_a_file(tmp_path, capsys) -> None:
    a_file = tmp_path / "not-a-dir.txt"
    a_file.write_text("hi")
    exit_code = main(["--mount", str(a_file)])
    assert exit_code == 1
    assert "not a directory" in capsys.readouterr().err


def test_main_rejects_mounts_with_colliding_basenames(tmp_path, capsys) -> None:
    a = tmp_path / "one" / "shared"
    b = tmp_path / "two" / "shared"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    exit_code = main(["--mount", str(a), "--mount", str(b)])
    assert exit_code == 1
    assert "distinct names" in capsys.readouterr().err
