from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ocbox.config import ConfigError, load_config
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
        "--agents-json", type=Path, default=None, help="Override the default agents.json."
    )
    parser.add_argument(
        "--skills-dir", type=Path, default=None, help="Override the default skills/ directory."
    )
    parser.add_argument(
        "--no-open", action="store_true", help="Don't automatically open the web UI in a browser."
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

    return run(
        cfg,
        cwd,
        non_interactive=args.yes,
        rebuild=args.rebuild,
        cli_apt=args.apt,
        cli_uv=args.uv,
        agents_json=args.agents_json,
        skills_dir=args.skills_dir,
        host_web_port=args.web_port,
        open_browser=not args.no_open,
    )


if __name__ == "__main__":
    raise SystemExit(main())
