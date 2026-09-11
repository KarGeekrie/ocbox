import re
import stat
from pathlib import Path

from ocbox import project


def test_project_slug_stable_for_same_path(tmp_path: Path) -> None:
    assert project.project_slug(tmp_path) == project.project_slug(tmp_path)


def test_project_slug_differs_for_different_paths(tmp_path: Path) -> None:
    a = tmp_path / "one"
    b = tmp_path / "two"
    a.mkdir()
    b.mkdir()
    assert project.project_slug(a) != project.project_slug(b)


def test_project_slug_includes_directory_basename(tmp_path: Path) -> None:
    myproj = tmp_path / "myproj"
    myproj.mkdir()
    assert project.project_slug(myproj).startswith("myproj-")


def _podman_name_ok(slug: str) -> bool:
    """A slug that podman accepts in an image repo name (lowercase) *and* in a
    volume/container name (`[a-zA-Z0-9][a-zA-Z0-9_.-]*`)."""
    return slug == slug.lower() and re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", slug) is not None


def test_project_slug_normalises_uppercase_and_spaces(tmp_path: Path) -> None:
    """A directory called `MyApp` or `mes projets` must still yield a slug
    podman accepts - uppercase repo names and spaces are rejected outright."""
    for name in ("MyApp", "mes projets", "Développement"):
        d = tmp_path / name
        d.mkdir()
        slug = project.project_slug(d)
        assert _podman_name_ok(slug), f"{name!r} -> {slug!r} not a valid podman name"


def test_project_slug_still_unique_when_prefixes_collapse_together(tmp_path: Path) -> None:
    a = tmp_path / "My App"
    b = tmp_path / "my-app"
    a.mkdir()
    b.mkdir()
    assert project.project_slug(a) != project.project_slug(b)


def test_runtime_dir_reasserts_private_perms_on_an_existing_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """A sandbox can chmod its bind-mounted /run/ocbox; the next run must reset
    it to 0700 so teardown can clear the run's sockets and secrets."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    path = project.runtime_dir("myslug")
    path.chmod(0o500)
    again = project.runtime_dir("myslug")
    assert again == path
    assert _mode(again) == 0o700


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_runtime_dir_created_with_private_permissions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    path = project.runtime_dir("myslug")
    assert path.exists()
    assert _mode(path) == 0o700


def test_runtime_dir_parent_levels_also_private(tmp_path: Path, monkeypatch) -> None:
    """Regression test: Path.mkdir(mode=...) only applies to the leaf it
    creates - intermediate parents (here, the 'ocbox' directory) must not be
    left with loose, umask-based permissions."""
    xdg_runtime = tmp_path / "runtime"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg_runtime))
    xdg_runtime.mkdir(mode=0o700)

    path = project.runtime_dir("myslug")

    ocbox_parent = xdg_runtime / "ocbox"
    assert ocbox_parent.exists()
    assert _mode(ocbox_parent) == 0o700
    assert _mode(path) == 0o700


def test_runtime_dir_fallback_when_no_xdg_runtime_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(project, "_xdg_runtime_dir", lambda: tmp_path / "fallback-root")
    path = project.runtime_dir("myslug")
    assert path.exists()
    assert _mode(path) == 0o700


def test_runtime_dir_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    first = project.runtime_dir("myslug")
    second = project.runtime_dir("myslug")
    assert first == second
    assert second.exists()


def test_state_dir_created(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = project.state_dir("myslug")
    assert path.exists()
    assert path == tmp_path / "state" / "ocbox" / "myslug"
