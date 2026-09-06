import json
from pathlib import Path

from ocbox.sandbox import RunPlan, _generate_opencode_config, build_podman_run_argv


def _plan(**overrides) -> RunPlan:
    defaults = dict(
        image_tag="ocbox/project-test:latest",
        workspace=Path("/home/user/myproj"),
        run_dir=Path("/run/user/1000/ocbox/myproj"),
        env_file=Path("/run/user/1000/ocbox/myproj/env"),
        opencode_config=Path("/run/user/1000/ocbox/myproj/opencode.json"),
        agents_json=Path("/pkg/data/agents.json"),
        skills_dir=Path("/pkg/data/skills"),
        data_volume="ocbox-home-myproj",
        container_name="ocbox-myproj",
        container_web_port=4096,
        container_llm_port=8081,
    )
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


def test_generate_opencode_config_points_at_container_llm_port(tmp_path) -> None:
    agents_path = tmp_path / "agents.json"
    agents_path.write_text(json.dumps({"agents": [{"name": "default"}], "skills": []}))

    cfg = _generate_opencode_config(8081, agents_path)
    assert cfg["provider"]["local"]["options"]["baseURL"] == "http://127.0.0.1:8081/v1"
    assert cfg["agents"] == [{"name": "default"}]


def test_generate_opencode_config_handles_missing_agents_file(tmp_path) -> None:
    cfg = _generate_opencode_config(8081, tmp_path / "does-not-exist.json")
    assert "agents" not in cfg
    assert cfg["provider"]["local"]["options"]["baseURL"] == "http://127.0.0.1:8081/v1"
