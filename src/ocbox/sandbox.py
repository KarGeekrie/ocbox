"""Builds `podman run` invocations and orchestrates one end-to-end `ocbox` run."""

from __future__ import annotations

import json
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from ocbox import auth, image, network, project
from ocbox.config import Config
from ocbox.packages import prompt_extra_packages
from ocbox.podman_client import PodmanClient
from ocbox.state import ProjectState

OPENCODE_CONFIG_MOUNT = "/etc/ocbox/opencode.json"
# OpenCode discovers global agents at $XDG_CONFIG_HOME/opencode/agent/<name>.md.
# Unlike skills - which have a `skills.paths` config key - there is no way to
# point OpenCode at an arbitrary agent folder, so the mount location itself is
# what makes these load. Nests inside the /home/ocbox volume, which podman
# handles as long as the volume is mounted first (see build_podman_run_argv).
AGENTS_DIR_MOUNT = "/home/ocbox/.config/opencode/agent"
SKILLS_DIR_MOUNT = "/etc/ocbox/skills"


@dataclass
class RunPlan:
    image_tag: str
    workspace: Path
    run_dir: Path
    opencode_config: Path
    agents_dir: Path
    skills_dir: Path
    data_volume: str
    container_name: str
    container_web_port: int
    container_llm_port: int
    mode: str = "web"  # "web" or "tui"
    env_file: Path | None = None  # web-only: gates the forwarded UI, unused for tui
    memory_limit: str | None = None
    pids_limit: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("web", "tui"):
            raise ValueError(f"RunPlan.mode must be 'web' or 'tui', got {self.mode!r}")
        if self.mode == "web" and self.env_file is None:
            raise ValueError(
                "RunPlan.env_file is required when mode='web' - it carries the "
                "auth token that gates the forwarded web UI; without it the "
                "container would run opencode web with no credentials set."
            )


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
    ]
    if plan.mode == "tui":
        argv.append("-it")
    argv += [
        "-v",
        f"{plan.workspace}:/workspace:rw",
        "-v",
        f"{plan.run_dir}:/run/ocbox:rw",
        "-v",
        f"{plan.opencode_config}:{OPENCODE_CONFIG_MOUNT}:ro",
        "-v",
        f"{plan.skills_dir}:{SKILLS_DIR_MOUNT}:ro",
        "-v",
        f"{plan.data_volume}:/home/ocbox:rw",
        # Must follow the /home/ocbox volume above: it mounts inside it.
        "-v",
        f"{plan.agents_dir}:{AGENTS_DIR_MOUNT}:ro",
    ]
    if plan.env_file is not None:
        argv += ["--env-file", str(plan.env_file)]
    argv += [
        "-e",
        f"OCBOX_MODE={plan.mode}",
        "-e",
        f"OCBOX_CONTAINER_LLM_PORT={plan.container_llm_port}",
    ]
    if plan.mode == "web":
        argv += ["-e", f"OCBOX_CONTAINER_WEB_PORT={plan.container_web_port}"]
    argv += [
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


def _generate_opencode_config(container_llm_port: int) -> dict:
    """Builds the single opencode.json ocbox mounts into every sandbox.

    Key names are verified against OpenCode's published schema
    (https://opencode.ai/config.json, checked at opencode 1.18.29): `provider`
    keyed by provider name, and `skills.paths` for extra skill folders.

    Agents deliberately aren't here: they're `<name>.md` files bind-mounted at
    AGENTS_DIR_MOUNT, because OpenCode has no config key pointing at an agent
    folder the way `skills.paths` does for skills.

    Getting a name wrong here fails silently rather than loudly: the schema
    declares additionalProperties=false, but the runtime just drops what it
    doesn't recognise. Earlier guesses at `skillsDir` and a list-valued
    `agents` did exactly that, leaving the mounted skills/agents invisible to
    OpenCode with nothing in the output to say so - so re-check any change
    here against `opencode debug config`, which prints what actually survived.
    """
    return {
        "provider": {
            "local": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": f"http://127.0.0.1:{container_llm_port}/v1"},
            }
        },
        "skills": {"paths": [SKILLS_DIR_MOUNT]},
    }


def run(
    cfg: Config,
    cwd: Path,
    *,
    mode: str = "web",
    non_interactive: bool = False,
    rebuild: bool = False,
    cli_apt: list[str] | None = None,
    cli_uv: list[str] | None = None,
    agents_dir: Path | None = None,
    skills_dir: Path | None = None,
    host_web_port: int | None = None,
) -> int:
    podman = PodmanClient()
    slug = project.project_slug(cwd)
    run_dir = project.runtime_dir(slug)
    st_dir = project.state_dir(slug)
    state = ProjectState.load(st_dir)

    image.ensure_base_image(podman, cfg.base_image, cfg.base_os)

    apt_pkgs, uv_pkgs = prompt_extra_packages(
        cfg, non_interactive=non_interactive, cli_apt=cli_apt, cli_uv=cli_uv
    )
    fingerprint = image.packages_fingerprint(
        apt_pkgs, uv_pkgs, cfg.base_image, image.containerfile_fingerprint(cfg.base_os)
    )
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
            podman, cfg.base_image, project_tag, apt_pkgs, uv_pkgs, build_context, cfg.base_os
        )
        state.packages_fingerprint = fingerprint
        state.image_tag = project_tag
        state.save(st_dir)

    token: str | None = None
    env_file: Path | None = None
    if mode == "web":
        token = auth.generate_token()
        env_file = run_dir / "env"
        auth.write_env_file(env_file, token)

    container_llm_port = 8081
    container_web_port = cfg.container_web_port
    resolved_agents_dir = agents_dir or (image.data_dir() / "agents")
    resolved_skills_dir = skills_dir or (image.data_dir() / "skills")

    opencode_config_path = run_dir / "opencode.json"
    opencode_config_path.write_text(
        json.dumps(_generate_opencode_config(container_llm_port), indent=2)
    )

    container_name = f"ocbox-{slug}"
    data_volume = f"ocbox-home-{slug}"

    plan = RunPlan(
        image_tag=project_tag,
        workspace=cwd,
        run_dir=run_dir,
        env_file=env_file,
        opencode_config=opencode_config_path,
        agents_dir=resolved_agents_dir,
        skills_dir=resolved_skills_dir,
        data_volume=data_volume,
        container_name=container_name,
        container_web_port=container_web_port,
        container_llm_port=container_llm_port,
        mode=mode,
        memory_limit=cfg.memory_limit,
        pids_limit=cfg.pids_limit,
    )

    llm_relay = network.start_llm_relay(run_dir, cfg.llm_host, cfg.llm_port)
    bridges = network.NetworkBridges(
        llm_relay=llm_relay, llm_sock=run_dir / "llm.sock", run_dir=run_dir
    )

    container_proc = launch(plan, podman)

    def _on_sigint(signum, frame) -> None:  # untyped args: signal handler signature
        podman.stop(container_name)

    if mode == "tui":
        # No custom handler here: with -it, the terminal already delivers
        # Ctrl-C straight to the container's foreground process (OpenCode's
        # own TUI), which should decide how to handle it (e.g. cancel an
        # in-flight action) rather than have ocbox force-stop the whole
        # sandbox out from under it.
        print(f"ocbox: launching OpenCode's TUI in {cwd}\n")
        try:
            try:
                return container_proc.wait()
            except KeyboardInterrupt:
                return container_proc.wait()
        finally:
            network.teardown_bridges(bridges)

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

        resolved_host_web_port = host_web_port or cfg.host_web_port or network.pick_free_port()
        web_relay = network.start_web_relay(run_dir, resolved_host_web_port)
        bridges.web_relay = web_relay
        bridges.web_sock = run_dir / "web.sock"

        url = auth.build_web_url(resolved_host_web_port)
        print(auth.format_connect_banner(url, auth.DEFAULT_USERNAME, token))

        return container_proc.wait()
    finally:
        signal.signal(signal.SIGINT, old_handler)
        network.teardown_bridges(bridges)
