"""update_check against real git repositories - a bare "remote", a checkout
cloned from it, and a second clone standing in for the team publishing - so
the fetch/describe behaviour is git's own, not a mock's."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from ocbox import update_check


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, message: str) -> None:
    (repo / "file.txt").write_text(message)
    git(repo, "add", "file.txt")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.com")
    monkeypatch.delenv("OCBOX_SKIP_UPDATE_CHECK", raising=False)


@pytest.fixture
def repos(tmp_path):
    """remote.git, a `team` clone that publishes, and the user's `checkout` at v1.0.0."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    team = tmp_path / "team"
    git(tmp_path, "clone", "-q", str(remote), str(team))
    git(team, "checkout", "-q", "-b", "main")
    commit(team, "first")
    git(team, "tag", "v1.0.0")
    git(team, "push", "-q", "origin", "main", "--tags")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(remote), str(checkout))
    return {"remote": remote, "team": team, "checkout": checkout, "state": tmp_path / "state"}


def publish(repos, message: str, tag: str | None = None) -> None:
    commit(repos["team"], message)
    if tag:
        git(repos["team"], "tag", tag)
    git(repos["team"], "push", "-q", "origin", "main", "--tags")


# ---- parse_version -----------------------------------------------------------


def test_parse_version_simple() -> None:
    assert update_check.parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_ignores_v_prefix() -> None:
    assert update_check.parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_stops_at_non_numeric_chunk() -> None:
    assert update_check.parse_version("0.2.0.dev3+g1234abc") == (0, 2, 0, 3)


# ---- check ---------------------------------------------------------------------


def test_up_to_date_checkout_needs_nothing(repos) -> None:
    status = update_check.check(repos["checkout"], repos["state"])
    assert status.required_tag is None
    assert status.commits_behind == 0
    assert status.current_tag == "v1.0.0"


def test_a_new_release_tag_makes_the_update_required(repos) -> None:
    publish(repos, "release", tag="v1.1.0")

    status = update_check.check(repos["checkout"], repos["state"])

    assert status.required_tag == "v1.1.0"
    assert status.current_tag == "v1.0.0"


def test_untagged_commits_are_only_worth_a_notice(repos) -> None:
    publish(repos, "fix one")
    publish(repos, "fix two")

    status = update_check.check(repos["checkout"], repos["state"])

    assert status.required_tag is None
    assert status.commits_behind == 2
    assert status.upstream == "origin/main"


def test_local_work_past_the_newest_tag_is_not_asked_to_update(repos) -> None:
    commit(repos["checkout"], "local work")
    status = update_check.check(repos["checkout"], repos["state"])
    assert status.required_tag is None


def test_version_comes_from_the_checkout_not_package_metadata(repos) -> None:
    """After an update the checkout's own describe moves on, so a required
    update clears - installed metadata would have kept the old version."""
    publish(repos, "release", tag="v2.0.0")
    assert update_check.check(repos["checkout"], repos["state"]).required_tag == "v2.0.0"

    git(repos["checkout"], "pull", "-q", "--ff-only")

    status = update_check.check(repos["checkout"], repos["state"])
    assert status.required_tag is None
    assert status.current_tag == "v2.0.0"


def test_fetch_happens_at_most_once_per_interval(repos) -> None:
    repos["state"].mkdir()
    (repos["state"] / "update-check.json").write_text(json.dumps({"fetched_at": time.time()}))
    publish(repos, "release", tag="v1.1.0")

    assert update_check.check(repos["checkout"], repos["state"]).required_tag is None

    stale = time.time() - update_check.CHECK_INTERVAL - 1
    (repos["state"] / "update-check.json").write_text(json.dumps({"fetched_at": stale}))
    assert update_check.check(repos["checkout"], repos["state"]).required_tag == "v1.1.0"


def test_a_failed_fetch_never_blocks_by_itself(repos) -> None:
    shutil.rmtree(repos["remote"])

    status = update_check.check(repos["checkout"], repos["state"])

    assert status.required_tag is None
    assert "fetched_at" in json.loads((repos["state"] / "update-check.json").read_text())


def test_a_release_already_fetched_still_blocks_offline(repos) -> None:
    publish(repos, "release", tag="v1.1.0")
    update_check.check(repos["checkout"], repos["state"])
    shutil.rmtree(repos["remote"])

    later = time.time() + update_check.CHECK_INTERVAL + 1
    status = update_check.check(repos["checkout"], repos["state"], now=later)

    assert status.required_tag == "v1.1.0"


def test_opt_out_env_var_skips_everything(repos, monkeypatch) -> None:
    publish(repos, "release", tag="v1.1.0")
    monkeypatch.setenv("OCBOX_SKIP_UPDATE_CHECK", "1")
    assert update_check.check(repos["checkout"], repos["state"]) == update_check.UpdateStatus()


def test_not_a_git_checkout_needs_nothing(tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert update_check.check(plain, tmp_path / "state") == update_check.UpdateStatus()


# ---- update_command ------------------------------------------------------------


def test_update_command_pulls_then_reinstalls_the_checkout(tmp_path) -> None:
    command = update_check.update_command(tmp_path)
    assert command == f"git -C {tmp_path} pull --ff-only && pip install --upgrade -e {tmp_path}"
