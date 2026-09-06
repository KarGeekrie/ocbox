import stat
from pathlib import Path

from ocbox import auth


def test_generate_token_is_url_safe_and_reasonably_long() -> None:
    token = auth.generate_token()
    assert len(token) >= 24
    assert all(c.isalnum() or c in "-_" for c in token)


def test_generate_token_is_random() -> None:
    assert auth.generate_token() != auth.generate_token()


def test_write_env_file_permissions_and_content(tmp_path: Path) -> None:
    path = tmp_path / "env"
    auth.write_env_file(path, "secret-token", username="opencode")

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600

    content = path.read_text()
    assert "OPENCODE_SERVER_USERNAME=opencode" in content
    assert "OPENCODE_SERVER_PASSWORD=secret-token" in content


def test_build_web_url() -> None:
    assert auth.build_web_url(12345) == "http://127.0.0.1:12345"


def test_format_connect_banner_contains_credentials() -> None:
    banner = auth.format_connect_banner("http://127.0.0.1:9", "opencode", "tok123")
    assert "http://127.0.0.1:9" in banner
    assert "opencode" in banner
    assert "tok123" in banner
