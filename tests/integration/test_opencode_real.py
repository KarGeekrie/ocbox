"""OpenCode itself, loading what ocbox hands it.

test_end_to_end.py proves ocbox's sandboxing mechanism with a stand-in for
OpenCode. This suite runs the real thing, end to end through the `ocbox` CLI:
the sandbox image ocbox builds - with whatever OpenCode is current, since the
images are deliberately unpinned - the team's opencode-config/, and a stub LLM
recording every request (stub_llm.py). It checks what the unit tests can only
assume about OpenCode:

- it discovers our agents and skills where ocbox mounts or links them;
- it merges the team's opencode.jsonc with the config ocbox generates;
- it sends the composed AGENTS.md to the model;
- it enforces the permissions we rely on, in real tool calls.

Opt-in with RUN_OPENCODE_INTEGRATION=1: the first sandbox run builds the real
image, which needs network and takes minutes. CI runs it on pull requests and
weekly, so an OpenCode release that changes any of this fails there rather than
in someone's session.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from ocbox import jsonc, project
from ocbox.sandbox import CONTAINER_LLM_PORT, SANDBOX_UV_PROJECT_ENVIRONMENT, SKILLS_DIR_MOUNT

from .stub_llm import StubLLM

pytestmark = pytest.mark.skipif(
    shutil.which("podman") is None or os.environ.get("RUN_OPENCODE_INTEGRATION") != "1",
    reason="requires podman, network for the image build, and RUN_OPENCODE_INTEGRATION=1",
)

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "opencode-config"
TEAM_CONFIG = CONFIG_DIR / "opencode.jsonc"
FIRST_RUN_TIMEOUT = 45 * 60  # builds the real sandbox image
RUN_TIMEOUT = 5 * 60
REPORT = "review_report.md"  # the one file the review agent may write


def _ocbox(project_dir: Path, *args: str, timeout: int = RUN_TIMEOUT) -> str:
    """Runs the ocbox CLI in `project_dir` and returns its output, CRs removed.

    `--tui` runs attach a pseudo-terminal, so OpenCode's output arrives with
    CRLF line ends and podman's "not a TTY" warning in front of it.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ocbox", *args],
        cwd=project_dir,
        env={**os.environ, "OCBOX_SKIP_UPDATE_CHECK": "1"},
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = (result.stdout + result.stderr).replace("\r", "")
    assert result.returncode == 0, f"ocbox {' '.join(args)} exited {result.returncode}:\n{output}"
    return output


def _find_json(output: str, wanted: Callable[[object], bool]) -> object:
    """The first JSON value in `output` that `wanted` accepts - podman's warning
    line holds a `[0000]` that would otherwise parse as a list."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", output):
        try:
            value, _ = decoder.raw_decode(output[match.start() :])
        except ValueError:
            continue
        if wanted(value):
            return value
    raise AssertionError(f"no matching JSON in output:\n{output[-3000:]}")


def _match(text: str, pattern: str) -> bool:
    """OpenCode's Wildcard.match: anchored, * -> .*, ? -> ., a trailing " *" optional."""

    def regex(p: str) -> str:
        return "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in p)

    full = regex(pattern[:-2]) + "( .*)?" if pattern.endswith(" *") else regex(pattern)
    return re.fullmatch(full, text, re.DOTALL) is not None


def _decide(rules: list[dict], permission: str, pattern: str) -> str:
    """OpenCode's Permission.evaluate over the rules it resolved: the last match wins."""
    for rule in reversed(rules):
        if _match(permission, rule["permission"]) and _match(pattern, rule["pattern"]):
            return rule["action"]
    return "ask"


def _team_skills() -> list[str]:
    return sorted(p.parent.name for p in (CONFIG_DIR / "skills").glob("*/SKILL.md"))


def _first_model() -> str:
    return next(iter(jsonc.load(TEAM_CONFIG)["provider"]["local"]["models"]))


def _config_pointing_at(stub: StubLLM, directory: Path) -> Path:
    """The team's opencode.jsonc, unchanged except for baseURL."""
    text = TEAM_CONFIG.read_text()
    replaced, count = re.subn(
        r'"baseURL"\s*:\s*"[^"]*"', f'"baseURL": "http://127.0.0.1:{stub.port}/v1"', text
    )
    assert count == 1, "expected exactly one baseURL in opencode.jsonc"
    path = directory / "opencode.jsonc"
    path.write_text(replaced)
    return path


@contextmanager
def _project(directory: Path) -> Iterator[Path]:
    """A throwaway project; removes the home volume and image ocbox creates for it."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        slug = project.project_slug(directory)
        for command in (
            ["podman", "volume", "rm", "-f", f"ocbox-home-{slug}"],
            ["podman", "rmi", "-f", f"ocbox/project-{slug}:latest"],
        ):
            subprocess.run(command, capture_output=True, check=False)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory) -> Iterator[tuple[Path, str]]:
    """One project, plus the output of its first run - which builds the image."""
    with _project(tmp_path_factory.mktemp("opencode") / "project") as path:
        (path / "AGENTS.md").write_text("# Project rules\n\nMarker: ocbox-project-agents-md\n")
        (path / "app.py").write_text("print('hello')\n")
        yield path, _ocbox(path, "--tui", "--yes", "--", "agent", "list", timeout=FIRST_RUN_TIMEOUT)


@pytest.fixture(scope="module")
def resolved_rules(sandbox) -> dict[str, list[dict]]:
    path, _ = sandbox
    rules = {}
    for agent in ("build", "plan", "review", "chat"):
        output = _ocbox(path, "--tui", "--yes", "--", "debug", "agent", agent)
        rules[agent] = _find_json(output, lambda v: isinstance(v, dict) and "permission" in v)[
            "permission"
        ]
    return rules


# ---- discovery and configuration --------------------------------------------------


def _agent_modes(output: str) -> dict[str, str]:
    return dict(re.findall(r"^(\S+) \((primary|subagent|all)\)\s*$", output, re.MULTILINE))


def test_sandbox_lists_the_team_agents_as_primary(sandbox) -> None:
    _, output = sandbox
    modes = _agent_modes(output)
    assert modes.get("chat") == "primary"
    assert modes.get("review") == "primary"
    assert modes.get("build") == "primary"
    assert modes.get("plan") == "primary"
    assert "README" not in modes, "agents/README.md loaded as an agent"


def test_sandbox_finds_every_team_skill_where_ocbox_mounts_it(sandbox) -> None:
    path, _ = sandbox
    output = _ocbox(path, "--tui", "--yes", "--", "debug", "skill")
    skills = _find_json(output, lambda v: isinstance(v, list) and bool(v) and "location" in v[0])
    locations = {skill["name"]: skill["location"] for skill in skills}
    for name in _team_skills():
        assert locations.get(name) == f"{SKILLS_DIR_MOUNT}/{name}/SKILL.md"


def test_sandbox_merges_the_team_config_with_the_generated_relay_endpoint(sandbox) -> None:
    path, _ = sandbox
    output = _ocbox(path, "--tui", "--yes", "--", "debug", "config")
    config = _find_json(output, lambda v: isinstance(v, dict) and "provider" in v)
    team = jsonc.load(TEAM_CONFIG)
    local = config["provider"]["local"]
    team_path = urllib.parse.urlsplit(team["provider"]["local"]["options"]["baseURL"]).path
    assert local["options"]["baseURL"] == f"http://127.0.0.1:{CONTAINER_LLM_PORT}{team_path}"
    assert set(local["models"]) == set(team["provider"]["local"]["models"])
    assert config["permission"]["external_directory"] == team["permission"]["external_directory"]
    assert config.get("share") == team.get("share")


@pytest.mark.parametrize(
    ("agent", "permission", "pattern", "expected"),
    [
        ("build", "edit", "src/app.py", "allow"),
        ("plan", "edit", "src/app.py", "deny"),
        ("plan", "edit", ".opencode/plans/1-plan.md", "allow"),
        ("review", "edit", "src/app.py", "deny"),
        ("review", "edit", "review_report.md", "allow"),
        ("review", "edit", "workspace/review_report.md", "allow"),
        ("review", "webfetch", "https://example.com", "deny"),
        ("chat", "edit", "src/app.py", "deny"),
        ("chat", "bash", "ls", "deny"),
        ("build", "external_directory", f"{SKILLS_DIR_MOUNT}/code-review/references/*", "allow"),
        ("build", "external_directory", "/etc/*", "deny"),
    ],
)
def test_agent_permissions_as_opencode_resolves_them(
    resolved_rules, agent, permission, pattern, expected
) -> None:
    assert _decide(resolved_rules[agent], permission, pattern) == expected


# ---- real sessions ------------------------------------------------------------------


def test_review_session_gets_the_composed_prompt_and_the_skill(sandbox, tmp_path) -> None:
    path, _ = sandbox
    checklist = "code-review/references/checklist-python.md"
    scenario = [
        {"name": "skill", "arguments": {"name": "code-review"}},
        {"name": "read", "arguments": {"filePath": f"{SKILLS_DIR_MOUNT}/{checklist}"}},
        {"name": "write", "arguments": {"filePath": f"/workspace/{REPORT}", "content": "# R"}},
        {"name": "write", "arguments": {"filePath": "/workspace/written.txt", "content": "x"}},
    ]
    with StubLLM(scenario) as llm:
        config = _config_pointing_at(llm, tmp_path)
        _ocbox(
            path, "--tui", "--yes", "--opencode-config", str(config), "--",
            "run", "--agent", "review", "--model", f"local/{_first_model()}", "review app.py",
        )

    requests = llm.tool_requests()
    assert requests, "OpenCode never reached the LLM"
    system = llm.system_prompt(requests[0])
    environment = (CONFIG_DIR / "environments" / "sandbox.md").read_text().splitlines()[0]
    team_rules = (CONFIG_DIR / "AGENTS.md").read_text().splitlines()[0]
    for origin, marker in [
        ("environments/sandbox.md", environment),
        ("the sandbox facts", "- Network: none."),
        ("the home directory fact", "`/home/ocbox` is kept between this project's sessions"),
        ("the team AGENTS.md", team_rules),
        ("the project AGENTS.md", "Marker: ocbox-project-agents-md"),
        ("agents/review.md", "You review code in the user's project."),
    ]:
        assert marker in system, f"system prompt lacks {origin}"

    tools = llm.tool_names(requests[0])
    assert {"skill", "read", "write"} <= tools, "review needs write for its report"

    results = llm.tool_results(requests[-1])
    assert '<skill_content name="code-review">' in results[0]
    assert (CONFIG_DIR / "skills" / checklist).read_text().splitlines()[0] in results[1]
    assert (path / "review_report.md").read_text() == "# R", "review couldn't write its report"
    assert not (path / "written.txt").exists(), "review wrote a file other than its report"


def test_build_session_uses_a_mount_and_stays_out_of_the_rest(tmp_path) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "note.txt").write_text("ocbox-mounted-note\n")
    scenario = [
        {"name": "read", "arguments": {"filePath": "/mnt/extra/note.txt"}},
        {"name": "write", "arguments": {"filePath": "/mnt/extra/created.txt", "content": "x"}},
        {"name": "glob", "arguments": {"pattern": "*.txt", "path": "/workspace"}},
        {"name": "read", "arguments": {"filePath": "/etc/hostname"}},
    ]
    with _project(tmp_path / "project") as path, StubLLM(scenario) as llm:
        (path / "inside.txt").write_text("inside\n")
        config = _config_pointing_at(llm, tmp_path)
        _ocbox(
            path, "--tui", "--yes", "--opencode-config", str(config), "--mount", str(extra), "--",
            "run", "--model", f"local/{_first_model()}", "go",
            timeout=FIRST_RUN_TIMEOUT,
        )

    requests = llm.tool_requests()
    assert requests, "OpenCode never reached the LLM"
    results = llm.tool_results(requests[-1])
    assert "ocbox-mounted-note" in results[0]
    assert (extra / "created.txt").read_text() == "x"
    assert "/workspace/inside.txt" in results[2], "glob failed - is ripgrep in the image?"
    assert "<content>" not in results[3], "/etc/hostname was readable"


def test_uv_in_a_sandbox_leaves_the_projects_host_venv_alone(tmp_path) -> None:
    """A venv made on the host links to an interpreter the sandbox doesn't have.
    uv, finding it broken, used to delete and recreate it - emptying the user's
    venv, since nothing can be reinstalled without network. ocbox points uv at
    an environment outside the project instead."""
    host_python = "/nonexistent/uv-managed/bin/python3.13"
    scenario = [
        {
            "name": "bash",
            "arguments": {
                "command": "uv sync && uv run python -c 'import sys; print(sys.prefix)'",
                "description": "Sync the project and show which environment runs it",
            },
        }
    ]
    with _project(tmp_path / "project") as path, StubLLM(scenario) as llm:
        (path / "pyproject.toml").write_text(
            '[project]\nname = "uvcheck"\nversion = "0"\nrequires-python = ">=3.8"\n'
            "dependencies = []\n"
        )
        venv = path / ".venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").symlink_to(host_python)
        (venv / "pyvenv.cfg").write_text(f"home = {Path(host_python).parent}\n")
        (venv / "made-on-the-host").write_text("")
        config = _config_pointing_at(llm, tmp_path)
        _ocbox(
            path, "--tui", "--yes", "--opencode-config", str(config), "--",
            "run", "--model", f"local/{_first_model()}", "go",
            timeout=FIRST_RUN_TIMEOUT,
        )

        requests = llm.tool_requests()
        assert requests, "OpenCode never reached the LLM"
        assert SANDBOX_UV_PROJECT_ENVIRONMENT in llm.tool_results(requests[-1])[0]
        assert (venv / "made-on-the-host").exists(), "uv replaced the host's .venv"
        assert os.readlink(venv / "bin" / "python") == host_python


# ---- --no-sandbox -----------------------------------------------------------------


def test_no_sandbox_loads_the_same_agents_and_skills(tmp_path) -> None:
    """Debug commands only: a session on the host can hang in OpenCode itself
    (README, "Known limitation")."""
    modes = _agent_modes(_ocbox(tmp_path, "--no-sandbox", "--", "agent", "list"))
    assert modes.get("chat") == "primary"
    assert modes.get("review") == "primary"
    assert "README" not in modes

    output = _ocbox(tmp_path, "--no-sandbox", "--", "debug", "skill")
    skills = _find_json(output, lambda v: isinstance(v, list) and bool(v) and "location" in v[0])
    locations = {skill["name"]: skill["location"] for skill in skills}
    for name in _team_skills():
        assert locations.get(name, "").endswith(
            f"/.ocbox/no-sandbox/opencode-config/skills/{name}/SKILL.md"
        )
