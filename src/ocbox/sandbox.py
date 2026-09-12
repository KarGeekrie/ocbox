"""Builds `podman run` invocations and orchestrates one end-to-end `ocbox` run."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from ocbox import auth, image, jsonc, network, project
from ocbox.config import Config, ConfigError
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
# The AGENTS.md ocbox composes for this run, mounted as OpenCode's *global*
# AGENTS.md. OpenCode combines it with the project's own AGENTS.md rather than
# picking one - verified against opencode 1.18.29 by recording the request
# bodies it sends to the LLM: with both files present, both reach the model.
# Nests inside /home/ocbox like the directories above, so it mounts after the
# volume. Optional content: no mount at all when the file doesn't exist.
GLOBAL_AGENTS_MD_MOUNT = "/home/ocbox/.config/opencode/AGENTS.md"
# Root for --mount's extra working directories, one per basename
# (<host-path>:/mnt/<basename>:rw), independent of /workspace and each other -
# unlike agents/skills, nothing here nests inside another mount. Being visible
# isn't enough for OpenCode's tools, which treat these as paths outside the
# project - see the permission entries _generate_opencode_config() adds.
EXTRA_MOUNTS_ROOT = "/mnt"

# The container's podman network mode. "none" is the isolation guarantee, and
# the sandbox AGENTS.md describes the network from this same value, so the agent
# is told what the container actually gets rather than what someone remembered.
SANDBOX_NETWORK = "none"

# The loopback port the LLM-egress relay binds *inside* the container. Fixed
# rather than configurable: OpenCode reaches it as http://127.0.0.1:<port>, and
# entrypoint.sh binds it. It must differ from the container web port (see run()).
CONTAINER_LLM_PORT = 8081


def _write_private(path: Path, text: str) -> None:
    """Writes `text` to `path` at mode 0600, never following a symlink at that
    path.

    The generated per-run files live in the run directory the container shares
    read-write at the same uid (--userns=keep-id), so a compromised sandbox
    could plant a symlink there to redirect a write onto a host file. Unlinking
    first and opening with O_NOFOLLOW|O_EXCL closes that off - same reasoning as
    auth.write_env_file.
    """
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)


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
    # AGENTS.md composed for this run, mounted as OpenCode's global one; None skips.
    global_agents_md: Path | None = None
    # Additional host directories mounted read-write at /mnt/<name.name>,
    # alongside the primary `workspace` at /workspace. See EXTRA_MOUNTS_ROOT.
    extra_mounts: list[Path] = field(default_factory=list)
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
        names = [p.name for p in self.extra_mounts]
        if len(names) != len(set(names)):
            raise ValueError(
                f"extra_mounts have colliding basenames ({names!r}) - each --mount "
                "needs a directory with a distinct name"
            )


def build_podman_run_argv(plan: RunPlan) -> list[str]:
    argv = [
        "run",
        "--rm",
        "--name",
        plan.container_name,
        "--network",
        SANDBOX_NETWORK,
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
    ]
    for extra in plan.extra_mounts:
        argv += ["-v", f"{extra}:{EXTRA_MOUNTS_ROOT}/{extra.name}:rw"]
    argv += [
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
    if plan.global_agents_md is not None:
        argv += ["-v", f"{plan.global_agents_md}:{GLOBAL_AGENTS_MD_MOUNT}:ro"]
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
    log_fd = os.open(
        str(log_path), os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600
    )
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)
    return 0


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
                f"{flag} can't be forwarded - ocbox controls how OpenCode binds "
                "so it stays wired to the relay (in web mode ocbox sets these to "
                "point OpenCode at it). Use --web-port to choose the host port you "
                "connect to."
            )


def _generate_opencode_config(base_url: str, extra_mounts: list[Path] | None = None) -> dict:
    """Builds the single opencode.json ocbox feeds OpenCode, sandboxed or not.

    Only what depends on the run is generated. `base_url` is the relay bridging
    a sandboxed container to the user's LLM, or - in --no-sandbox mode -
    opencode.jsonc's own baseURL, no relay involved. Agents and skills aren't
    here - they're files placed at the locations OpenCode already searches - and
    the models belong to opencode.jsonc, layered in as OpenCode's global config.

    The other run-dependent part is access to --mount's directories. OpenCode
    gates every path outside the project behind `permission.external_directory`,
    and the team's opencode.jsonc denies them all (`"*": "deny"`), so without an
    entry a mounted directory is visible in the container but refused to every
    tool. Verified against opencode 1.18.29 with a stub LLM issuing read, write
    and bash calls on /mnt/<name>: all refused under the team rules, all allowed
    with these entries - which OpenCode merges into the team's rules rather than
    replacing them (`opencode debug config` lists both).

    Key names verified against OpenCode's published schema
    (https://opencode.ai/config.json, checked at opencode 1.18.29). Getting one
    wrong fails silently rather than loudly: the schema declares
    additionalProperties=false, but the runtime just drops what it doesn't
    recognise. Earlier guesses at `skillsDir` and a list-valued `agents` did
    exactly that, leaving mounted skills and agents invisible with nothing in
    the output to say so - so re-check any change here against
    `opencode debug config`, which prints what actually survived.
    """
    config: dict = {
        "provider": {
            "local": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": base_url},
            }
        }
    }
    if extra_mounts:
        config["permission"] = {
            "external_directory": {
                f"{EXTRA_MOUNTS_ROOT}/{path.name}/**": "allow" for path in extra_mounts
            }
        }
    return config


class LlmEndpointError(ConfigError):
    """Raised when opencode.jsonc doesn't name an LLM server ocbox can relay to."""


@dataclass(frozen=True)
class LlmEndpoint:
    host: str
    port: int
    path: str


def llm_endpoint(opencode_jsonc: Path) -> LlmEndpoint:
    """Where the LLM server is, read from provider.local.options.baseURL.

    opencode.jsonc is the one place the team names its LLM: OpenCode reads it
    directly under --no-sandbox, and ocbox reads the same value to know what the
    sandbox's relay has to dial, so the address is never written down twice.
    """
    try:
        node: object = jsonc.loads(opencode_jsonc.read_text())
    except (OSError, jsonc.JsoncError) as exc:
        raise LlmEndpointError(f"Can't read {opencode_jsonc}: {exc}") from exc
    for key in ("provider", "local", "options", "baseURL"):
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, str) or not node.strip():
        raise LlmEndpointError(
            f"{opencode_jsonc} doesn't set provider.local.options.baseURL - set it to "
            "the LLM server, e.g. http://127.0.0.1:11434/v1 for a local Ollama."
        )
    base_url = node.strip()
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme == "https":
        raise LlmEndpointError(
            f"baseURL {base_url!r} is https. A sandbox reaches the LLM through a plain "
            "TCP relay that OpenCode sees at http://127.0.0.1, which no https "
            "certificate can match - use the server's http address, or --no-sandbox."
        )
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "http" or not parts.hostname or port == -1:
        raise LlmEndpointError(
            f"baseURL {base_url!r} in {opencode_jsonc} isn't a usable "
            "http://host[:port]/path address - is it still a placeholder?"
        )
    return LlmEndpoint(parts.hostname, port or 80, parts.path.rstrip("/"))


def _sandbox_facts(
    base_os: str,
    apt_pkgs: list[str],
    uv_pkgs: list[str],
    extra_mounts: list[Path],
    network: str = SANDBOX_NETWORK,
) -> list[str]:
    """What this particular sandbox has - generated, since it varies per run."""
    if network == "none":
        net = (
            "- Network: none. The container has no network device besides loopback; "
            "the only thing it reaches is the LLM serving you, through ocbox's relay. "
            "Package installs, git fetch/push, curl and web lookups fail - say so "
            "rather than retrying."
        )
    else:
        net = f"- Network: available (podman network mode `{network}`)."
    project_dirs = ["`/workspace` (the user's project)"]
    project_dirs += [f"`{EXTRA_MOUNTS_ROOT}/{path.name}`" for path in extra_mounts]
    return [
        "## This sandbox",
        "",
        net,
        f"- Base system: {base_os}, with python3, uv, curl and ripgrep (`rg`).",
        "- Extra system packages: " + (", ".join(apt_pkgs) if apt_pkgs else "none") + ".",
        "- Extra Python packages (uv): " + (", ".join(uv_pkgs) if uv_pkgs else "none") + ".",
        "- Project directories, where changes are real: " + ", ".join(project_dirs) + ".",
        "- `/tmp` is scratch space, and most of the rest of the filesystem is read-only.",
    ]


def _compose_global_agents_md(environment: str, facts: list[str]) -> str | None:
    """The global AGENTS.md for one mode: environment, then facts, then team rules.

    opencode-config/environments/<environment>.md says where the agent runs - a
    sandbox, or the user's own machine - the facts pin down this particular run,
    and opencode-config/AGENTS.md carries the team's rules common to every mode.
    Composed per run rather than shipped as one static file, so an agent is never
    told it is sandboxed when it isn't.
    """
    config_dir = image.repo_config_dir()
    sections: list[str] = []
    environment_file = config_dir / "environments" / f"{environment}.md"
    if environment_file.is_file():
        sections.append(environment_file.read_text().strip())
    if facts:
        sections.append("\n".join(facts).strip())
    team_rules = config_dir / "AGENTS.md"
    if team_rules.is_file():
        sections.append(team_rules.read_text().strip())
    return "\n\n".join(sections) + "\n" if sections else None


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
    extra_mounts: list[Path] | None = None,
) -> int:
    if detach and mode != "web":
        raise ValueError("detach only applies to mode='web' - there's nothing to attach it to")

    # The LLM relay and OpenCode's web server both bind loopback inside the
    # container; equal ports would make one fail to bind. The LLM port is fixed,
    # the web port is configurable, so guard against a conf.py that collides.
    if mode == "web" and cfg.container_web_port == CONTAINER_LLM_PORT:
        raise ConfigError(
            f"CONTAINER_WEB_PORT ({cfg.container_web_port}) collides with the "
            f"container's LLM relay port ({CONTAINER_LLM_PORT}); pick a different "
            "CONTAINER_WEB_PORT in conf.py."
        )

    # Before any image work: fail fast if opencode.jsonc doesn't name a usable LLM.
    llm = llm_endpoint(user_config or (image.repo_config_dir() / "opencode.jsonc"))

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
        apt_pkgs, uv_pkgs, cfg.base_image, image.base_fingerprint(cfg.base_os)
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

    container_llm_port = CONTAINER_LLM_PORT
    relay_url = f"http://127.0.0.1:{container_llm_port}{llm.path}"
    container_web_port = cfg.container_web_port
    resolved_agents_dir = agents_dir or (image.repo_config_dir() / "agents")
    resolved_skills_dir = skills_dir or (image.repo_config_dir() / "skills")
    # Only opencode-config/opencode.jsonc is the user's to touch; --opencode-config
    # exists for a one-off run, and nothing in the home directory overrides it.
    resolved_user_config = user_config or (image.repo_config_dir() / "opencode.jsonc")
    global_agents_md = run_dir / "AGENTS.md"
    agents_md_text = _compose_global_agents_md(
        "sandbox", _sandbox_facts(cfg.base_os, apt_pkgs, uv_pkgs, list(extra_mounts or []))
    )
    if agents_md_text is None:
        global_agents_md.unlink(missing_ok=True)
        resolved_global_agents_md = None
    else:
        _write_private(global_agents_md, agents_md_text)
        resolved_global_agents_md = global_agents_md

    opencode_config_path = run_dir / "opencode.json"
    _write_private(
        opencode_config_path,
        json.dumps(_generate_opencode_config(relay_url, list(extra_mounts or [])), indent=2),
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
        global_agents_md=resolved_global_agents_md,
        opencode_args=list(opencode_args or []),
        skills_dir=resolved_skills_dir,
        data_volume=data_volume,
        container_name=container_name,
        container_web_port=container_web_port,
        container_llm_port=container_llm_port,
        mode=mode,
        memory_limit=cfg.memory_limit,
        pids_limit=cfg.pids_limit,
        extra_mounts=list(extra_mounts or []),
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

    llm_relay = network.start_llm_relay(run_dir, llm.host, llm.port)
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


class NoSandboxError(Exception):
    """Raised when --no-sandbox can't safely set up a bare OpenCode run."""


OPENCODE_INSTALL_URL = "https://opencode.ai/install"


def _find_or_install_opencode() -> str:
    """Locates an OpenCode binary, installing one into the package if none exists.

    An installation the user already has wins: `opencode` on PATH, or the
    standard ~/.opencode/bin. Otherwise ocbox uses - or installs - its own copy
    in the checkout's .ocbox/bin, so nothing is written to the user's home.

    The official installer hardcodes $HOME/.opencode/bin, so it runs with HOME
    pointed at a throwaway directory inside .ocbox/ and the binary is moved out
    of it. --no-modify-path keeps it off shell rc files, even that throwaway
    HOME's.
    """
    found = shutil.which("opencode")
    if found:
        return found
    standard = Path.home() / ".opencode" / "bin" / "opencode"
    if standard.exists():
        return str(standard)
    local_dir = image.repo_local_dir()
    local_bin = local_dir / "bin" / "opencode"
    if local_bin.exists():
        return str(local_bin)

    print(
        f"ocbox: opencode not found - installing it into {local_bin.parent}...",
        file=sys.stderr,
    )
    curl = subprocess.run(
        ["curl", "-fsSL", OPENCODE_INSTALL_URL], capture_output=True, check=True
    )
    local_bin.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=local_dir, prefix="install-") as install_home:
        # The installer assumes bash (`set -euo pipefail` on its own line 2) -
        # piping into plain `sh` breaks wherever that's dash, e.g. Debian/Ubuntu.
        subprocess.run(
            ["bash", "-s", "--", "--no-modify-path"],
            input=curl.stdout,
            check=True,
            env={**os.environ, "HOME": install_home},
        )
        installed = Path(install_home) / ".opencode" / "bin" / "opencode"
        if not installed.exists():
            raise NoSandboxError(
                f"the OpenCode installer ran but didn't produce {installed} - "
                "install OpenCode yourself and re-run."
            )
        shutil.move(str(installed), local_bin)
    return str(local_bin)



def _build_no_sandbox_config_dir(
    agents_dir: Path,
    skills_dir: Path,
    user_config: Path,
    agents_md: str | None = None,
) -> Path:
    """Assembles the config directory OpenCode is pointed at under --no-sandbox.

    OPENCODE_CONFIG_DIR takes a single directory, but --agents-dir/--skills-dir
    can point anywhere, so this stitches them together with symlinks, next to
    the AGENTS.md composed for this mode. It lives in the checkout's gitignored
    .ocbox/ rather than under $HOME, keeping what ocbox writes inside the
    package; OpenCode's own plugin install into this directory lands there too.

    Verified against opencode 1.18.29 rather than assumed: agents, skills and
    opencode.jsonc all load from a directory given through OPENCODE_CONFIG_DIR;
    a config layered over it with OPENCODE_CONFIG merges rather than replacing
    it; and an AGENTS.md inside it is sent to the model as the global one,
    alongside the project's (checked by recording the request bodies OpenCode
    sends to a stub LLM).
    """
    config_dir = image.repo_local_dir() / "no-sandbox" / "opencode-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    links = {"agents": agents_dir, "skills": skills_dir, "opencode.jsonc": user_config}
    for name, source in links.items():
        link = config_dir / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(source, target_is_directory=source.is_dir())
    agents_md_path = config_dir / "AGENTS.md"
    if agents_md_path.is_symlink() or agents_md_path.exists():
        agents_md_path.unlink()
    if agents_md is not None:
        agents_md_path.write_text(agents_md)
    return config_dir


def run_no_sandbox(
    *,
    agents_dir: Path | None = None,
    skills_dir: Path | None = None,
    user_config: Path | None = None,
    opencode_args: list[str] | None = None,
) -> int:
    """Runs OpenCode directly on the host - no Podman, no isolation at all.

    Trades ocbox's whole sandboxing story for convenience: it still installs
    OpenCode if missing and wires up the same agents/skills/model config from
    opencode-config/, but nothing here limits what OpenCode can touch on this
    machine or reach over the network. Use --tui or the default web mode for
    the actual sandbox.

    Everything is passed by environment variable rather than written into the
    user's home: OPENCODE_CONFIG_DIR points at a directory ocbox assembles in
    the checkout's .ocbox/, and ocbox itself writes nothing under
    ~/.config/opencode - though OpenCode, on its own account, installs its
    plugin SDK there at startup.
    OpenCode does still *read* that directory alongside the one it is given -
    measured against 1.18.29 with a marker in each file: the user's own
    opencode.jsonc and agents/ are merged in, while their AGENTS.md is replaced
    by the team's. So unlike a sandbox, a personal global config comes along.

    Unlike the sandboxed modes there is no relay: opencode.jsonc's baseURL is
    reachable directly, since nothing here is network-isolated, and OpenCode
    uses it as written.
    """
    opencode_bin = _find_or_install_opencode()

    resolved_agents_dir = agents_dir or (image.repo_config_dir() / "agents")
    resolved_skills_dir = skills_dir or (image.repo_config_dir() / "skills")
    # Only opencode-config/opencode.jsonc is the user's to touch; --opencode-config
    # exists for a one-off run, and nothing in the home directory overrides it.
    resolved_user_config = user_config or (image.repo_config_dir() / "opencode.jsonc")
    agents_md_text = _compose_global_agents_md("no-sandbox", [])

    config_dir = _build_no_sandbox_config_dir(
        resolved_agents_dir,
        resolved_skills_dir,
        resolved_user_config,
        agents_md_text,
    )

    print(
        "ocbox: running OpenCode directly on this machine - no sandbox, no "
        "network isolation. Ctrl-C or OpenCode's own quit key to stop.\n"
    )
    env = os.environ.copy()
    env["OPENCODE_CONFIG_DIR"] = str(config_dir)
    # The assembled directory already carries the right opencode.jsonc, and a
    # stale OPENCODE_CONFIG inherited from a sandboxed run would point at a
    # relay that isn't running here.
    env.pop("OPENCODE_CONFIG", None)
    os.execvpe(opencode_bin, [opencode_bin, *(opencode_args or [])], env)
    return 0  # unreachable - execvpe replaces this process on success
