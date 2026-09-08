from unittest.mock import patch

from ocbox.config import Config
from ocbox.packages import prompt_extra_packages


def _cfg(**overrides) -> Config:
    defaults = {
        "llm_host": "127.0.0.1",
        "llm_port": 1234,
        "extra_apt_default": ["git", "vim"],
        "extra_uv_default": ["ruff"],
    }
    defaults.update(overrides)
    return Config(**defaults)


def test_cli_apt_only_falls_back_to_uv_default() -> None:
    apt, uv = prompt_extra_packages(_cfg(), non_interactive=False, cli_apt=["curl"], cli_uv=None)
    assert apt == ["curl"]
    assert uv == ["ruff"]


def test_cli_uv_only_falls_back_to_apt_default() -> None:
    apt, uv = prompt_extra_packages(_cfg(), non_interactive=False, cli_apt=None, cli_uv=["black"])
    assert apt == ["git", "vim"]
    assert uv == ["black"]


def test_cli_both_override_both_defaults() -> None:
    apt, uv = prompt_extra_packages(
        _cfg(), non_interactive=False, cli_apt=["curl"], cli_uv=["black"]
    )
    assert apt == ["curl"]
    assert uv == ["black"]


def test_cli_apt_empty_list_is_an_explicit_override_not_a_fallback() -> None:
    # Explicitly passing --apt with no packages means "none", not "use default".
    apt, uv = prompt_extra_packages(_cfg(), non_interactive=False, cli_apt=[], cli_uv=None)
    assert apt == []
    assert uv == ["ruff"]


def test_non_interactive_uses_config_defaults() -> None:
    apt, uv = prompt_extra_packages(_cfg(), non_interactive=True)
    assert apt == ["git", "vim"]
    assert uv == ["ruff"]


def test_non_tty_stdin_uses_config_defaults_without_prompting() -> None:
    with patch("sys.stdin.isatty", return_value=False):
        apt, uv = prompt_extra_packages(_cfg(), non_interactive=False)
    assert apt == ["git", "vim"]
    assert uv == ["ruff"]


def test_interactive_prompt_parses_input() -> None:
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", side_effect=["curl wget", "black"]),
    ):
        apt, uv = prompt_extra_packages(_cfg(), non_interactive=False)
    assert apt == ["curl", "wget"]
    assert uv == ["black"]


def test_interactive_prompt_blank_input_uses_defaults() -> None:
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", side_effect=["", ""]),
    ):
        apt, uv = prompt_extra_packages(_cfg(), non_interactive=False)
    assert apt == ["git", "vim"]
    assert uv == ["ruff"]
