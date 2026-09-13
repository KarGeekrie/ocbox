"""PodmanClient's podman argv, checked without running podman."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ocbox.podman_client import QUERY_TIMEOUT, PodmanClient, PodmanError


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


@patch("ocbox.podman_client.sys.stdin.isatty", return_value=True)
@patch("ocbox.podman_client.subprocess.call", return_value=0)
def test_exec_interactive_allocates_a_tty_when_there_is_one(mock_call, mock_isatty) -> None:
    assert PodmanClient().exec_interactive("ocbox-x", ["sh"]) == 0
    assert mock_call.call_args.args[0] == ["podman", "exec", "-it", "ocbox-x", "sh"]


@patch("ocbox.podman_client.sys.stdin.isatty", return_value=False)
@patch("ocbox.podman_client.subprocess.call", return_value=0)
def test_exec_interactive_skips_the_tty_flag_without_one(mock_call, mock_isatty) -> None:
    """podman refuses to allocate a TTY when stdin isn't one, which would turn
    a piped or cron-driven `ocbox exec` into an error instead of a run."""
    PodmanClient().exec_interactive("ocbox-x", ["echo", "hi"])
    assert mock_call.call_args.args[0] == ["podman", "exec", "-i", "ocbox-x", "echo", "hi"]


@patch("ocbox.podman_client.subprocess.call", side_effect=OSError("no such binary"))
def test_exec_interactive_reports_a_missing_podman_as_podman_error(mock_call) -> None:
    with pytest.raises(PodmanError, match="Could not execute"):
        PodmanClient().exec_interactive("ocbox-x", ["sh"])


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


# ---- a podman that stops answering ------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.image_exists("t"),
        lambda c: c.image_label("t", "l"),
        lambda c: c.container_exists("c"),
        lambda c: c.list_containers(),
    ],
)
@patch(
    "ocbox.podman_client.subprocess.run",
    side_effect=subprocess.TimeoutExpired(["podman"], QUERY_TIMEOUT),
)
def test_a_query_that_hangs_raises_podman_error(mock_run, call) -> None:
    with pytest.raises(PodmanError, match="did not answer"):
        call(PodmanClient())


@patch("ocbox.podman_client.subprocess.run")
def test_queries_are_bounded(mock_run) -> None:
    mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    client = PodmanClient()
    client.image_exists("t")
    client.container_exists("c")
    client.list_containers()
    assert [call.kwargs["timeout"] for call in mock_run.call_args_list] == [QUERY_TIMEOUT] * 3


@patch(
    "ocbox.podman_client.subprocess.run",
    side_effect=subprocess.TimeoutExpired(["podman", "stop"], 70),
)
def test_a_stop_that_hangs_returns_for_the_caller_to_check(mock_run) -> None:
    PodmanClient().stop("c")


@patch("ocbox.podman_client.subprocess.run")
def test_builds_are_not_bounded(mock_run) -> None:
    """A --no-cache base image build takes minutes."""
    PodmanClient().build("FROM scratch\n", "t:latest")
    assert "timeout" not in mock_run.call_args.kwargs

