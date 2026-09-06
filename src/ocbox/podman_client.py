"""Thin subprocess wrapper over the `podman` binary.

Kept deliberately dumb: no argument-building smarts live here, that belongs to
image.py / sandbox.py. This module just knows how to invoke podman and surface
failures.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class PodmanError(Exception):
    """Raised when a podman invocation fails."""


@dataclass
class PodmanClient:
    binary: str = "podman"

    def run_capture(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.binary, *args], capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as exc:
            raise PodmanError(
                f"`{self.binary} {' '.join(args)}` failed (exit {exc.returncode}):\n{exc.stderr}"
            ) from exc
        except OSError as exc:
            raise PodmanError(f"Could not execute `{self.binary}`: {exc}") from exc

    def popen(self, args: list[str], **kwargs) -> subprocess.Popen:
        try:
            return subprocess.Popen([self.binary, *args], **kwargs)
        except OSError as exc:
            raise PodmanError(f"Could not execute `{self.binary}`: {exc}") from exc

    def image_exists(self, tag: str) -> bool:
        result = subprocess.run(
            [self.binary, "image", "exists", tag], capture_output=True, text=True
        )
        return result.returncode == 0

    def image_label(self, tag: str, label: str) -> str | None:
        """Returns the value of `label` on `tag`, or None if the image or
        label doesn't exist."""
        result = subprocess.run(
            [
                self.binary,
                "inspect",
                "--format",
                f'{{{{ index .Config.Labels "{label}" }}}}',
                tag,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    def build(
        self,
        containerfile_text: str,
        tag: str,
        *,
        context_dir: str = ".",
        network: bool = True,
    ) -> None:
        args = ["build", "-t", tag, "-f", "-"]
        if not network:
            args += ["--network", "none"]
        args.append(context_dir)
        try:
            subprocess.run(
                [self.binary, *args],
                input=containerfile_text,
                text=True,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise PodmanError(f"podman build failed for tag {tag}:\n{exc.stderr}") from exc

    def stop(self, name: str, timeout: int = 10) -> None:
        subprocess.run(
            [self.binary, "stop", "-t", str(timeout), name],
            capture_output=True,
            text=True,
        )
