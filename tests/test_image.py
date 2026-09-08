from unittest.mock import MagicMock

from ocbox import image


def test_packages_fingerprint_stable_regardless_of_order() -> None:
    a = image.packages_fingerprint(["git", "curl"], ["ruff"], "ocbox/base:latest", "abc123")
    b = image.packages_fingerprint(["curl", "git"], ["ruff"], "ocbox/base:latest", "abc123")
    assert a == b


def test_packages_fingerprint_differs_for_different_packages() -> None:
    a = image.packages_fingerprint(["git"], [], "ocbox/base:latest", "abc123")
    b = image.packages_fingerprint(["curl"], [], "ocbox/base:latest", "abc123")
    assert a != b


def test_packages_fingerprint_differs_for_different_base_image() -> None:
    a = image.packages_fingerprint(["git"], [], "ocbox/base:latest", "abc123")
    b = image.packages_fingerprint(["git"], [], "custom/base:1.0", "abc123")
    assert a != b


def test_packages_fingerprint_differs_when_base_content_changes() -> None:
    """A rebuilt/updated base image (different content hash under the same
    tag name) must invalidate cached project images too."""
    a = image.packages_fingerprint(["git"], [], "ocbox/base:latest", "abc123")
    b = image.packages_fingerprint(["git"], [], "ocbox/base:latest", "def456")
    assert a != b


def test_containerfile_fingerprint_is_deterministic() -> None:
    assert image.containerfile_fingerprint() == image.containerfile_fingerprint()


def test_ensure_base_image_skips_build_if_present_and_hash_matches() -> None:
    podman = MagicMock()
    podman.image_exists.return_value = True
    podman.image_label.return_value = image.containerfile_fingerprint()
    image.ensure_base_image(podman, "ocbox/base:latest")
    podman.build.assert_not_called()


def test_ensure_base_image_builds_if_missing() -> None:
    podman = MagicMock()
    podman.image_exists.return_value = False
    image.ensure_base_image(podman, "ocbox/base:latest")
    podman.build.assert_called_once()
    args, _kwargs = podman.build.call_args
    assert args[1] == "ocbox/base:latest"
    assert image.CONTAINERFILE_HASH_LABEL in args[0]


def test_ensure_base_image_rebuilds_when_content_hash_stale() -> None:
    """Simulates an ocbox upgrade: the tag already exists locally (built by
    an older version) but its recorded content hash doesn't match the
    currently-packaged Containerfile/relay.py/entrypoint.sh - must rebuild
    rather than silently keep using the stale cached image forever."""
    podman = MagicMock()
    podman.image_exists.return_value = True
    podman.image_label.return_value = "some-old-hash-from-a-previous-version"
    image.ensure_base_image(podman, "ocbox/base:latest")
    podman.build.assert_called_once()


def test_ensure_base_image_rebuilds_when_label_missing() -> None:
    """An image built before this labeling existed at all has no label -
    must rebuild once to start tracking it, not treat missing as a match."""
    podman = MagicMock()
    podman.image_exists.return_value = True
    podman.image_label.return_value = None
    image.ensure_base_image(podman, "ocbox/base:latest")
    podman.build.assert_called_once()


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
