"""Base image bootstrap and per-project derived image layering extra apt/uv
packages requested interactively via packages.py.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import shlex
from pathlib import Path

from ocbox import __version__, update_check
from ocbox.podman_client import PodmanClient

BASE_FINGERPRINT_LABEL = "ocbox.base_fingerprint"

# Each entry names the packaged Containerfile variant under data/distros/
# and the package manager `build_project_image` uses to install a project's
# requested extra packages on top of it.
DISTROS = {
    "debian": "apt",
    "ubuntu": "apt",
    "rocky": "dnf",
}
DEFAULT_BASE_OS = "ubuntu"


def data_dir() -> Path:
    return Path(str(importlib.resources.files("ocbox.data")))


def repo_config_dir() -> Path:
    """opencode-config/ at the repo root: agents/skills/opencode.jsonc meant to
    be seen and edited directly in a checkout, unlike data_dir()'s contents
    (relay.py, entrypoint.sh, per-distro Containerfiles), which are internal.

    Only resolvable for the (currently only supported - see README "Setup")
    editable-install-from-checkout workflow: three parents up from this file
    (src/ocbox/image.py) is the repo root.
    """
    path = Path(__file__).resolve().parents[2] / "opencode-config"
    if not path.is_dir():
        raise FileNotFoundError(
            f"Expected {path} (agents/skills/opencode.jsonc) next to a checkout "
            "of ocbox - install with `pip install -e .` from a clone, not a "
            "built wheel."
        )
    return path


def repo_local_dir() -> Path:
    """.ocbox/ at the repo root: what ocbox itself writes for --no-sandbox - an
    OpenCode binary it had to install, the config directory it assembles.

    Kept inside the checkout and gitignored, so ocbox doesn't scatter state
    through the user's home. Not created here; callers create what they need.
    """
    return repo_config_dir().parent / ".ocbox"


def _distro_containerfile_path(base_os: str) -> Path:
    if base_os not in DISTROS:
        raise ValueError(
            f"Unknown BASE_OS {base_os!r}; supported: {', '.join(sorted(DISTROS))}"
        )
    return data_dir() / "distros" / base_os / "Containerfile"


def ocbox_revision() -> str:
    """Which ocbox is running: this checkout's commit, or the package version
    outside a git checkout."""
    return update_check.revision(Path(__file__).resolve().parents[2]) or __version__


def base_fingerprint(base_os: str = DEFAULT_BASE_OS) -> str:
    """Identifies what a base image was built from: the selected distro's
    Containerfile, relay.py, entrypoint.sh - and the ocbox revision.

    The revision is what makes an ocbox update rebuild the images even when
    none of those files changed. The Containerfiles install uv and OpenCode
    unpinned, at whatever version is current when they are built, and an ocbox
    update is when the team moves to newer ones - see ensure_base_image().
    """
    payload = _distro_containerfile_path(base_os).read_bytes()
    payload += (data_dir() / "relay.py").read_bytes()
    payload += (data_dir() / "entrypoint.sh").read_bytes()
    payload += ocbox_revision().encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def ensure_base_image(podman: PodmanClient, tag: str, base_os: str = DEFAULT_BASE_OS) -> None:
    """Builds the base image (chosen distro + uv + OpenCode + relay.py) unless
    one built from the same base_fingerprint() is already there - so updating
    ocbox, changing its image files, or switching BASE_OS rebuilds it, and
    project images follow through packages_fingerprint().
    """
    fingerprint = base_fingerprint(base_os)
    if podman.image_exists(tag) and (
        podman.image_label(tag, BASE_FINGERPRINT_LABEL) == fingerprint
    ):
        return
    containerfile = _distro_containerfile_path(base_os).read_text()
    containerfile += f"\nLABEL {BASE_FINGERPRINT_LABEL}={fingerprint}\n"
    # Without the layer cache: the `curl ... | bash` steps read the same as last
    # time, so a cached build would reuse their layers and reinstall the very
    # uv and OpenCode the rebuild is meant to refresh.
    podman.build(containerfile, tag, context_dir=str(data_dir()), no_cache=True)


def packages_fingerprint(
    apt_pkgs: list[str], uv_pkgs: list[str], base_image: str, base_fingerprint: str
) -> str:
    """Fingerprints everything that determines a project image's contents:
    the requested extra packages, which base image it's built from, and that
    base image's own content (so a rebuilt/updated base image - see
    ensure_base_image() - transitively invalidates project images too).
    """
    payload = (
        "base:" + base_image
        + "|basehash:" + base_fingerprint
        + "|apt:" + ",".join(sorted(apt_pkgs))
        + "|uv:" + ",".join(sorted(uv_pkgs))
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def image_exists(podman: PodmanClient, tag: str) -> bool:
    return podman.image_exists(tag)


def _system_package_install_line(base_os: str, pkgs: list[str]) -> str:
    pkg_args = " ".join(shlex.quote(p) for p in pkgs)
    package_manager = DISTROS.get(base_os, "apt")
    if package_manager == "dnf":
        return f"RUN dnf install -y {pkg_args} && dnf clean all"
    return (
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        f"{pkg_args} && rm -rf /var/lib/apt/lists/*"
    )


def build_project_image(
    podman: PodmanClient,
    base_tag: str,
    project_tag: str,
    apt_pkgs: list[str],
    uv_pkgs: list[str],
    empty_context: Path,
    base_os: str = DEFAULT_BASE_OS,
) -> None:
    """Layers the requested extra packages onto base_tag, tagged as project_tag.

    The extra "apt" packages are installed with the package manager that
    matches `base_os` (apt on Debian/Ubuntu, dnf on Rocky) - package names
    still need to be valid for whichever distro is actually selected.

    Runs with normal (non-isolated) networking - this is the only phase of
    ocbox's lifecycle that touches the open internet, and it never overlaps
    with the sandboxed run itself. `empty_context` must be an existing,
    otherwise-empty directory (podman build requires a build context even
    when nothing is COPYed).
    """
    lines = [f"FROM {base_tag}"]
    if apt_pkgs:
        lines.append(_system_package_install_line(base_os, apt_pkgs))
    if uv_pkgs:
        pkg_args = " ".join(shlex.quote(p) for p in uv_pkgs)
        # --break-system-packages: Debian and Ubuntu mark their system Python as
        # externally managed (PEP 668), and uv refuses --system installs there
        # without it - which left --uv/EXTRA_UV_DEFAULT failing the image build
        # on the default BASE_OS. The container is disposable and owns that
        # interpreter, so the protection it asks for doesn't apply here.
        lines.append(f"RUN uv pip install --system --break-system-packages {pkg_args}")
    containerfile = "\n".join(lines) + "\n"
    podman.build(containerfile, project_tag, context_dir=str(empty_context))
