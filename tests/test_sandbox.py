from pathlib import Path

import pytest

from ocbox import sandbox
from ocbox.sandbox import (
    AGENTS_DIR_MOUNT,
    INSTRUCTIONS_DIR_MOUNT,
    SKILLS_DIR_MOUNT,
    USER_CONFIG_MOUNT,
    RunPlan,
    _generate_opencode_config,
    build_podman_run_argv,
)


def _plan(**overrides) -> RunPlan:
    defaults = {
        "image_tag": "ocbox/project-test:latest",
        "workspace": Path("/home/user/myproj"),
        "run_dir": Path("/run/user/1000/ocbox/myproj"),
        "env_file": Path("/run/user/1000/ocbox/myproj/env"),
        "opencode_config": Path("/run/user/1000/ocbox/myproj/opencode.json"),
        "agents_dir": Path("/pkg/data/agents"),
        "user_config": Path("/pkg/data/opencode.jsonc"),
        "skills_dir": Path("/pkg/data/skills"),
        "instructions_dir": Path("/pkg/data/instructions"),
        "data_volume": "ocbox-home-myproj",
        "container_name": "ocbox-myproj",
        "container_web_port": 4096,
        "container_llm_port": 8081,
    }
    defaults.update(overrides)
    return RunPlan(**defaults)


def test_argv_uses_network_none_and_no_publish() -> None:
    argv = build_podman_run_argv(_plan())
    assert "--network" in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert "-p" not in argv
    assert "--publish" not in argv


def test_argv_mounts_only_workspace_and_ocbox_dirs() -> None:
    argv = build_podman_run_argv(_plan())
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    sources = [m.split(":")[0] for m in mounts]
    assert "/home/user/myproj" in sources
    assert "/run/user/1000/ocbox/myproj" in sources
    # no unrelated host paths mounted
    assert all(
        s.startswith(("/home/user/myproj", "/run/user/1000/ocbox/myproj", "/pkg/data"))
        or s == "ocbox-home-myproj"
        for s in sources
    )


def test_argv_workspace_is_readwrite() -> None:
    argv = build_podman_run_argv(_plan())
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    workspace_mount = next(m for m in mounts if m.startswith("/home/user/myproj:"))
    assert workspace_mount.endswith(":rw")


def test_argv_uses_env_file_not_inline_env_for_secrets() -> None:
    argv = build_podman_run_argv(_plan())
    assert "--env-file" in argv
    # no -e flag should carry the word PASSWORD or TOKEN (secrets must go via --env-file)
    inline_envs = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert not any("PASSWORD" in e or "TOKEN" in e for e in inline_envs)


def test_argv_includes_hardening_flags() -> None:
    argv = build_podman_run_argv(_plan())
    assert "--cap-drop" in argv
    assert "--read-only" in argv
    assert "--userns" in argv
    assert "--init" in argv


def test_argv_omits_resource_limits_when_unset() -> None:
    argv = build_podman_run_argv(_plan(memory_limit=None, pids_limit=None))
    assert "--memory" not in argv
    assert "--pids-limit" not in argv


def test_argv_includes_resource_limits_when_set() -> None:
    argv = build_podman_run_argv(_plan(memory_limit="2g", pids_limit=256))
    assert "--memory" in argv
    assert argv[argv.index("--memory") + 1] == "2g"
    assert "--pids-limit" in argv
    assert argv[argv.index("--pids-limit") + 1] == "256"


def test_generate_opencode_config_uses_the_given_base_url() -> None:
    """base_url is the relay endpoint in sandbox mode, or LLM_HOST:LLM_PORT
    directly in --no-sandbox mode - either way it's just passed through."""
    cfg = _generate_opencode_config("http://127.0.0.1:8081/v1")
    assert cfg["provider"]["local"]["options"]["baseURL"] == "http://127.0.0.1:8081/v1"


def test_generate_opencode_config_generates_only_the_provider() -> None:
    """Everything else is a mounted file: agents and skills sit where OpenCode
    already looks, models come from the user's own opencode.jsonc. The relay
    endpoint is the only thing ocbox has to synthesise."""
    cfg = _generate_opencode_config("http://127.0.0.1:8081/v1")
    assert set(cfg) == {"provider"}


def test_generate_opencode_config_uses_only_real_schema_keys() -> None:
    """OpenCode's schema is additionalProperties=false but its runtime drops
    unknown keys silently, so a typo here disables a feature with no error -
    which is exactly how `skillsDir`/`agents` went unnoticed."""
    cfg = _generate_opencode_config("http://127.0.0.1:8081/v1")
    assert "skillsDir" not in cfg
    assert "agents" not in cfg


def test_argv_mounts_skills_dir_at_opencode_discovery_path() -> None:
    """Same mechanism as agents: OpenCode finds these because of where they
    are, so no `skills.paths` entry is needed in the generated config."""
    argv = build_podman_run_argv(_plan(skills_dir=Path("/pkg/data/skills")))
    assert f"/pkg/data/skills:{SKILLS_DIR_MOUNT}:ro" in argv
    assert SKILLS_DIR_MOUNT == "/home/ocbox/.config/opencode/skills"


def test_argv_mounts_skills_dir_after_the_home_volume_it_nests_in() -> None:
    argv = build_podman_run_argv(_plan())
    home_volume = next(i for i, a in enumerate(argv) if a.endswith(":/home/ocbox:rw"))
    skills = next(i for i, a in enumerate(argv) if a.endswith(f":{SKILLS_DIR_MOUNT}:ro"))
    assert home_volume < skills


def test_argv_mounts_instructions_dir_at_opencode_discovery_path() -> None:
    """Same mechanism as agents/skills: mounted at a fixed location, though
    unlike them, OpenCode is believed to also need instructions.jsonc's own
    `instructions` array to point at it - see opencode-config/instructions/
    README.md."""
    argv = build_podman_run_argv(_plan(instructions_dir=Path("/pkg/data/instructions")))
    assert f"/pkg/data/instructions:{INSTRUCTIONS_DIR_MOUNT}:ro" in argv
    assert INSTRUCTIONS_DIR_MOUNT == "/home/ocbox/.config/opencode/instructions"


def test_argv_mounts_instructions_dir_after_the_home_volume_it_nests_in() -> None:
    argv = build_podman_run_argv(_plan())
    home_volume = next(i for i, a in enumerate(argv) if a.endswith(":/home/ocbox:rw"))
    instructions = next(
        i for i, a in enumerate(argv) if a.endswith(f":{INSTRUCTIONS_DIR_MOUNT}:ro")
    )
    assert home_volume < instructions


def test_argv_mounts_user_config_as_opencode_global_config() -> None:
    """Mounted at OpenCode's *global* config path on purpose: global ranks
    below OPENCODE_CONFIG, so ocbox keeps control of the provider endpoint
    while the user's model list is merged in."""
    argv = build_podman_run_argv(_plan(user_config=Path("/home/u/.config/ocbox/opencode.jsonc")))
    assert f"/home/u/.config/ocbox/opencode.jsonc:{USER_CONFIG_MOUNT}:ro" in argv
    assert USER_CONFIG_MOUNT == "/home/ocbox/.config/opencode/opencode.jsonc"


def test_argv_mounts_user_config_after_the_home_volume_it_nests_in() -> None:
    argv = build_podman_run_argv(_plan())
    home_volume = next(i for i, a in enumerate(argv) if a.endswith(":/home/ocbox:rw"))
    user_config = next(i for i, a in enumerate(argv) if a.endswith(f":{USER_CONFIG_MOUNT}:ro"))
    assert home_volume < user_config


def test_argv_mounts_agents_dir_after_the_home_volume_it_nests_in() -> None:
    """The agents mount lives inside /home/ocbox; podman needs the volume
    mounted first or the nested bind is shadowed."""
    argv = build_podman_run_argv(_plan())
    home_volume = next(i for i, a in enumerate(argv) if a.endswith(":/home/ocbox:rw"))
    agents = next(i for i, a in enumerate(argv) if a.endswith(f":{AGENTS_DIR_MOUNT}:ro"))
    assert home_volume < agents


def test_argv_web_mode_omits_it_flag() -> None:
    argv = build_podman_run_argv(_plan(mode="web"))
    assert "-it" not in argv


def test_argv_tui_mode_uses_it_flag() -> None:
    argv = build_podman_run_argv(_plan(mode="tui"))
    assert "-it" in argv


def test_argv_tui_mode_skips_env_file_when_none() -> None:
    argv = build_podman_run_argv(_plan(mode="tui", env_file=None))
    assert "--env-file" not in argv


def test_argv_tui_mode_omits_web_port_env() -> None:
    argv = build_podman_run_argv(_plan(mode="tui", env_file=None))
    inline_envs = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert not any(e.startswith("OCBOX_CONTAINER_WEB_PORT=") for e in inline_envs)
    assert "OCBOX_MODE=tui" in inline_envs


def test_argv_web_mode_includes_web_port_env() -> None:
    argv = build_podman_run_argv(_plan(mode="web"))
    inline_envs = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert "OCBOX_CONTAINER_WEB_PORT=4096" in inline_envs
    assert "OCBOX_MODE=web" in inline_envs


def test_runplan_rejects_web_mode_without_env_file() -> None:
    with pytest.raises(ValueError, match="env_file is required"):
        _plan(mode="web", env_file=None)


def test_runplan_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="must be 'web' or 'tui'"):
        _plan(mode="bogus")


def test_runplan_tui_mode_allows_no_env_file() -> None:
    plan = _plan(mode="tui", env_file=None)
    assert plan.env_file is None


def test_argv_tui_mode_still_mounts_workspace_and_config() -> None:
    argv = build_podman_run_argv(_plan(mode="tui", env_file=None))
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    sources = [m.split(":")[0] for m in mounts]
    assert "/home/user/myproj" in sources
    assert "/pkg/data/agents" in sources
    assert "/pkg/data/skills" in sources
    assert "/pkg/data/instructions" in sources


def test_resolve_user_config_prefers_the_users_file(tmp_path, monkeypatch) -> None:
    user_file = tmp_path / "opencode.jsonc"
    user_file.write_text("{}")
    monkeypatch.setattr(sandbox, "USER_CONFIG_PATH", user_file)
    assert sandbox._resolve_user_config() == user_file


def test_resolve_user_config_falls_back_to_packaged_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox, "USER_CONFIG_PATH", tmp_path / "absent.jsonc")
    resolved = sandbox._resolve_user_config()
    assert resolved.name == "opencode.jsonc"
    assert resolved.exists(), "the packaged default must ship, it is always mounted"


def test_argv_appends_opencode_args_after_the_image_tag() -> None:
    """They land as the container's CMD, which entrypoint.sh forwards as "$@"."""
    plan = _plan(opencode_args=["--model", "local/qwen"])
    argv = build_podman_run_argv(plan)
    assert argv[-3:] == [plan.image_tag, "--model", "local/qwen"]


def test_argv_without_opencode_args_ends_at_the_image_tag() -> None:
    plan = _plan()
    assert build_podman_run_argv(plan)[-1] == plan.image_tag


def test_check_opencode_args_rejects_flags_ocbox_owns() -> None:
    for arg in ("--port", "--hostname", "--port=9999"):
        with pytest.raises(sandbox.OpencodeArgsError):
            sandbox.check_opencode_args(["--model", "local/qwen", arg], mode="tui")


def test_check_opencode_args_allows_everything_else_in_tui_mode() -> None:
    sandbox.check_opencode_args(
        ["run", "--model", "local/qwen", "--agent", "review"], mode="tui"
    )


def test_check_opencode_args_rejects_any_args_in_web_mode() -> None:
    """Web mode appends passthrough to `opencode serve`, which chokes on most
    of OpenCode's own CLI - so it's refused outright rather than forwarded."""
    with pytest.raises(sandbox.OpencodeArgsError, match="--tui"):
        sandbox.check_opencode_args(["--print-logs"], mode="web")


def test_check_opencode_args_allows_no_args_in_web_mode() -> None:
    sandbox.check_opencode_args([], mode="web")


def test_daemonize_parent_returns_the_childs_pid(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sandbox.os, "fork", lambda: 4242)
    assert sandbox.daemonize(tmp_path / "ocbox.log") == 4242


def test_daemonize_child_detaches_and_redirects_stdio(monkeypatch, tmp_path) -> None:
    """Exercises the child branch without ever calling the real os.setsid/dup2 -
    doing that for real would sever this test process's own stdio."""
    calls: list[tuple] = []
    monkeypatch.setattr(sandbox.os, "fork", lambda: 0)
    monkeypatch.setattr(sandbox.os, "setsid", lambda: calls.append(("setsid",)))
    monkeypatch.setattr(sandbox.os, "open", lambda *a, **k: calls.append(("open", *a)) or 99)
    monkeypatch.setattr(sandbox.os, "dup2", lambda fd, target: calls.append(("dup2", fd, target)))
    monkeypatch.setattr(sandbox.os, "close", lambda fd: calls.append(("close", fd)))

    result = sandbox.daemonize(tmp_path / "ocbox.log")

    assert result == 0
    assert ("setsid",) in calls
    assert ("dup2", 99, 1) in calls  # stdout -> the log file
    assert ("dup2", 99, 2) in calls  # stderr -> the log file
    assert calls.count(("close", 99)) == 2  # devnull fd and log fd, each closed after dup2'ing
