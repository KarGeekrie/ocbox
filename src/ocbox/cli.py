from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ocbox.config import ConfigError, load_config
from ocbox.podman_client import PodmanError
from ocbox.preflight import PreflightError, run_preflight
from ocbox.sandbox import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocbox",
        description="Run OpenCode inside a rootless-Podman sandbox scoped to the current directory.",
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="Path to conf.py (default: ~/.config/ocbox/conf.py)"
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
    parser.add_argument("--web-port", type=int, default=None, help="Host port for the OpenCode web UI.")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cwd = Path.cwd()

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
        )
    except PodmanError as exc:
        print(f"ocbox: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
