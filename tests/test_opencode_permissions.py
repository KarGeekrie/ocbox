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

OpenCode's own defaults come before the config and only decide what nothing
here matches, so the rules below are the config's alone.
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


@pytest.fixture(scope="module")
def build(config) -> list[tuple[str, str, str]]:
    return _rules(config["permission"])


@pytest.fixture(scope="module")
def plan(config, build) -> list[tuple[str, str, str]]:
    return build + _rules(config["agent"]["plan"]["permission"])


# ---- plan --------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".opencode/plans/1726-refactor.md",
        "home/u/.local/share/opencode/plans/1726-refactor.md",
        "../../.local/share/opencode/plans/1726-refactor.md",
    ],
)
def test_plan_can_write_its_plan_file(plan, path) -> None:
    """A bare `edit: "deny"` for plan, coming last, used to deny this too."""
    assert _evaluate(plan, "edit", path) == "allow"


def test_plan_cannot_edit_project_files(plan) -> None:
    """The global edit block ("*": "allow") comes after OpenCode's own plan
    restriction, so the config has to restate it."""
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
