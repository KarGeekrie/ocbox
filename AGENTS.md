# AGENTS.md

Instructions for AI coding agents working in this repository.

## What this project is

`ocbox` is a Python CLI that sandboxes the [OpenCode](https://opencode.ai)
agent inside a **rootless Podman** container scoped to the current project
directory - either through OpenCode's web UI (default) or its terminal UI
(`--tui`). See `README.md` for the user-facing docs and architecture
overview; read it before making changes, it explains the isolation design
in depth.

Don't confuse this repo-level `AGENTS.md` with `opencode-config/agents/` -
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
  that validated this) - see "Verification history" below before trusting
  it as-is.
- `data/entrypoint.sh` is POSIX `sh`, not bash - keep it that way (it runs
  inside a minimal container image). Test changes to it via the integration
  suite, not just `sh -n`.
- The parts of OpenCode's CLI/config surface that ocbox depends on have been
  verified against opencode 1.18.29 - see "Verification history" below for
  what was checked and how. Two things to know before changing any of it:
  OpenCode's published schema is at
  <https://opencode.ai/config.json>, and it **ignores config keys it doesn't
  recognise** rather than rejecting them, so a wrong key name silently
  disables a feature instead of failing. Check with `opencode debug config`
  (what config survived) and `opencode debug skill` (what was discovered)
  from inside a sandbox, not by reading the code. If you introduce a new
  assumption you haven't checked that way, mark it and say so.

## Verification history

### Verified against real OpenCode

The details of OpenCode's CLI/config surface that ocbox depends on were
originally best-effort guesses. All four have since been checked against
opencode 1.18.29 and its published schema:

- **`opencode.json` discovery**: `OPENCODE_CONFIG=<path>` is honoured - the
  config ocbox mounts there shows up in `opencode debug config`.
- **Skills/agents schema**: `skills` is an object (`paths`/`urls`), and
  `agent` is an object keyed by agent name - neither is a list. Skills are
  `<dir>/<name>/SKILL.md` with `name`/`description` frontmatter. Earlier
  versions of ocbox emitted `skillsDir` and a list-valued `agents`, neither
  of which exists; OpenCode dropped both silently, so the mounted skills and
  agents never reached it.
- **`opencode web` auto-opens a browser**: it spawns `xdg-open`, absent from
  the sandbox image, for a container-internal URL that is meaningless on the
  host. ocbox runs `opencode serve` instead - headless, byte-for-byte the
  same UI - and prints the URL for you to open.
- **Bare `opencode` is the TUI**: `opencode --help` lists it as the default
  command, which is what `--tui` relies on.
- **`instructions` does not work - use `AGENTS.md`**: ocbox briefly shipped
  an `opencode-config/instructions/` directory wired to OpenCode's
  `instructions` config key. The key is real and survives
  `opencode debug config`, but OpenCode's V2 docs state it "currently parses
  and retains this field but does not resolve its entries into instruction
  sources", so its contents "do not reach the model yet"
  (<https://opencode.ai/v2/docs/instructions>). The directory and the
  `--instructions-dir` flag were removed; standing instructions belong in
  `~/.config/opencode/AGENTS.md` or the project's own `AGENTS.md`, generated
  by `/init` inside an OpenCode session. A textbook case of the silent no-op
  this file warns about: it looked configured and did nothing.
- **Global and project `AGENTS.md` are combined, not either/or**: checked by
  pointing OpenCode at a stub OpenAI-compatible server that records every
  request body, then searching those bodies for a marker placed in each file.
  With both files present, both markers reach the model; with only the global
  one, it still does. `/docs/rules/`'s "the first matching file wins in each
  category" means `AGENTS.md` beats `CLAUDE.md` *in the same location*, not
  that a project file shadows the global one - the V2 docs say it outright:
  "OpenCode combines the files and does not resolve conflicts between them".
  ocbox ships the team's global file as `opencode-config/AGENTS.md`.
- **`OPENCODE_CONFIG_DIR`**, which the whole of `--no-sandbox`'s config wiring
  rests on: agents, skills and `opencode.jsonc` all load from a directory given
  this way, a config layered over it with `OPENCODE_CONFIG` merges rather than
  replacing it, and an `AGENTS.md` inside it is sent as the global one (same
  request-recording check). OpenCode also writes into that directory - a
  `.gitignore`, then `node_modules` and `package.json` once plugins load -
  which is why ocbox assembles it in its own state dir, not in the checkout.
- **What `--no-sandbox` still takes from the user's own
  `~/.config/opencode/`**: OpenCode reads that directory alongside
  `OPENCODE_CONFIG_DIR` rather than instead of it - its DEBUG log lists both.
  With a marker in each file under a throwaway `HOME`: the user's
  `opencode.jsonc` is merged, the `OPENCODE_CONFIG_DIR` copy winning on a
  conflicting key (`share` set both ways resolved to the team's value) while
  user-only keys are kept; the user's `agents/` are merged; the user's
  `AGENTS.md` is not sent at all, replaced by the one in `OPENCODE_CONFIG_DIR`.
  An earlier README claimed the user's directory was neither read nor used in
  this mode - wrong for everything except `AGENTS.md`.
- **OpenCode writes into the host's `~/.config/opencode/` on its own**: at
  startup it installs `@opencode-ai/plugin` there (`package.json`,
  `package-lock.json`, `node_modules/`, ~63 MB) and into whatever
  `OPENCODE_CONFIG_DIR` names. Reproduced under a fresh throwaway `HOME`, and a
  known upstream behaviour (anomalyco/opencode#30908, #27676) with no
  documented off switch. Sandboxes are unaffected - no network, and no
  `package.json`/`node_modules` in their home volumes. Tried: pointing the
  OpenCode process's `XDG_CONFIG_HOME` at an ocbox-owned directory. The user's
  own directory then stays byte-for-byte unchanged, their personal agents and
  models stop merging in, and the install lands in the ocbox-owned directory.
  Not adopted, since it also changes `XDG_CONFIG_HOME` for every tool OpenCode
  spawns; left as a decision.
- **Open: `opencode run` on the host can stall right after `init`.** Seen as
  ~11 log lines ending at `init`, then silence, with no request reaching the
  LLM (confirmed by a recording stub) until killed. It happened in all three
  runs that started without the plugin dependencies present, and once right
  after a killed run; in none of the runs that started with them present,
  including two under a fresh `HOME` seeded with a working copy. Ruled
  out: an incomplete install (a stalled run's `node_modules` was identical to a
  working one), inotify limits (9 of 128 instances), and an IPv6 black hole
  (no IPv6 route here, but connections fail in milliseconds). Cause unknown.
- **Testing on a stock Ollama truncates OpenCode's prompt**: Ollama logs
  `truncating input prompt limit=2048 prompt=4512`, so with the default
  `num_ctx` the model sees only part of the system prompt, `AGENTS.md`
  included, and a cold model on CPU takes ~90 s per request. The team's models
  declare 200k contexts, so this only matters for local testing: judge what
  OpenCode *sends* from a recorded request body, not from the model's answer.

Two observables look usable for "does this reach the model?" and are not: the
token counts in `opencode run --format json` (against Ollama they report the
context size, 2048, whatever the prompt), and `opencode export <session>`
(messages only, no system prompt). A stub LLM that records request bodies is
the reliable check.

Worth knowing when changing any of this: OpenCode ignores config keys it
doesn't recognise instead of rejecting them, so a wrong key name disables a
feature with nothing in the output to say so. `opencode debug config` prints
what actually survived, and `opencode debug skill` lists what was discovered.

### Verified against real rootless Podman

`tests/integration/test_end_to_end.py` runs `ocbox`'s actual sandboxing code
(`sandbox.py`, `network.py`, the real `relay.py`/`entrypoint.sh`) against a
real rootless Podman container - it swaps in a stand-in for the OpenCode
binary itself (see `fixtures/fake_opencode.py`) since it doesn't assume
network access to opencode.ai, but everything else is the genuine mechanism.
Confirmed working this way:

- `--network=none` really blocks arbitrary egress from inside the container.
- The Unix-socket relay bridge correctly proxies both directions: the "LLM"
  reachable from inside a network-isolated container, and the web UI
  reachable from the host browser.
- HTTP Basic Auth gating (`OPENCODE_SERVER_USERNAME`/`_PASSWORD`) actually
  rejects missing/wrong credentials and accepts the right ones.
- `--userns=keep-id` correctly maps container-written files in `/workspace`
  to the invoking host user, not root or an arbitrary subuid.
- `--tui` mode's real `entrypoint.sh` branch (exec straight into OpenCode, no
  web relay/auth) runs correctly and can still reach the LLM relay from
  inside the network-isolated container.
- `BASE_OS` switching: selecting a different distro under the same image
  tag correctly triggers a rebuild (verified for `debian`/`ubuntu`, whose
  build mechanics are otherwise identical - `apt`, same Containerfile
  shape); re-selecting the same distro doesn't rebuild. The `rocky`
  Containerfile itself (the actual `dnf install` line) has **not** been
  built against a real Rocky mirror - the dev sandbox this was validated in
  had no route to dl.rockylinux.org. Verify it builds before relying on it.

**Gotcha found along the way**: rootless `podman build` sets up build-time
networking (via slirp4netns) by default even when the build itself does no
networking, and that setup needs read/write access to `/dev/net/tun`. On a
host (or nested container) where that device isn't accessible to your user,
`podman build` fails outright - pass `network=False` to
`PodmanClient.build()` for build phases that don't need network (as the
test fixtures do), and expect the real `image.build_project_image()` /
`image.ensure_base_image()` (which *do* need network for apt/uv/curl) to
need `/dev/net/tun` access fixed at the host level instead.

## Git / PR conventions

- Commit messages: explain *why*, matching the existing history's style
  (see `git log`) - what problem motivated the change, not a restatement of
  the diff.
- This repo has no CI configured yet - your local `pytest` + `ruff check`
  run is the only gate. Don't skip it.
