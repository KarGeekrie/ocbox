"""Real end-to-end test against actual Podman.

Skipped unless Podman is installed AND RUN_PODMAN_INTEGRATION=1 is set -
it builds a real image and runs a real rootless container, too slow/heavy
for the default unit test run.

Uses a stand-in for the OpenCode binary (fixtures/fake_opencode.py) rather
than the real one, since opencode.ai and astral.sh may not be reachable from
the machine running this test - see fake_opencode.py's docstring. This test
still drives the real, unmodified ocbox.sandbox / ocbox.network code and the
real relay.py / entrypoint.sh against real rootless Podman, so it proves the
sandboxing mechanism itself (network isolation, the relay bridge, auth,
filesystem ownership) even though it doesn't exercise OpenCode's actual CLI.
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ocbox import network
from ocbox.image import data_dir
from ocbox.podman_client import PodmanClient
from ocbox.sandbox import RunPlan, build_podman_run_argv

pytestmark = pytest.mark.skipif(
    shutil.which("podman") is None or os.environ.get("RUN_PODMAN_INTEGRATION") != "1",
    reason="requires podman installed and RUN_PODMAN_INTEGRATION=1",
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
IMAGE_TAG = "ocbox-integration-test:latest"


class _StubLLMHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # untyped args: stdlib signature
        pass

    def do_GET(self) -> None:  # non-PEP8 name: stdlib handler method
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"stub": "llm-response"}')


@pytest.fixture
def stub_llm():
    server = http.server.HTTPServer(("127.0.0.1", 0), _StubLLMHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def test_image_tag() -> str:
    podman = PodmanClient()
    with tempfile.TemporaryDirectory() as build_ctx:
        build_ctx_path = Path(build_ctx)
        shutil.copy(data_dir() / "relay.py", build_ctx_path / "relay.py")
        shutil.copy(data_dir() / "entrypoint.sh", build_ctx_path / "entrypoint.sh")
        shutil.copy(FIXTURES_DIR / "fake_opencode.py", build_ctx_path / "fake_opencode.py")
        shutil.copy(
            FIXTURES_DIR / "fake_opencode_tui.py", build_ctx_path / "fake_opencode_tui.py"
        )
        shutil.copy(FIXTURES_DIR / "opencode", build_ctx_path / "opencode")
        containerfile_text = (FIXTURES_DIR / "Containerfile.test").read_text()
        # This test image needs no network at build time (no apt/curl steps),
        # and some rootless Podman setups can't set up build-time networking
        # at all (e.g. no rootless access to /dev/net/tun for slirp4netns) -
        # network=False sidesteps that entirely rather than requiring it.
        podman.build(containerfile_text, IMAGE_TAG, context_dir=str(build_ctx_path), network=False)
    return IMAGE_TAG


def _get(url: str, token: str | None = None, timeout: float = 5) -> tuple[int, bytes]:
    headers = {}
    if token is not None:
        creds = base64.b64encode(f"opencode:{token}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_full_sandbox_roundtrip(tmp_path: Path, stub_llm: int, test_image_tag: str) -> None:
    podman = PodmanClient()
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    token = "integration-test-token"
    env_file = run_dir / "env"
    env_file.write_text(
        f"OPENCODE_SERVER_USERNAME=opencode\nOPENCODE_SERVER_PASSWORD={token}\n"
    )
    empty_json = run_dir / "empty.json"
    empty_json.write_text("{}")
    empty_dir = run_dir / "empty_dir"
    empty_dir.mkdir()

    container_llm_port = 8081
    container_web_port = 4096
    host_web_port = network.pick_free_port()

    plan = RunPlan(
        image_tag=test_image_tag,
        workspace=workspace,
        run_dir=run_dir,
        env_file=env_file,
        opencode_config=empty_json,
        agents_json=empty_json,
        skills_dir=empty_dir,
        data_volume="ocbox-integration-test-home",
        container_name="ocbox-integration-test",
        container_web_port=container_web_port,
        container_llm_port=container_llm_port,
    )

    llm_relay = network.start_llm_relay(run_dir, "127.0.0.1", stub_llm)
    bridges = network.NetworkBridges(llm_relay=llm_relay, llm_sock=run_dir / "llm.sock")

    container_proc = podman.popen(
        build_podman_run_argv(plan), stdout=None, stderr=None
    )
    try:
        network.wait_for_unix_socket(run_dir / "web.sock", timeout=30)
        web_relay = network.start_web_relay(run_dir, host_web_port)
        bridges.web_relay = web_relay
        bridges.web_sock = run_dir / "web.sock"

        base_url = f"http://127.0.0.1:{host_web_port}"

        # Give the web relay a moment to bind before the first real request.
        time.sleep(0.3)

        # 1. No/wrong credentials -> 401 (the auth wiring is real, not a stub).
        status, _ = _get(base_url + "/")
        assert status == 401
        status, _ = _get(base_url + "/", token="wrong-token")
        assert status == 401

        # 2. Correct credentials -> the fake OpenCode's fixed response, proving
        #    the full web-ingress relay chain (browser -> host relay -> Unix
        #    socket -> container relay -> opencode's own loopback port) works.
        status, body = _get(base_url + "/", token=token)
        assert status == 200
        assert body == b"ocbox-fake-opencode-ok"

        # 3. The LLM-egress relay chain actually reaches the stub LLM, from
        #    *inside* the network=none container, through nothing but the
        #    Unix-socket bridge.
        status, body = _get(base_url + "/llm-check", token=token)
        assert status == 200
        assert json.loads(body) == {"stub": "llm-response"}
    finally:
        podman.stop(plan.container_name)
        container_proc.wait(timeout=15)
        network.teardown_bridges(bridges)


def test_network_none_blocks_arbitrary_egress(test_image_tag: str) -> None:
    """Proves --network=none isolation is real, not just "we didn't publish a
    port": a container from the same image can't reach an arbitrary external
    address at all, even though it's otherwise a normal running process.
    """
    podman = PodmanClient()
    result = podman.run_capture(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python3",
            test_image_tag,
            "-c",
            (
                "import socket, sys\n"
                "s = socket.socket()\n"
                "s.settimeout(3)\n"
                "try:\n"
                "    s.connect(('1.1.1.1', 80))\n"
                "    print('CONNECTED')\n"
                "except OSError as exc:\n"
                "    print('BLOCKED:', exc)\n"
            ),
        ]
    )
    assert "BLOCKED" in result.stdout
    assert "CONNECTED" not in result.stdout


def test_userns_keep_id_preserves_host_ownership(tmp_path: Path, test_image_tag: str) -> None:
    """Proves --userns=keep-id: a file written by the container process in
    /workspace lands on the host owned by the invoking (non-root) user, not
    some arbitrary/root UID.
    """
    podman = PodmanClient()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    podman.run_capture(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--userns",
            "keep-id",
            "-v",
            f"{workspace}:/workspace:rw",
            "--entrypoint",
            "python3",
            test_image_tag,
            "-c",
            "open('/workspace/written-by-container.txt', 'w').write('hello host\\n')",
        ]
    )

    written = workspace / "written-by-container.txt"
    assert written.read_text() == "hello host\n"
    assert written.stat().st_uid == os.getuid()


def test_tui_mode_runs_real_entrypoint_and_reaches_llm(
    tmp_path: Path, stub_llm: int, test_image_tag: str
) -> None:
    """Drives the real entrypoint.sh's OCBOX_MODE=tui branch (exec opencode,
    no web relay/auth) through real Podman. Runs without `-it` so the test
    harness doesn't need a real pty - build_podman_run_argv's `-it` handling
    for a genuine interactive run is covered separately by the mocked
    argv-construction unit tests (test_sandbox.py).
    """
    podman = PodmanClient()
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    empty_json = run_dir / "empty.json"
    empty_json.write_text("{}")
    empty_dir = run_dir / "empty_dir"
    empty_dir.mkdir()

    plan = RunPlan(
        image_tag=test_image_tag,
        workspace=workspace,
        run_dir=run_dir,
        env_file=None,
        opencode_config=empty_json,
        agents_json=empty_json,
        skills_dir=empty_dir,
        data_volume="ocbox-integration-test-home-tui",
        container_name="ocbox-integration-test-tui",
        container_web_port=4096,
        container_llm_port=8081,
        mode="tui",
    )

    llm_relay = network.start_llm_relay(run_dir, "127.0.0.1", stub_llm)
    bridges = network.NetworkBridges(llm_relay=llm_relay, llm_sock=run_dir / "llm.sock")
    try:
        network.wait_for_unix_socket(run_dir / "llm.sock", timeout=5)
        argv = build_podman_run_argv(plan)
        assert "-it" in argv  # real invocation would attach a tty
        argv_without_tty = [a for a in argv if a != "-it"]
        result = podman.run_capture(argv_without_tty)
    finally:
        network.teardown_bridges(bridges)

    assert "OCBOX-FAKE-TUI-STARTED" in result.stdout
    assert 'LLM-CHECK: {"stub": "llm-response"}' in result.stdout
