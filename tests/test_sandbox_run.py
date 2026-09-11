"""Tests sandbox.run()'s own orchestration/wiring - as opposed to
test_sandbox.py, which only tests build_podman_run_argv() against
hand-built RunPlan objects. This covers the thing a RunPlan-only test can't:
that run() actually wires mode -> (auth generation, SIGINT handling,
pick_free_port) correctly, so a regression that hoists that logic out of
its `if mode == "web"` guard gets caught.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ocbox import sandbox
from ocbox.config import Config


def _cfg(**overrides) -> Config:
    return Config(**overrides)


@pytest.fixture
def mocked_run_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "agents").mkdir()
    (data_dir / "opencode.jsonc").write_text(
        '{\n  // the team LLM\n  "provider": {"local": {"options": '
        '{"baseURL": "http://10.1.2.3:4567/v1"}}},\n}\n'
    )
    (data_dir / "environments").mkdir()
    (data_dir / "environments" / "sandbox.md").write_text("# Environment: sandbox\n")
    (data_dir / "environments" / "no-sandbox.md").write_text("# Environment: your machine\n")
    (data_dir / "AGENTS.md").write_text("# Team rules\n")
    (data_dir / "skills").mkdir()

    with (
        patch("ocbox.sandbox.PodmanClient") as mock_podman_cls,
        patch("ocbox.sandbox.image") as mock_image,
        patch("ocbox.sandbox.auth") as mock_auth,
        patch("ocbox.sandbox.network") as mock_network,
        patch("ocbox.sandbox.prompt_extra_packages", return_value=([], [])),
        patch("ocbox.sandbox.launch") as mock_launch,
    ):
        mock_image.repo_config_dir.return_value = data_dir
        mock_image.packages_fingerprint.return_value = "fp"
        mock_image.containerfile_fingerprint.return_value = "basefp"
        mock_image.image_exists.return_value = True

        mock_auth.generate_token.return_value = "test-token"
        mock_auth.DEFAULT_USERNAME = "opencode"
        mock_auth.build_web_url.return_value = "http://127.0.0.1:1"
        mock_auth.format_connect_banner.return_value = "banner"

        mock_network.pick_free_port.return_value = 5555
        mock_network.start_llm_relay.return_value = MagicMock()

        container_proc = MagicMock()
        container_proc.wait.return_value = 0
        mock_launch.return_value = container_proc

        yield {
            "podman_cls": mock_podman_cls,
            "image": mock_image,
            "auth": mock_auth,
            "network": mock_network,
            "launch": mock_launch,
            "container_proc": container_proc,
        }


def test_run_forwards_extra_mounts_to_the_plan(tmp_path, mocked_run_env) -> None:
    extra = tmp_path / "other-repo"
    extra.mkdir()

    sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True, extra_mounts=[extra])

    plan = mocked_run_env["launch"].call_args[0][0]
    assert plan.extra_mounts == [extra]


def test_run_defaults_to_no_extra_mounts(tmp_path, mocked_run_env) -> None:
    sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)

    plan = mocked_run_env["launch"].call_args[0][0]
    assert plan.extra_mounts == []


def test_run_web_mode_generates_auth_and_passes_env_file(tmp_path, mocked_run_env) -> None:
    exit_code = sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)

    assert exit_code == 0
    mocked_run_env["auth"].generate_token.assert_called_once()
    mocked_run_env["auth"].write_env_file.assert_called_once()
    plan = mocked_run_env["launch"].call_args[0][0]
    assert plan.mode == "web"
    assert plan.env_file is not None


def test_run_tui_mode_skips_auth_and_env_file(tmp_path, mocked_run_env) -> None:
    exit_code = sandbox.run(_cfg(), tmp_path, mode="tui", non_interactive=True)

    assert exit_code == 0
    mocked_run_env["auth"].generate_token.assert_not_called()
    mocked_run_env["auth"].write_env_file.assert_not_called()
    plan = mocked_run_env["launch"].call_args[0][0]
    assert plan.mode == "tui"
    assert plan.env_file is None


def test_run_tui_mode_does_not_call_pick_free_port(tmp_path, mocked_run_env) -> None:
    sandbox.run(_cfg(), tmp_path, mode="tui", non_interactive=True)
    mocked_run_env["network"].pick_free_port.assert_not_called()


def test_run_web_mode_calls_pick_free_port_when_no_port_configured(
    tmp_path, mocked_run_env
) -> None:
    sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)
    mocked_run_env["network"].pick_free_port.assert_called_once()


def test_run_tui_mode_keyboard_interrupt_does_not_force_stop(tmp_path, mocked_run_env) -> None:
    """Regression test for the SIGINT-in---tui fix: a Ctrl-C delivered while
    waiting on the -it-attached container must not trigger podman stop -
    the container already got the raw signal directly via the terminal.
    """
    container_proc = mocked_run_env["container_proc"]
    container_proc.wait.side_effect = [KeyboardInterrupt(), 0]

    exit_code = sandbox.run(_cfg(), tmp_path, mode="tui", non_interactive=True)

    assert exit_code == 0
    assert container_proc.wait.call_count == 2
    podman_instance = mocked_run_env["podman_cls"].return_value
    podman_instance.stop.assert_not_called()


def test_run_web_mode_stops_container_on_wait_for_socket_failure(
    tmp_path, mocked_run_env
) -> None:
    mocked_run_env["network"].NetworkError = RuntimeError  # needs a real exception type
    mocked_run_env["network"].wait_for_unix_socket.side_effect = RuntimeError("timed out")

    exit_code = sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)

    assert exit_code == 1
    mocked_run_env["container_proc"].terminate.assert_called_once()


def test_run_detach_with_tui_mode_rejected(tmp_path, mocked_run_env) -> None:
    with pytest.raises(ValueError, match="detach only applies to mode='web'"):
        sandbox.run(_cfg(), tmp_path, mode="tui", non_interactive=True, detach=True)


def test_run_web_mode_detach_parent_returns_without_touching_the_sandbox(
    tmp_path, mocked_run_env
) -> None:
    """The parent branch (daemonize() returning a real child pid) must print
    and exit before starting any relay or container - that work belongs to
    the detached child, not the process the caller's shell is waiting on."""
    with patch("ocbox.sandbox.daemonize", return_value=4242) as mock_daemonize:
        exit_code = sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True, detach=True)

    assert exit_code == 0
    mock_daemonize.assert_called_once()
    mocked_run_env["network"].start_llm_relay.assert_not_called()
    mocked_run_env["launch"].assert_not_called()


def test_run_web_mode_detach_child_continues_the_normal_flow(tmp_path, mocked_run_env) -> None:
    """daemonize() returning 0 (the child branch) must fall through to the
    same relay/launch sequence a non-detached run takes."""
    with patch("ocbox.sandbox.daemonize", return_value=0) as mock_daemonize:
        exit_code = sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True, detach=True)

    assert exit_code == 0
    mock_daemonize.assert_called_once()
    mocked_run_env["network"].start_llm_relay.assert_called_once()
    mocked_run_env["launch"].assert_called_once()


def test_run_relays_to_the_llm_named_in_opencode_jsonc(tmp_path, mocked_run_env) -> None:
    sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)

    args = mocked_run_env["network"].start_llm_relay.call_args.args
    assert args[1:] == ("10.1.2.3", 4567)


def test_run_points_opencode_at_the_relay_keeping_the_base_url_path(
    tmp_path, mocked_run_env
) -> None:
    sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)

    plan = mocked_run_env["launch"].call_args[0][0]
    generated = json.loads(plan.opencode_config.read_text())
    expected = f"http://127.0.0.1:{plan.container_llm_port}/v1"
    assert generated["provider"]["local"]["options"]["baseURL"] == expected


def test_run_fails_before_any_image_work_without_a_usable_base_url(
    tmp_path, mocked_run_env
) -> None:
    data_dir = mocked_run_env["image"].repo_config_dir.return_value
    (data_dir / "opencode.jsonc").write_text("{}")

    with pytest.raises(sandbox.LlmEndpointError):
        sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)
    mocked_run_env["image"].ensure_base_image.assert_not_called()


def test_run_mounts_a_sandbox_agents_md_listing_what_is_installed(
    tmp_path, mocked_run_env
) -> None:
    with patch("ocbox.sandbox.prompt_extra_packages", return_value=(["git"], ["py-spy"])):
        sandbox.run(_cfg(), tmp_path, mode="web", non_interactive=True)

    plan = mocked_run_env["launch"].call_args[0][0]
    text = plan.global_agents_md.read_text()
    assert text.index("# Environment: sandbox") < text.index("py-spy") < text.index("# Team rules")
    assert "Extra system packages: git." in text
    assert "Network: none" in text
    assert "# Environment: your machine" not in text
