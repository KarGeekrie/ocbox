"""PodmanClient's podman argv, checked without running podman."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ocbox.podman_client import PodmanClient, PodmanError


@patch("ocbox.podman_client.subprocess.run")
def test_build_keeps_the_layer_cache_by_default(mock_run) -> None:
    PodmanClient().build("FROM scratch\n", "t:latest", context_dir="/ctx")
    argv = mock_run.call_args.args[0]
    assert "--no-cache" not in argv
    assert argv[-1] == "/ctx"


@patch("ocbox.podman_client.subprocess.run")
def test_build_no_cache_passes_the_flag_before_the_context(mock_run) -> None:
    PodmanClient().build("FROM scratch\n", "t:latest", context_dir="/ctx", no_cache=True)
    argv = mock_run.call_args.args[0]
    assert "--no-cache" in argv
    assert argv[-1] == "/ctx"


@patch("ocbox.podman_client.subprocess.run")
def test_build_without_network(mock_run) -> None:
    PodmanClient().build("FROM scratch\n", "t:latest", network=False)
    argv = mock_run.call_args.args[0]
    assert argv[argv.index("--network") + 1] == "none"


@patch("ocbox.podman_client.subprocess.run")
def test_list_containers_builds_ps_json_argv(mock_run) -> None:
    mock_run.return_value = MagicMock(stdout="[]", returncode=0)
    PodmanClient().list_containers()
    argv = mock_run.call_args.args[0]
    assert argv == ["podman", "ps", "--format", "json"]


@patch("ocbox.podman_client.subprocess.run")
def test_list_containers_adds_a_label_filter(mock_run) -> None:
    mock_run.return_value = MagicMock(stdout="[]", returncode=0)
    PodmanClient().list_containers(label="ocbox.managed")
    argv = mock_run.call_args.args[0]
    assert "--filter" in argv
    assert argv[argv.index("--filter") + 1] == "label=ocbox.managed"


@patch("ocbox.podman_client.subprocess.run")
def test_list_containers_parses_json_stdout(mock_run) -> None:
    mock_run.return_value = MagicMock(
        stdout='[{"Names": ["ocbox-foo"], "Labels": {"ocbox.slug": "foo"}}]', returncode=0
    )
    result = PodmanClient().list_containers()
    assert result == [{"Names": ["ocbox-foo"], "Labels": {"ocbox.slug": "foo"}}]


@patch("ocbox.podman_client.subprocess.run")
def test_list_containers_empty_stdout_is_an_empty_list(mock_run) -> None:
    mock_run.return_value = MagicMock(stdout="", returncode=0)
    assert PodmanClient().list_containers() == []


@patch("ocbox.podman_client.subprocess.run")
def test_list_containers_raises_podman_error_on_failure(mock_run) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(1, ["podman", "ps"], stderr="boom")
    with pytest.raises(PodmanError, match="boom"):
        PodmanClient().list_containers()


@patch("ocbox.podman_client.subprocess.run")
def test_list_containers_raises_podman_error_on_unparseable_json(mock_run) -> None:
    mock_run.return_value = MagicMock(stdout="not json", returncode=0)
    with pytest.raises(PodmanError, match="could not parse"):
        PodmanClient().list_containers()


@patch("ocbox.podman_client.subprocess.run")
def test_container_exists_true_on_zero_exit(mock_run) -> None:
    mock_run.return_value = MagicMock(returncode=0)
    assert PodmanClient().container_exists("ocbox-foo") is True


@patch("ocbox.podman_client.subprocess.run")
def test_container_exists_false_on_nonzero_exit(mock_run) -> None:
    mock_run.return_value = MagicMock(returncode=1)
    assert PodmanClient().container_exists("ocbox-foo") is False
