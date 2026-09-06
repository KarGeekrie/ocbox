"""Builds `podman run` invocations and orchestrates one end-to-end `ocbox` run."""

from __future__ import annotations

import json
import signal
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from ocbox import auth, image, network, project
from ocbox.config import Config
from ocbox.packages import prompt_extra_packages
from ocbox.podman_client import PodmanClient
from ocbox.state import ProjectState

OPENCODE_CONFIG_MOUNT = "/etc/ocbox/opencode.json"
AGENTS_JSON_MOUNT = "/etc/ocbox/agents.json"
SKILLS_DIR_MOUNT = "/etc/ocbox/skills"


@dataclass
class RunPlan:
    image_tag: str
    workspace: Path
    run_dir: Path
    env_file: Path
    opencode_config: Path
    agents_json: Path
    skills_dir: Path
    data_volume: str
    container_name: str
    container_web_port: int
    container_llm_port: int
    memory_limit: str | None = None
    pids_limit: int | None = None


def build_podman_run_argv(plan: RunPlan) -> list[str]:
    argv = [
        "run",
        "--rm",
        "--name",
        plan.container_name,
        "--network",
        "none",
        "--userns",
        "keep-id",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--init",
        "-v",
        f"{plan.workspace}:/workspace:rw",
        "-v",
        f"{plan.run_dir}:/run/ocbox:rw",
        "-v",
        f"{plan.opencode_config}:{OPENCODE_CONFIG_MOUNT}:ro",
        "-v",
        f"{plan.agents_json}:{AGENTS_JSON_MOUNT}:ro",
        "-v",
        f"{plan.skills_dir}:{SKILLS_DIR_MOUNT}:ro",
        "-v",
        f"{plan.data_volume}:/home/ocbox:rw",
        "--env-file",
        str(plan.env_file),
        "-e",
        f"OCBOX_CONTAINER_LLM_PORT={plan.container_llm_port}",
        "-e",
        f"OCBOX_CONTAINER_WEB_PORT={plan.container_web_port}",
        "-e",
        f"OPENCODE_CONFIG={OPENCODE_CONFIG_MOUNT}",
        "-e",
        "HOME=/home/ocbox",
        "-e",
        "XDG_CONFIG_HOME=/home/ocbox/.config",
        "-e",
        "XDG_DATA_HOME=/home/ocbox/.local/share",
        "-e",
        "XDG_STATE_HOME=/home/ocbox/.local/state",
    ]
    if plan.memory_limit:
        argv += ["--memory", plan.memory_limit]
    if plan.pids_limit:
        argv += ["--pids-limit", str(plan.pids_limit)]
    argv.append(plan.image_tag)
    return argv


def launch(plan: RunPlan, podman: PodmanClient):
    return podman.popen(build_podman_run_argv(plan))


def _generate_opencode_config(container_llm_port: int, agents_path: Path) -> dict:
    """Builds the single opencode.json ocbox mounts into every sandbox.

    Field names for the local-LLM provider and the agents/skills passthrough
    are ocbox's best guess at OpenCode's config schema - verify against
    OpenCode's real docs before relying on this (see the project plan's open
    questions #1 and #7).
    """
    cfg: dict = {
        "provider": {
            "local": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": f"http://127.0.0.1:{container_llm_port}/v1"},
            }
        },
    }
    if agents_path.exists():
        agents_data = json.loads(agents_path.read_text())
        for key in ("agents", "skills"):
            if key in agents_data:
                cfg[key] = agents_data[key]
    return cfg


def run(
    cfg: Config,
    cwd: Path,
    *,
    non_interactive: bool = False,
    rebuild: bool = False,
    cli_apt: list[str] | None = None,
    cli_uv: list[str] | None = None,
    agents_json: Path | None = None,
    skills_dir: Path | None = None,
    host_web_port: int | None = None,
    open_browser: bool = True,
) -> int:
    podman = PodmanClient()
    slug = project.project_slug(cwd)
    run_dir = project.runtime_dir(slug)
    st_dir = project.state_dir(slug)
    state = ProjectState.load(st_dir)

    image.ensure_base_image(podman, cfg.base_image)

    apt_pkgs, uv_pkgs = prompt_extra_packages(
        cfg, non_interactive=non_interactive, cli_apt=cli_apt, cli_uv=cli_uv
    )
    fingerprint = image.packages_fingerprint(apt_pkgs, uv_pkgs)
    project_tag = f"ocbox/project-{slug}:latest"

    needs_build = (
        rebuild
        or state.packages_fingerprint != fingerprint
        or not image.image_exists(podman, project_tag)
    )
    if needs_build:
        build_context = st_dir / "build-context"
        build_context.mkdir(exist_ok=True)
        image.build_project_image(
            podman, cfg.base_image, project_tag, apt_pkgs, uv_pkgs, build_context
        )
        state.packages_fingerprint = fingerprint
        state.image_tag = project_tag
        state.save(st_dir)

    token = auth.generate_token()
    env_file = run_dir / "env"
    auth.write_env_file(env_file, token)

    container_llm_port = 8081
    container_web_port = cfg.container_web_port
    resolved_agents_json = agents_json or (image.data_dir() / "agents.json")
    resolved_skills_dir = skills_dir or (image.data_dir() / "skills")

    opencode_config_path = run_dir / "opencode.json"
    opencode_config_path.write_text(
        json.dumps(_generate_opencode_config(container_llm_port, resolved_agents_json), indent=2)
    )

    resolved_host_web_port = host_web_port or cfg.host_web_port or network.pick_free_port()
    container_name = f"ocbox-{slug}"
    data_volume = f"ocbox-home-{slug}"

    plan = RunPlan(
        image_tag=project_tag,
        workspace=cwd,
        run_dir=run_dir,
        env_file=env_file,
        opencode_config=opencode_config_path,
        agents_json=resolved_agents_json,
        skills_dir=resolved_skills_dir,
        data_volume=data_volume,
        container_name=container_name,
        container_web_port=container_web_port,
        container_llm_port=container_llm_port,
        memory_limit=cfg.memory_limit,
        pids_limit=cfg.pids_limit,
    )

    llm_relay = network.start_llm_relay(run_dir, cfg.llm_host, cfg.llm_port)
    bridges = network.NetworkBridges(llm_relay=llm_relay, llm_sock=run_dir / "llm.sock")

    container_proc = launch(plan, podman)

    def _on_sigint(signum, frame) -> None:  # noqa: ANN001 - signal handler signature
        podman.stop(container_name)

    old_handler = signal.signal(signal.SIGINT, _on_sigint)
    try:
        try:
            network.wait_for_unix_socket(run_dir / "web.sock", timeout=60)
        except network.NetworkError:
            print(
                f"ocbox: sandbox never became ready; check `podman logs {container_name}`",
                file=sys.stderr,
            )
            container_proc.terminate()
            return 1

        web_relay = network.start_web_relay(run_dir, resolved_host_web_port)
        bridges.web_relay = web_relay
        bridges.web_sock = run_dir / "web.sock"

        url = auth.build_web_url(resolved_host_web_port)
        print(auth.format_connect_banner(url, auth.DEFAULT_USERNAME, token))
        if open_browser:
            webbrowser.open(url)

        return container_proc.wait()
    finally:
        signal.signal(signal.SIGINT, old_handler)
        network.teardown_bridges(bridges)
