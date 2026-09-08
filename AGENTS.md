# AGENTS.md

Instructions for AI coding agents working in this repository.

## What this project is

`ocbox` is a Python CLI that sandboxes the [OpenCode](https://opencode.ai)
agent inside a **rootless Podman** container scoped to the current project
directory - either through OpenCode's web UI (default) or its terminal UI
(`--tui`). See `README.md` for the user-facing docs and architecture
overview; read it before making changes, it explains the isolation design
in depth.

Don't confuse this repo-level `AGENTS.md` with `src/ocbox/data/agents/` -
that directory holds *runtime* agent definitions ocbox mounts into the
sandboxes it creates, for OpenCode itself. They're unrelated.

## Setup

```sh
pip install -e ".[dev]"
```

No other setup is required for unit tests. Real Podman is only needed for
the integration suite (see below) - if unavailable, unit tests are the full
signal.

## Running tests

```sh
pytest                                              # unit tests - fast, no podman needed
RUN_PODMAN_INTEGRATION=1 pytest tests/integration    # real rootless Podman required
ruff check src tests                                 # lint
```

Always run both `pytest` and `ruff check src tests` before considering a
change done. Run the integration suite too whenever you touch `sandbox.py`,
`network.py`, `podman_client.py`, `image.py`, or `data/{relay.py,
entrypoint.sh,Containerfile}` - those are exactly the pieces the mocked unit
tests can't fully validate (real namespace/relay/auth behavior).

If Podman isn't installed and you need to validate against it: `apt-get
install -y podman` (or `dnf install -y podman`) works standalone, no other
system config needed on a reasonably modern Linux host. If the sandbox
you're running in has no access to public container registries (some CI/dev
sandboxes block them), you can still validate the mechanism without a real
registry: build a minimal local rootfs with `debootstrap` and `podman
import` it, then `podman tag` it as whatever base image a Containerfile
references so `podman build` resolves it locally instead of pulling. This is
exactly how the integration tests were validated during initial development
- see the git history around the "Add real Podman integration test" and
"Add --tui" commits for the full recipe if you need to reproduce it.

## Code conventions

- **Stdlib-only runtime dependencies**, deliberately, to minimize the
  trusted supply chain for a tool that runs container/network operations.
  Don't add a dependency without a strong reason; if you must, it goes in
  `[project.optional-dependencies]`, never `dependencies`.
- Every module under `src/ocbox/` has a corresponding `tests/test_<module>.py`
  covering it directly (not just indirectly through `cli.py`/`sandbox.py`).
  Keep it that way - a previous review found several modules (`packages.py`,
  `network.py`, `project.py`, `cli.py`, `sandbox.py`'s own `run()`
  orchestration) had zero direct tests, which is exactly how a real bug in
  `packages.py`'s `--apt`/`--uv` handling went unnoticed. When you add a new
  module or a non-trivial function, add its test file/cases in the same
  change.
- Comments explain *why*, not *what* - see the top-level style guide this
  agent follows. This repo leans on comments specifically to flag unverified
  assumptions about OpenCode's real CLI/config surface (grep for "NOTE:",
  "unverified", "open question" across `src/`) - preserve those markers
  when you touch nearby code, and add one if you introduce a new assumption
  about OpenCode's behavior that hasn't been checked against its real docs.
- Ruff config lives in `pyproject.toml` (line-length 100, py311 target). No
  separate formatter is configured - match the existing style.

## Architecture pointers

- `sandbox.py` is the orchestration core: `RunPlan` (what a `podman run`
  invocation needs), `build_podman_run_argv()` (pure argv construction, unit
  tested extensively), and `run()` (the actual end-to-end flow, tested via
  heavy mocking in `test_sandbox_run.py` since it has real side effects).
- `network.py` + `data/relay.py` are the network-isolation mechanism:
  `--network=none` on the container plus a pair of stdlib TCP<->Unix-socket
  relay processes bridging exactly the local LLM (egress) and the web UI
  (ingress, web mode only). Don't add any other network path without a
  deliberate design discussion - the whole point of this project is that
  nothing else is reachable.
- `image.py` builds and caches sandbox images, with a content-hash `LABEL`
  on the base image so an ocbox upgrade (changed `Containerfile`/`relay.py`/
  `entrypoint.sh`) triggers a rebuild instead of silently reusing a stale
  cached image forever. If you change any file under `src/ocbox/data/`,
  this rebuild-triggering is why you don't need to bump a version number by
  hand. The base OS is selectable (`BASE_OS` in `conf.py` -
  debian/ubuntu/rocky) - each distro's Containerfile lives under
  `data/distros/<name>/Containerfile` and shares the same `relay.py`/
  `entrypoint.sh` (COPY'd from the shared top-level `data/` context
  regardless of which distro Containerfile is in use). `image.DISTROS` maps
  each name to its package manager (`apt` or `dnf`), which
  `build_project_image()` uses to install a project's extra packages. When
  adding a distro variant, register it in `image.DISTROS` and add its
  Containerfile - `containerfile_fingerprint()`/`ensure_base_image()` pick
  the rest up automatically. The `rocky` variant was written but never
  built against a real Rocky mirror (network-blocked in the dev sandbox
  that validated this) - see the README's "Verified against real rootless
  Podman" section before trusting it as-is.
- `data/entrypoint.sh` is POSIX `sh`, not bash - keep it that way (it runs
  inside a minimal container image). Test changes to it via the integration
  suite, not just `sh -n`.
- The parts of OpenCode's CLI/config surface that ocbox depends on have been
  verified against opencode 1.18.29 - see `README.md`'s "Verified against
  real OpenCode" section for what was checked and how. Two things to know
  before changing any of it: OpenCode's published schema is at
  <https://opencode.ai/config.json>, and it **ignores config keys it doesn't
  recognise** rather than rejecting them, so a wrong key name silently
  disables a feature instead of failing. Check with `opencode debug config`
  (what config survived) and `opencode debug skill` (what was discovered)
  from inside a sandbox, not by reading the code. If you introduce a new
  assumption you haven't checked that way, mark it and say so.

## Git / PR conventions

- Commit messages: explain *why*, matching the existing history's style
  (see `git log`) - what problem motivated the change, not a restatement of
  the diff.
- This repo has no CI configured yet - your local `pytest` + `ruff check`
  run is the only gate. Don't skip it.
