"""fleet.py's cross-project list/stop/attach/exec, against a fake PodmanClient
and hand-built run_dir files - no real podman needed."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ocbox import auth, fleet, project


@pytest.fixture(autouse=True)
def _isolated_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))


def _entry(name: str, slug: str, mode: str = "web", workdir: str = "/home/user/proj") -> dict:
    return {
        "Names": [name],
        "Labels": {"ocbox.slug": slug, "ocbox.mode": mode, "ocbox.workdir": workdir},
        "Status": "Up 5 minutes",
    }


# ---- list_running --------------------------------------------------------


def test_list_running_parses_labels_into_sandbox_info() -> None:
    podman = MagicMock()
    podman.list_containers.return_value = [_entry("ocbox-foo", "foo")]

    infos = fleet.list_running(podman)

    assert len(infos) == 1
    info = infos[0]
    assert info.container_name == "ocbox-foo"
    assert info.slug == "foo"
    assert info.mode == "web"
    assert info.workdir == "/home/user/proj"
    podman.list_containers.assert_called_once_with(label=fleet.MANAGED_LABEL)


def test_list_running_empty_when_nothing_running() -> None:
    podman = MagicMock()
    podman.list_containers.return_value = []
    assert fleet.list_running(podman) == []


def test_list_running_reads_web_url_from_connect_json() -> None:
    podman = MagicMock()
    podman.list_containers.return_value = [_entry("ocbox-foo", "foo")]
    run_dir = project.runtime_dir("foo")
    (run_dir / "connect.json").write_text(json.dumps({"host_web_port": 9999}))

    infos = fleet.list_running(podman)

    assert infos[0].web_url == "http://127.0.0.1:9999"


def test_list_running_web_url_none_when_connect_json_missing() -> None:
    """tui mode, or a sandbox started before connect.json existed."""
    podman = MagicMock()
    podman.list_containers.return_value = [_entry("ocbox-foo", "foo", mode="tui")]
    assert fleet.list_running(podman)[0].web_url is None


# ---- resolve_target -------------------------------------------------------


def test_resolve_target_passes_through_a_container_name() -> None:
    assert fleet.resolve_target("ocbox-foo-abc123") == "ocbox-foo-abc123"


def test_resolve_target_prefixes_a_bare_slug() -> None:
    assert fleet.resolve_target("foo-abc123") == "ocbox-foo-abc123"


def test_resolve_target_resolves_a_project_path(tmp_path: Path) -> None:
    project_dir = tmp_path / "myproj"
    project_dir.mkdir()
    expected = f"ocbox-{project.project_slug(project_dir)}"
    assert fleet.resolve_target(str(project_dir)) == expected


def test_resolve_target_resolves_dot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    expected = f"ocbox-{project.project_slug(tmp_path)}"
    assert fleet.resolve_target(".") == expected


# ---- stop_sandbox ----------------------------------------------------------


def test_stop_sandbox_reports_missing_target() -> None:
    podman = MagicMock()
    podman.container_exists.return_value = False
    assert fleet.stop_sandbox(podman, "ocbox-foo") == 1
    podman.stop.assert_not_called()


def test_stop_sandbox_stops_and_confirms() -> None:
    podman = MagicMock()
    podman.container_exists.side_effect = [True, False]
    assert fleet.stop_sandbox(podman, "ocbox-foo") == 0
    podman.stop.assert_called_once_with("ocbox-foo")


def test_stop_sandbox_reports_failure_to_stop() -> None:
    podman = MagicMock()
    podman.container_exists.side_effect = [True, True]
    assert fleet.stop_sandbox(podman, "ocbox-foo") == 1


# ---- attach_sandbox ---------------------------------------------------------


def test_attach_sandbox_reports_missing_target() -> None:
    podman = MagicMock()
    podman.container_exists.return_value = False
    assert fleet.attach_sandbox(podman, "ocbox-foo") == 1


def test_attach_sandbox_prints_the_connect_banner() -> None:
    podman = MagicMock()
    podman.container_exists.return_value = True
    run_dir = project.runtime_dir("foo")
    (run_dir / "connect.json").write_text(json.dumps({"host_web_port": 4242}))
    auth.write_env_file(run_dir / "env", "tok123", username="opencode")

    assert fleet.attach_sandbox(podman, "ocbox-foo") == 0


def test_attach_sandbox_graceful_when_connect_info_missing() -> None:
    """tui mode, or a sandbox that predates connect.json/the env file."""
    podman = MagicMock()
    podman.container_exists.return_value = True
    assert fleet.attach_sandbox(podman, "ocbox-foo") == 1


# ---- exec_shell -------------------------------------------------------------


def test_exec_shell_reports_missing_target() -> None:
    podman = MagicMock()
    podman.container_exists.return_value = False
    assert fleet.exec_shell(podman, "ocbox-foo") == 1


def test_exec_shell_defaults_to_sh() -> None:
    """Goes through PodmanClient rather than subprocess directly, so a missing
    podman surfaces as ocbox's own error instead of a traceback."""
    podman = MagicMock()
    podman.container_exists.return_value = True
    podman.exec_interactive.return_value = 0

    assert fleet.exec_shell(podman, "ocbox-foo") == 0
    podman.exec_interactive.assert_called_once_with("ocbox-foo", ["sh"])


def test_exec_shell_uses_a_given_command() -> None:
    podman = MagicMock()
    podman.container_exists.return_value = True

    fleet.exec_shell(podman, "ocbox-foo", ["bash", "-l"])
    podman.exec_interactive.assert_called_once_with("ocbox-foo", ["bash", "-l"])
