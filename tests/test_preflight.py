import json
import subprocess
from unittest.mock import patch

import pytest

from ocbox.preflight import (
    PreflightError,
    check_podman_installed,
    check_rootless,
    check_subuid_subgid,
)


def test_check_podman_installed_missing() -> None:
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(PreflightError, match="not installed"),
    ):
        check_podman_installed()


def test_check_podman_installed_present() -> None:
    with patch("shutil.which", return_value="/usr/bin/podman"), patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout="podman version 5.0.0\n"),
    ):
        assert "5.0.0" in check_podman_installed()


def test_check_rootless_true() -> None:
    payload = json.dumps({"host": {"security": {"rootless": True}}})
    with patch(
        "subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=payload)
    ):
        check_rootless()  # should not raise


def test_check_rootless_false() -> None:
    payload = json.dumps({"host": {"security": {"rootless": False}}})
    with (
        patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=payload)),
        pytest.raises(PreflightError, match="rootless"),
    ):
        check_rootless()


def test_check_subuid_subgid_missing(tmp_path) -> None:
    with patch("ocbox.preflight.Path") as mock_path:

        def _factory(p):
            fake = tmp_path / p.lstrip("/")
            return fake

        mock_path.side_effect = _factory
        with pytest.raises(PreflightError, match="subuid"):
            check_subuid_subgid()


def test_check_subuid_subgid_present(tmp_path, monkeypatch) -> None:
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    monkeypatch.setenv("USER", "testuser")
    subuid.write_text("testuser:100000:65536\n")
    subgid.write_text("testuser:100000:65536\n")

    with patch("ocbox.preflight.Path") as mock_path:
        mapping = {"/etc/subuid": subuid, "/etc/subgid": subgid}
        mock_path.side_effect = lambda p: mapping.get(p, tmp_path / p.lstrip("/"))
        check_subuid_subgid()  # should not raise
