from unittest.mock import patch

from ocbox import cli
from ocbox.cli import build_parser, main
from ocbox.config import ConfigError
from ocbox.podman_client import PodmanError
from ocbox.preflight import PreflightError


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
