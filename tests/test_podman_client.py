"""PodmanClient's podman argv, checked without running podman."""

from unittest.mock import patch

from ocbox.podman_client import PodmanClient


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
