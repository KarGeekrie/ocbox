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
