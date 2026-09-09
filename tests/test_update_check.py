import json
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

from ocbox import update_check


def test_parse_version_simple() -> None:
    assert update_check._parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_ignores_v_prefix() -> None:
    assert update_check._parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_stops_at_non_numeric_chunk() -> None:
    """A hatch-vcs dev version like '0.2.0.dev3+g1234abc': '+...' is dropped
    outright, but 'dev3' still has digits worth keeping."""
    assert update_check._parse_version("0.2.0.dev3+g1234abc") == (0, 2, 0, 3)


def test_check_for_update_fetches_and_reports_a_newer_release(tmp_path: Path) -> None:
    with patch.object(update_check, "_fetch_latest_tag", return_value="v9.0.0"):
        latest = update_check.check_for_update(tmp_path, current_version="1.0.0")
    assert latest == "v9.0.0"


def test_check_for_update_returns_none_when_current(tmp_path: Path) -> None:
    with patch.object(update_check, "_fetch_latest_tag", return_value="v1.0.0"):
        latest = update_check.check_for_update(tmp_path, current_version="1.0.0")
    assert latest is None


def test_check_for_update_returns_none_when_newer_than_latest(tmp_path: Path) -> None:
    """A local dev/pre-release build shouldn't nag the user to 'upgrade' backwards."""
    with patch.object(update_check, "_fetch_latest_tag", return_value="v1.0.0"):
        latest = update_check.check_for_update(tmp_path, current_version="1.5.0")
    assert latest is None


def test_check_for_update_swallows_network_failures(tmp_path: Path) -> None:
    with patch.object(update_check, "_fetch_latest_tag", return_value=None):
        latest = update_check.check_for_update(tmp_path, current_version="1.0.0")
    assert latest is None


def test_check_for_update_writes_a_cache_file(tmp_path: Path) -> None:
    with patch.object(update_check, "_fetch_latest_tag", return_value="v2.0.0"):
        update_check.check_for_update(tmp_path, current_version="1.0.0")
    cached = json.loads((tmp_path / "update-check.json").read_text())
    assert cached["latest"] == "v2.0.0"
    assert "checked_at" in cached


def test_check_for_update_uses_the_cache_within_the_interval(tmp_path: Path) -> None:
    (tmp_path / "update-check.json").write_text(
        json.dumps({"checked_at": time.time(), "latest": "v3.0.0"})
    )
    with patch.object(update_check, "_fetch_latest_tag") as mock_fetch:
        latest = update_check.check_for_update(tmp_path, current_version="1.0.0")
    mock_fetch.assert_not_called()
    assert latest == "v3.0.0"


def test_check_for_update_refetches_once_the_cache_is_stale(tmp_path: Path) -> None:
    stale = time.time() - update_check.CHECK_INTERVAL - 1
    (tmp_path / "update-check.json").write_text(
        json.dumps({"checked_at": stale, "latest": "v3.0.0"})
    )
    with patch.object(update_check, "_fetch_latest_tag", return_value="v4.0.0") as mock_fetch:
        latest = update_check.check_for_update(tmp_path, current_version="1.0.0")
    mock_fetch.assert_called_once()
    assert latest == "v4.0.0"


def test_check_for_update_respects_the_opt_out_env_var(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OCBOX_SKIP_UPDATE_CHECK", "1")
    with patch.object(update_check, "_fetch_latest_tag") as mock_fetch:
        latest = update_check.check_for_update(tmp_path, current_version="1.0.0")
    mock_fetch.assert_not_called()
    assert latest is None


def test_fetch_latest_tag_returns_none_on_url_error() -> None:
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
        assert update_check._fetch_latest_tag() is None
