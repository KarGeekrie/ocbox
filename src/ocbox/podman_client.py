"""Thin subprocess wrapper over the `podman` binary.

Kept deliberately dumb: no argument-building smarts live here, that belongs to
image.py / sandbox.py. This module just knows how to invoke podman and surface
failures.

Short queries are bounded by QUERY_TIMEOUT. Builds, the container itself and
`exec` sessions run as long as they need.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from dataclasses import dataclass

# A query - `image exists`, `ps`, `inspect` - answers in well under a second
# normally. Without a bound, a podman that stops answering hangs every ocbox
# command along with it, `ocbox list` and `ocbox stop` included.
QUERY_TIMEOUT = 60


class PodmanError(Exception):
    """Raised when a podman invocation fails."""


def _timeout_message(binary: str, args: list[str]) -> str:
    command = " ".join([binary, *args])
    return f"`{command}` did not answer within {QUERY_TIMEOUT}s - podman looks stuck"


@dataclass
class PodmanClient:
    binary: str = "podman"

    def run_capture(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=QUERY_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise PodmanError(_timeout_message(self.binary, args)) from exc
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

    def _query(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """A short call whose exit code is the answer, bounded by QUERY_TIMEOUT."""
        try:
            return subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=QUERY_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise PodmanError(_timeout_message(self.binary, args)) from exc
        except OSError as exc:
            raise PodmanError(f"Could not execute `{self.binary}`: {exc}") from exc

    def image_exists(self, tag: str) -> bool:
        return self._query(["image", "exists", tag]).returncode == 0

    def image_label(self, tag: str, label: str) -> str | None:
        """Returns the value of `label` on `tag`, or None if the image or
        label doesn't exist."""
        result = self._query(
            ["inspect", "--format", f'{{{{ index .Config.Labels "{label}" }}}}', tag]
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
        no_cache: bool = False,
    ) -> None:
        args = ["build", "-t", tag, "-f", "-"]
        if not network:
            args += ["--network", "none"]
        if no_cache:
            args.append("--no-cache")
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
        """Best effort, like before: callers check afterwards whether the
        container is gone. Bounded too, so a stuck podman can't hang a teardown."""
        with contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run(
                [self.binary, "stop", "-t", str(timeout), name],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout + QUERY_TIMEOUT,
            )

    def container_exists(self, name: str) -> bool:
        return self._query(["container", "exists", name]).returncode == 0

    def list_containers(self, *, label: str | None = None) -> list[dict]:
        """Running containers, as `podman ps` reports them - the raw dicts
        (`Names` a list, `Labels` a dict, `Status` a human string like
        "Up 5 minutes"; verified against real podman 4.9.3 output), not a
        shape this wrapper invents. `label` is an existence filter ("key" or
        "key=value") narrowing to containers carrying it.

        Raises PodmanError on failure (unlike image_exists/stop): this backs
        real operations (`ocbox list`, the startup warning) that should hear
        about a broken podman rather than silently see "nothing running".
        """
        args = ["ps", "--format", "json"]
        if label:
            args += ["--filter", f"label={label}"]
        result = self.run_capture(args)
        try:
            return json.loads(result.stdout) if result.stdout.strip() else []
        except json.JSONDecodeError as exc:
            raise PodmanError(f"could not parse `podman ps` output: {exc}") from exc

    def exec_interactive(self, name: str, cmd: list[str]) -> int:
        """Runs `cmd` inside a running container, inheriting this process's
        stdio so the user gets a real terminal, and returns its exit code.

        `-t` only when stdin is a TTY: podman refuses to allocate one
        otherwise, so asking for it unconditionally would turn a piped or
        cron-driven `ocbox exec` into an error about the input device instead
        of just running the command.
        """
        flags = ["-it"] if sys.stdin.isatty() else ["-i"]
        try:
            return subprocess.call([self.binary, "exec", *flags, name, *cmd])
        except OSError as exc:
            raise PodmanError(f"Could not execute `{self.binary}`: {exc}") from exc
