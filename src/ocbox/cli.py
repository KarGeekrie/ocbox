from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ocbox import fleet, image, update_check
from ocbox.config import ConfigError, load_config
from ocbox.podman_client import PodmanClient, PodmanError
from ocbox.preflight import PreflightError, run_preflight
from ocbox.sandbox import (
    NoSandboxError,
    OpencodeArgsError,
    SandboxBusyError,
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
        "Defaults to opencode-config/opencode.jsonc.",
    )
    parser.add_argument(
        "--skills-dir", type=Path, default=None, help="Override the default skills/ directory."
    )
    parser.add_argument(
        "--detach",
        "-d",
        action="store_true",
        help="Run the web sandbox in the background, surviving this terminal closing. "
        "Web mode only. Track it with `ocbox list`; stop it with `ocbox stop`.",
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

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "list", help="List currently-running ocbox sandboxes, across all projects."
    )
    stop_parser = subparsers.add_parser("stop", help="Stop a running ocbox sandbox.")
    stop_parser.add_argument(
        "target", help="Container name (ocbox-<slug>), bare slug, or project path (e.g. `.`)."
    )
    attach_parser = subparsers.add_parser(
        "attach", help="Redisplay the connect URL/credentials for a running sandbox."
    )
    attach_parser.add_argument("target", help="Same forms as `ocbox stop`.")
    exec_parser = subparsers.add_parser(
        "exec", help="Open a shell (or run a command) inside a running sandbox."
    )
    exec_parser.add_argument("target", help="Same forms as `ocbox stop`.")
    exec_parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to run (default: sh). Takes everything after <target> verbatim, "
        "so flags like -l reach the command instead of being parsed as ocbox's own.",
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


def cmd_list() -> int:
    try:
        sandboxes = fleet.list_running(PodmanClient())
    except PodmanError as exc:
        print(f"ocbox: {exc}", file=sys.stderr)
        return 1
    if not sandboxes:
        print("ocbox: no sandboxes running")
        return 0
    rows = [("CONTAINER", "PROJECT", "MODE", "URL", "STATUS")]
    rows += [
        (s.container_name, s.workdir or s.slug, s.mode or "-", s.web_url or "-", s.status or "-")
        for s in sandboxes
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)))
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    ocbox_argv, opencode_args = split_opencode_args(raw_argv)
    args = build_parser().parse_args(ocbox_argv)
    if args.command is not None and opencode_args:
        # The subcommands take no OpenCode passthrough, so their `--` is
        # argparse's. Split off, `ocbox exec <target> -- ls -la` - the podman and
        # kubectl habit - opened a bare sh and silently dropped `ls -la`. Parsed
        # again whole, exec keeps its command and a stray argument after
        # `list --` is an error. Deciding this after parsing, not from argv[0],
        # also covers an ocbox option placed first (`ocbox -y exec ...`).
        args = build_parser().parse_args(raw_argv)
        opencode_args = []
    cwd = Path.cwd()

    if args.command == "list":
        return cmd_list()
    if args.command == "stop":
        return fleet.stop_sandbox(PodmanClient(), args.target)
    if args.command == "attach":
        return fleet.attach_sandbox(PodmanClient(), args.target)
    if args.command == "exec":
        return fleet.exec_shell(PodmanClient(), args.target, args.cmd or None)

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

    # These are handed straight to `podman -v <src>:<dst>` / OpenCode, and a
    # relative path without a slash would be read by podman as a *named volume*,
    # not the directory the user meant - so resolve to an absolute path and
    # check the target exists, the same way --mount does below.
    for attr, is_dir in (("agents_dir", True), ("skills_dir", True), ("opencode_config", False)):
        value = getattr(args, attr)
        if value is None:
            continue
        resolved = value.resolve()
        ok = resolved.is_dir() if is_dir else resolved.is_file()
        if not ok:
            kind = "directory" if is_dir else "file"
            flag = "--" + attr.replace("_", "-")
            print(f"ocbox: {flag} {value} is not a {kind}", file=sys.stderr)
            return 1
        setattr(args, attr, resolved)

    extra_mounts = [p.resolve() for p in (args.mount or [])]
    for path in extra_mounts:
        if not path.is_dir():
            print(f"ocbox: --mount {path} is not a directory", file=sys.stderr)
            return 1
        if not path.name:
            print(
                f"ocbox: --mount {path} has no basename to mount it under "
                "(/mnt/<basename>); mount a named subdirectory instead",
                file=sys.stderr,
            )
            return 1
    names = [p.name for p in extra_mounts]
    if len(names) != len(set(names)):
        print(
            f"ocbox: --mount directories must have distinct names, got {names}",
            file=sys.stderr,
        )
        return 1

    repo = image.repo_config_dir().parent
    status = update_check.check(repo, image.repo_local_dir())
    if status.required_tag:
        print(
            f"ocbox: release {status.required_tag} is out and required "
            f"(this checkout is on {status.current_tag or 'no release'}) - update with:\n"
            f"  {update_check.update_command(repo)}",
            file=sys.stderr,
        )
        return 1
    if status.commits_behind:
        print(
            f"ocbox: {status.commits_behind} new commit(s) on {status.upstream}, not part of "
            f"a release yet - optional, to update: {update_check.update_command(repo)}",
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
    except (PodmanError, ConfigError, SandboxBusyError) as exc:
        print(f"ocbox: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
