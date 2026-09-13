"""The team's permission rules in opencode-config/opencode.jsonc, evaluated the
way OpenCode does - so a reordered block, or a pattern that can never match,
fails here rather than silently inside a session.

Mirrors opencode 1.18.30's bundled code:
- Permission.fromConfig keeps a block's entries in written order; a string
  value is the pattern "*"; a leading "~/" is the home directory.
- Permission.evaluate is `rulesets.flat().findLast(match)`: the LAST matching
  rule wins. Nothing sorts by pattern length.
- Wildcard.match anchors the pattern, turns * into .* and ? into ., with the
  dotAll flag; a trailing " *" also matches the bare command.
- read and edit ask with the path relative to the worktree; external_directory
  asks with the absolute parent directory plus "/*".

OpenCode's own rules come before the config and decide whatever the config
doesn't match: the default allow-everything rule, and the built-in plan
agent's restrictions, both as `opencode debug agent` resolves them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ocbox import jsonc

CONFIG = Path(__file__).resolve().parents[1] / "opencode-config" / "opencode.jsonc"
HOME = "/home/u"


def _rules(block: dict) -> list[tuple[str, str, str]]:
    rules = []
    for permission, value in block.items():
        if isinstance(value, str):
            rules.append((permission, "*", value))
            continue
        for written, action in value.items():
            pattern = HOME + written[1:] if written.startswith("~/") else written
            rules.append((permission, pattern, action))
    return rules


def _regex(pattern: str) -> str:
    return "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)


def _match(text: str, pattern: str) -> bool:
    regex = _regex(pattern[:-2]) + "( .*)?" if pattern.endswith(" *") else _regex(pattern)
    return re.fullmatch(regex, text, re.DOTALL) is not None


def _evaluate(rules: list[tuple[str, str, str]], permission: str, pattern: str) -> str:
    for rule_permission, rule_pattern, action in reversed(rules):
        if _match(permission, rule_permission) and _match(pattern, rule_pattern):
            return action
    return "ask"


@pytest.fixture(scope="module")
def config() -> dict:
    return jsonc.load(CONFIG)


# OpenCode 1.18.30's defaults that matter here, and what its built-in plan agent
# adds on top of them.
DEFAULTS = [("*", "*", "allow"), ("external_directory", "*", "ask")]
PLAN_BUILTINS = [
    ("external_directory", f"{HOME}/.local/share/opencode/plans/*", "allow"),
    ("edit", "*", "deny"),
    ("edit", ".opencode/plans/*.md", "allow"),
    ("edit", "home/u/.local/share/opencode/plans/*.md", "allow"),
]


@pytest.fixture(scope="module")
def build(config) -> list[tuple[str, str, str]]:
    return DEFAULTS + _rules(config["permission"])


@pytest.fixture(scope="module")
def plan(config) -> list[tuple[str, str, str]]:
    return DEFAULTS + PLAN_BUILTINS + _rules(config["permission"])


# ---- plan: left as OpenCode ships it ------------------------------------------


def test_the_config_does_not_redefine_plan(config) -> None:
    assert "plan" not in config.get("agent", {})


@pytest.mark.parametrize(
    "path",
    [".opencode/plans/1726-refactor.md", "home/u/.local/share/opencode/plans/1726-refactor.md"],
)
def test_plan_keeps_writing_its_plan_file(plan, path) -> None:
    assert _evaluate(plan, "edit", path) == "allow"


def test_plan_keeps_its_own_restriction_on_project_files(plan) -> None:
    """A config "edit" rule matching everything - even "*": "allow", which
    looks harmless - comes after plan's built-in "*": "deny" and lifts it."""
    assert _evaluate(plan, "edit", "src/app.py") == "deny"


def test_the_plans_directory_is_reachable(build) -> None:
    assert _evaluate(build, "external_directory", f"{HOME}/.local/share/opencode/plans/*") == (
        "allow"
    )


def test_build_can_edit_project_files(build) -> None:
    assert _evaluate(build, "edit", "src/app.py") == "allow"


# ---- external_directory --------------------------------------------------------


@pytest.mark.parametrize(
    "directory",
    [
        f"{HOME}/.config/opencode/skills/code-review/*",
        f"{HOME}/.config/opencode/skills/sota-review/references/*",
        "/work/ocbox/.ocbox/no-sandbox/opencode-config/skills/code-review/references/*",
        "/work/ocbox/.ocbox/no-sandbox/opencode-config/skills/any-new-skill/*",
    ],
)
def test_skill_files_are_reachable_in_both_modes(build, directory) -> None:
    assert _evaluate(build, "external_directory", directory) == "allow"


@pytest.mark.parametrize(
    "directory",
    ["/tmp/evil/opencode-config/skills/code-review/*", "/etc/*", f"{HOME}/.ssh/*"],
)
def test_other_directories_outside_the_project_stay_denied(build, directory) -> None:
    assert _evaluate(build, "external_directory", directory) == "deny"


# ---- read / edit -----------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [".ssh/id_rsa", "../.ssh/id_rsa", "home/u/.ssh/id_rsa", "../../.aws/credentials"]
)
def test_credentials_stay_unreadable_wherever_the_worktree_is(build, path) -> None:
    assert _evaluate(build, "read", path) == "deny"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", "deny"),
        ("app/.env.production", "deny"),
        ("app/.env.example", "allow"),
        ("src/main.py", "allow"),
    ],
)
def test_env_files(build, path, expected) -> None:
    assert _evaluate(build, "read", path) == expected


def test_credentials_are_not_editable(build) -> None:
    assert _evaluate(build, "edit", "../.ssh/authorized_keys") == "deny"


@pytest.mark.parametrize(
    "path",
    [
        "../ocbox/.ocbox/no-sandbox/opencode-config/skills/code-review/SKILL.md",
        "home/u/ocbox/.ocbox/no-sandbox/opencode-config/skills/sota-review/references/x.md",
        "home/ocbox/.config/opencode/skills/code-review/SKILL.md",
    ],
)
def test_skills_are_readable_but_not_editable(build, path) -> None:
    """external_directory has to let the model reach skill files; without this
    the global edit block would let `build` rewrite the team's skills under
    --no-sandbox."""
    assert _evaluate(build, "edit", path) == "deny"
    assert _evaluate(build, "read", path) == "allow"


def test_read_and_edit_patterns_can_match_a_worktree_relative_path(config) -> None:
    """read and edit are asked with a relative path: a "~/..." or absolute
    pattern there looks like protection and never matches anything."""
    for block in ("read", "edit"):
        for pattern in config["permission"][block]:
            assert not pattern.startswith(("~", "/")), f"{block}: {pattern!r}"


# ---- bash ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("pip install requests", "ask"),
        ("pip install -r requirements.txt", "allow"),
        ("uv sync", "allow"),
        ("sudo rm -rf build", "deny"),
        ("git push origin main", "ask"),
        ("git status", "allow"),
    ],
)
def test_bash_exceptions_come_after_their_general_rule(build, command, expected) -> None:
    assert _evaluate(build, "bash", command) == expected
