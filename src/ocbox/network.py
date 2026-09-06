"""Host-side orchestration of the TCP<->UNIX relay processes that bridge a
`--network=none` container to exactly two things: the configured local LLM
(egress) and the host browser (ingress for OpenCode's web UI). See relay.py
for the actual proxying logic - this module just starts/stops it as
subprocesses and waits for sockets to come up.
"""

from __future__ import annotations

import contextlib
import importlib.resources
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class NetworkError(Exception):
    """Raised when a relay fails to start or a socket never comes up."""


@dataclass
class NetworkBridges:
    llm_relay: subprocess.Popen
    llm_sock: Path
    web_relay: subprocess.Popen | None = None
    web_sock: Path | None = None
    run_dir: Path | None = None  # when set, teardown removes it entirely


def relay_script_path() -> Path:
    return Path(str(importlib.resources.files("ocbox.data") / "relay.py"))


def start_relay(*args: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(relay_script_path()), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def start_llm_relay(run_dir: Path, llm_host: str, llm_port: int) -> subprocess.Popen:
    """Starts the host-side relay dialing out to the user's local LLM.

    Must be started before `podman run` so the socket exists by the time the
    container's entrypoint tries to connect to it.
    """
    sock_path = run_dir / "llm.sock"
    if sock_path.exists():
        sock_path.unlink()
    return start_relay("serve-unix", str(sock_path), "--connect-tcp", f"{llm_host}:{llm_port}")


def start_web_relay(run_dir: Path, host_web_port: int) -> subprocess.Popen:
    """Starts the host-side relay that exposes the container's web UI on localhost.

    Call only after wait_for_unix_socket() confirms the container side is up.
    """
    sock_path = run_dir / "web.sock"
    return start_relay(
        "serve-tcp", f"127.0.0.1:{host_web_port}", "--connect-unix", str(sock_path)
    )


def wait_for_unix_socket(path: Path, timeout: float = 20.0, poll_interval: float = 0.2) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.connect(str(path))
                return
            except OSError:
                pass
        time.sleep(poll_interval)
    raise NetworkError(f"Timed out after {timeout}s waiting for socket {path} to come up")


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def teardown_bridges(bridges: NetworkBridges) -> None:
    for proc in (bridges.llm_relay, bridges.web_relay):
        if proc is None:
            continue
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)

    if bridges.run_dir is not None:
        # Removes the socket files along with the auth-token env file and
        # generated opencode.json that live alongside them - nothing from
        # this run should linger on disk once it's torn down.
        shutil.rmtree(bridges.run_dir, ignore_errors=True)
        return

    for sock_path in (bridges.llm_sock, bridges.web_sock):
        if sock_path is not None:
            with contextlib.suppress(FileNotFoundError):
                sock_path.unlink()
