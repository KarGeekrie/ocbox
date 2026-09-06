import socket
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ocbox import network


def _fake_proc() -> MagicMock:
    proc = MagicMock()
    proc.wait.return_value = 0
    return proc


def test_teardown_with_run_dir_removes_everything(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "llm.sock").write_text("")
    (run_dir / "web.sock").write_text("")
    (run_dir / "env").write_text("OPENCODE_SERVER_PASSWORD=secret\n")
    (run_dir / "opencode.json").write_text("{}")

    bridges = network.NetworkBridges(
        llm_relay=_fake_proc(),
        llm_sock=run_dir / "llm.sock",
        web_relay=_fake_proc(),
        web_sock=run_dir / "web.sock",
        run_dir=run_dir,
    )
    network.teardown_bridges(bridges)

    assert not run_dir.exists()


def test_teardown_without_run_dir_only_removes_sockets(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "llm.sock").write_text("")
    (run_dir / "other-file.txt").write_text("keep me")

    bridges = network.NetworkBridges(
        llm_relay=_fake_proc(),
        llm_sock=run_dir / "llm.sock",
        run_dir=None,
    )
    network.teardown_bridges(bridges)

    assert not (run_dir / "llm.sock").exists()
    assert (run_dir / "other-file.txt").exists()


def test_teardown_terminates_relay_processes() -> None:
    llm_relay = _fake_proc()
    web_relay = _fake_proc()
    bridges = network.NetworkBridges(llm_relay=llm_relay, llm_sock=Path("/nonexistent"))
    bridges.web_relay = web_relay

    network.teardown_bridges(bridges)

    llm_relay.terminate.assert_called_once()
    web_relay.terminate.assert_called_once()


def test_teardown_kills_relay_if_terminate_times_out() -> None:
    import subprocess

    llm_relay = _fake_proc()
    llm_relay.wait.side_effect = [subprocess.TimeoutExpired("relay.py", 5), 0]
    bridges = network.NetworkBridges(llm_relay=llm_relay, llm_sock=Path("/nonexistent"))

    network.teardown_bridges(bridges)

    llm_relay.kill.assert_called_once()


def test_pick_free_port_returns_a_bindable_port() -> None:
    port = network.pick_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # would raise if not actually free


def test_wait_for_unix_socket_times_out(tmp_path: Path) -> None:
    with pytest.raises(network.NetworkError, match="Timed out"):
        network.wait_for_unix_socket(tmp_path / "never-created.sock", timeout=0.3, poll_interval=0.1)


def test_wait_for_unix_socket_succeeds_once_listening(tmp_path: Path) -> None:
    sock_path = tmp_path / "test.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    try:
        start = time.monotonic()
        network.wait_for_unix_socket(sock_path, timeout=5, poll_interval=0.05)
        assert time.monotonic() - start < 5
    finally:
        server.close()
