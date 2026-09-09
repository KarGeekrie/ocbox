"""Builds `podman run` invocations and orchestrates one end-to-end `ocbox` run."""

from __future__ import annotations

import json
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ocbox import auth, image, network, project
from ocbox.config import Config
from ocbox.packages import prompt_extra_packages
from ocbox.podman_client import PodmanClient
from ocbox.state import ProjectState

OPENCODE_CONFIG_MOUNT = "/etc/ocbox/opencode.json"
# OpenCode discovers global agents at $XDG_CONFIG_HOME/opencode/agents/<name>.md.
# Unlike skills - which have a `skills.paths` config key - there is no way to
# point OpenCode at an arbitrary agent folder, so the mount location itself is
# what makes these load. Nests inside the /home/ocbox volume, which podman
# handles as long as the volume is mounted first (see build_podman_run_argv).
# Singular `agent/` is accepted too, but the docs name the plural, so use it.
AGENTS_DIR_MOUNT = "/home/ocbox/.config/opencode/agents"
# The user's own OpenCode settings, mounted as OpenCode's *global* config.
# Global sits below OPENCODE_CONFIG in OpenCode's precedence order, so ocbox's
# generated config still wins on the provider endpoint while everything the
# user puts here - crucially the model list, without which nothing is
# selectable - is merged in. Deep-merged, not replaced: user `models` and
# ocbox's `options.baseURL` end up in the same provider block.
USER_CONFIG_MOUNT = "/home/ocbox/.config/opencode/opencode.jsonc"
# Same story as agents: mounted at OpenCode's documented global skills
# location rather than registered through the `skills.paths` config key.
# Both work, but one mechanism for both beats two, and it leaves the
# generated config holding only the thing ocbox actually owns - the relay
# endpoint. Also nests inside /home/ocbox, so it mounts after the volume.
SKILLS_DIR_MOUNT = "/home/ocbox/.config/opencode/skills"


@dataclass
class RunPlan:
    image_tag: str
    workspace: Path
    run_dir: Path
    opencode_config: Path
    agents_dir: Path
    skills_dir: Path
    user_config: Path
    data_volume: str
    container_name: str
    container_web_port: int
    container_llm_port: int
    mode: str = "web"  # "web" or "tui"
    env_file: Path | None = None  # web-only: gates the forwarded UI, unused for tui
    memory_limit: str | None = None
    pids_limit: int | None = None
    # OpenCode's own arguments, forwarded verbatim from `ocbox ... -- <args>`.
    opencode_args: list[str] = field(default_factory=list)

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
        f"{plan.data_volume}:/home/ocbox:rw",
        # Must follow the /home/ocbox volume above: they mount inside it.
        "-v",
        f"{plan.agents_dir}:{AGENTS_DIR_MOUNT}:ro",
        "-v",
        f"{plan.skills_dir}:{SKILLS_DIR_MOUNT}:ro",
        "-v",
        f"{plan.user_config}:{USER_CONFIG_MOUNT}:ro",
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
    # Anything after the image tag is CMD, which entrypoint.sh receives as "$@"
    # and forwards to opencode itself.
    argv += plan.opencode_args
    return argv


def launch(plan: RunPlan, podman: PodmanClient):
    return podman.popen(build_podman_run_argv(plan))


def daemonize(log_path: Path) -> int:
    """Forks so the rest of run() - relay bridges included - keeps going in the
    background, detached from the controlling terminal (like `nohup ... &`).

    The relay processes that bridge the sandboxed container to the network are
    plain subprocesses of ocbox itself, not the container; only backgrounding
    ocbox's own process, not just the container, keeps them alive once the
    terminal goes away. Returns the child's pid to the parent, which should
    stop right there, and 0 to the child, which continues run() with stdio
    redirected to `log_path`.
    """
    pid = os.fork()
    if pid > 0:
        return pid
    os.setsid()
    devnull_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull_fd, 0)
    os.close(devnull_fd)
    log_fd = os.open(str(log_path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)
    return 0


USER_CONFIG_PATH = Path.home() / ".config" / "ocbox" / "opencode.jsonc"


# ocbox sets these itself: the web UI is reached through a relay bound to a
# port ocbox chose, so a second --port/--hostname on the same command line
# either conflicts or silently detaches OpenCode from the bridge.
RESERVED_OPENCODE_FLAGS = ("--port", "--hostname")


class OpencodeArgsError(ValueError):
    """Raised when forwarded OpenCode args would break the sandbox."""


def check_opencode_args(args: list[str], mode: str = "tui") -> None:
    """Validates OpenCode passthrough args (`ocbox ... -- <args>`).

    Web mode appends them to `opencode serve`, which - unlike the TUI - does
    not understand most of OpenCode's own CLI flags (`--agent`, `--continue`,
    `run`, ...): it just hangs until ocbox's own readiness timeout fires, a
    confusing failure with nothing pointing at the real cause. Rather than
    special-case which flags happen to be serve-safe, passthrough is TUI-only;
    web mode rejects any of it upfront.
    """
    if not args:
        return
    if mode == "web":
        raise OpencodeArgsError(
            "arguments after -- aren't supported in web mode - they'd be "
            "appended to `opencode serve`, which doesn't understand most of "
            "OpenCode's own CLI and fails with a confusing timeout instead of "
            "an error. Use --tui -- ... instead."
        )
    for arg in args:
        flag = arg.split("=", 1)[0]
        if flag in RESERVED_OPENCODE_FLAGS:
            raise OpencodeArgsError(
                f"{flag} is set by ocbox and can't be forwarded - it would detach "
                "OpenCode from the relay that exposes it. Use --web-port to choose "
                "the port you connect to on the host."
            )


def _resolve_user_config() -> Path:
    """The user's own OpenCode settings, or the packaged empty default.

    Kept next to conf.py in ~/.config/ocbox/ because what belongs here - the
    list of models your LLM server serves - is a property of that server, the
    same thing LLM_HOST/LLM_PORT describe.
    """
    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH
    return image.data_dir() / "opencode.jsonc"


def _generate_opencode_config(container_llm_port: int) -> dict:
    """Builds the single opencode.json ocbox mounts into every sandbox.

    Only the provider is generated, because it is the only part ocbox owns:
    the baseURL points at the relay bridging the container to the user's LLM.
    Agents and skills aren't here - they're files mounted at the locations
    OpenCode already searches - and the models belong to the user's own
    opencode.jsonc, mounted as OpenCode's global config.

    Key names verified against OpenCode's published schema
    (https://opencode.ai/config.json, checked at opencode 1.18.29). Getting one
    wrong fails silently rather than loudly: the schema declares
    additionalProperties=false, but the runtime just drops what it doesn't
    recognise. Earlier guesses at `skillsDir` and a list-valued `agents` did
    exactly that, leaving mounted skills and agents invisible with nothing in
    the output to say so - so re-check any change here against
    `opencode debug config`, which prints what actually survived.
    """
    return {
        "provider": {
            "local": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": f"http://127.0.0.1:{container_llm_port}/v1"},
            }
        }
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
    user_config: Path | None = None,
    opencode_args: list[str] | None = None,
    host_web_port: int | None = None,
    detach: bool = False,
) -> int:
    if detach and mode != "web":
        raise ValueError("detach only applies to mode='web' - there's nothing to attach it to")

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
    resolved_user_config = user_config or _resolve_user_config()

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
        user_config=resolved_user_config,
        opencode_args=list(opencode_args or []),
        skills_dir=resolved_skills_dir,
        data_volume=data_volume,
        container_name=container_name,
        container_web_port=container_web_port,
        container_llm_port=container_llm_port,
        mode=mode,
        memory_limit=cfg.memory_limit,
        pids_limit=cfg.pids_limit,
    )

    if detach:
        log_path = run_dir / "ocbox.log"
        child_pid = daemonize(log_path)
        if child_pid:
            print(
                f"ocbox: detached (pid {child_pid}), container {container_name}\n"
                f"  progress/URL: tail -f {log_path}\n"
                f"  status:       podman ps --filter name={container_name}\n"
                f"  stop:         podman stop {container_name}"
            )
            return 0

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
