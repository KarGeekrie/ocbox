from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ocbox import project, update_check
from ocbox.config import ConfigError, load_config
from ocbox.podman_client import PodmanError
from ocbox.preflight import PreflightError, run_preflight
from ocbox.sandbox import (
    NoSandboxError,
    OpencodeArgsError,
    check_opencode_args,
    run,
    run_no_sandbox,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocbox",
        description=(
            "Run OpenCode inside a rootless-Podman sandbox "
            "scoped to the current directory."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to conf.py (default: ~/.config/ocbox/conf.py)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the interactive package prompt; use config defaults.",
    )
    parser.add_argument("--apt", nargs="*", default=None, help="Extra apt packages to install.")
    parser.add_argument("--uv", nargs="*", default=None, help="Extra uv/pip packages to install.")
    parser.add_argument(
        "--rebuild", action="store_true", help="Force a rebuild of the project's sandbox image."
    )
    parser.add_argument(
        "--web-port", type=int, default=None, help="Host port for the OpenCode web UI."
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch OpenCode's terminal UI in this terminal instead of the web UI.",
    )
    parser.add_argument(
        "--agents-dir", type=Path, default=None, help="Override the default agents/ directory."
    )
    parser.add_argument(
        "--opencode-config",
        type=Path,
        default=None,
        help="OpenCode settings (models, theme, ...) to mount into the sandbox. "
        "Defaults to ~/.config/ocbox/opencode.jsonc when it exists.",
    )
    parser.add_argument(
        "--skills-dir", type=Path, default=None, help="Override the default skills/ directory."
    )
    parser.add_argument(
        "--detach",
        "-d",
        action="store_true",
        help="Run the web sandbox in the background, surviving this terminal closing. "
        "Web mode only. Track it with `podman ps`/`podman logs`/`podman stop` on the "
        "printed container name.",
    )
    parser.add_argument(
        "--mount",
        action="append",
        type=Path,
        default=None,
        metavar="PATH",
        help="Mount an additional directory into the sandbox, read-write, alongside the "
        "current directory (repeatable). Lands at /mnt/<basename> - basenames must be "
        "distinct across every --mount.",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="Run OpenCode directly on this machine instead of in a sandbox: no Podman, "
        "no network isolation, no conf.py needed. Still installs OpenCode if missing "
        "and wires up opencode-config/'s agents/skills/models. Not compatible with "
        "--tui/--detach/--web-port/--rebuild/--apt/--uv/--yes/--config/--mount, which "
        "are all sandbox-only.",
    )
    return parser


def split_opencode_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Splits ocbox's own arguments from OpenCode's at the first bare `--`.

    Done by hand rather than with argparse.REMAINDER, which only behaves if
    the passthrough is the last positional and swallows unknown ocbox flags
    into it silently - a typo like `--tuo` would be forwarded to OpenCode
    instead of being reported.
    """
    if "--" not in argv:
        return argv, []
    cut = argv.index("--")
    return argv[:cut], argv[cut + 1 :]


def main(argv: list[str] | None = None) -> int:
    ocbox_argv, opencode_args = split_opencode_args(
        list(argv) if argv is not None else sys.argv[1:]
    )
    args = build_parser().parse_args(ocbox_argv)
    cwd = Path.cwd()

    if args.detach and args.tui:
        print(
            "ocbox: --detach doesn't apply to --tui - there'd be nothing attached to "
            "it to make backgrounding meaningful",
            file=sys.stderr,
        )
        return 1

    if args.no_sandbox:
        sandbox_only = {
            "--tui": args.tui,
            "--detach": args.detach,
            "--web-port": args.web_port is not None,
            "--rebuild": args.rebuild,
            "--apt": args.apt is not None,
            "--uv": args.uv is not None,
            "--yes": args.yes,
            "--config": args.config is not None,
            "--mount": args.mount is not None,
        }
        conflicts = [flag for flag, present in sandbox_only.items() if present]
        if conflicts:
            print(
                f"ocbox: --no-sandbox can't be combined with {', '.join(conflicts)} - "
                "there's no container/image for them to apply to",
                file=sys.stderr,
            )
            return 1
    else:
        try:
            check_opencode_args(opencode_args, mode="tui" if args.tui else "web")
        except OpencodeArgsError as exc:
            print(f"ocbox: {exc}", file=sys.stderr)
            return 1

    extra_mounts = [p.resolve() for p in (args.mount or [])]
    for path in extra_mounts:
        if not path.is_dir():
            print(f"ocbox: --mount {path} is not a directory", file=sys.stderr)
            return 1
    names = [p.name for p in extra_mounts]
    if len(names) != len(set(names)):
        print(
            f"ocbox: --mount directories must have distinct names, got {names}",
            file=sys.stderr,
        )
        return 1

    latest = update_check.check_for_update(project.cache_dir())
    if latest:
        print(
            f"ocbox: a newer version is available ({latest}) - "
            "see https://github.com/KarGeekrie/ocbox/releases",
            file=sys.stderr,
        )

    if args.no_sandbox:
        try:
            return run_no_sandbox(
                agents_dir=args.agents_dir,
                user_config=args.opencode_config,
                skills_dir=args.skills_dir,
                opencode_args=opencode_args,
            )
        except NoSandboxError as exc:
            print(f"ocbox: {exc}", file=sys.stderr)
            return 1

    try:
        run_preflight()
    except PreflightError as exc:
        print(f"ocbox: {exc}", file=sys.stderr)
        return 1

    try:
        cfg = load_config(explicit_path=args.config, project_dir=cwd)
    except ConfigError as exc:
        print(f"ocbox: {exc}", file=sys.stderr)
        return 1

    try:
        return run(
            cfg,
            cwd,
            mode="tui" if args.tui else "web",
            non_interactive=args.yes,
            rebuild=args.rebuild,
            cli_apt=args.apt,
            cli_uv=args.uv,
            agents_dir=args.agents_dir,
            user_config=args.opencode_config,
            skills_dir=args.skills_dir,
            host_web_port=args.web_port,
            opencode_args=opencode_args,
            detach=args.detach,
            extra_mounts=extra_mounts,
        )
    except PodmanError as exc:
        print(f"ocbox: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
