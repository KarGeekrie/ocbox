from unittest.mock import MagicMock

from ocbox import image


def test_packages_fingerprint_stable_regardless_of_order() -> None:
    a = image.packages_fingerprint(["git", "curl"], ["ruff"])
    b = image.packages_fingerprint(["curl", "git"], ["ruff"])
    assert a == b


def test_packages_fingerprint_differs_for_different_packages() -> None:
    a = image.packages_fingerprint(["git"], [])
    b = image.packages_fingerprint(["curl"], [])
    assert a != b


def test_ensure_base_image_skips_build_if_present() -> None:
    podman = MagicMock()
    podman.image_exists.return_value = True
    image.ensure_base_image(podman, "ocbox/base:latest")
    podman.build.assert_not_called()


def test_ensure_base_image_builds_if_missing() -> None:
    podman = MagicMock()
    podman.image_exists.return_value = False
    image.ensure_base_image(podman, "ocbox/base:latest")
    podman.build.assert_called_once()
    args, kwargs = podman.build.call_args
    assert args[1] == "ocbox/base:latest"


def test_build_project_image_generates_containerfile_with_packages(tmp_path) -> None:
    podman = MagicMock()
    image.build_project_image(
        podman, "ocbox/base:latest", "ocbox/project-x:latest", ["git", "curl"], ["ruff"], tmp_path
    )
    podman.build.assert_called_once()
    containerfile_text = podman.build.call_args[0][0]
    assert "FROM ocbox/base:latest" in containerfile_text
    assert "apt-get install" in containerfile_text
    assert "git" in containerfile_text and "curl" in containerfile_text
    assert "uv pip install --system ruff" in containerfile_text


def test_build_project_image_no_extra_layers_when_no_packages(tmp_path) -> None:
    podman = MagicMock()
    image.build_project_image(
        podman, "ocbox/base:latest", "ocbox/project-x:latest", [], [], tmp_path
    )
    containerfile_text = podman.build.call_args[0][0]
    assert containerfile_text.strip() == "FROM ocbox/base:latest"


def test_build_project_image_quotes_package_names(tmp_path) -> None:
    podman = MagicMock()
    image.build_project_image(
        podman, "ocbox/base:latest", "ocbox/project-x:latest", ["pkg; rm -rf /"], [], tmp_path
    )
    containerfile_text = podman.build.call_args[0][0]
    assert "'pkg; rm -rf /'" in containerfile_text
