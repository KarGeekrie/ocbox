# ocbox

Rootless-Podman sandbox for running the [OpenCode](https://opencode.ai) agent.

`ocbox` launches OpenCode inside a Podman container scoped to your current
project directory, with no root privileges required - either through its
**web UI** (default) or, with `--tui`, directly as an **interactive terminal
UI** in the invoking terminal. Same sandboxing either way:

- **Filesystem**: only the project directory you run `ocbox` from is mounted
  into the sandbox (read-write). No other host path is visible from inside.
- **Network**: the container gets `--network=none` - no network device at
  all except loopback. The only thing it can reach is a local LLM server you
  configure (see "How the isolation works" below). In **web UI** mode, a pair of
  relay processes ocbox starts on the host is the only thing that can reach
  back into the container, exposing the UI to your browser; in `--tui` mode
  nothing is exposed to the host network at all - you're attached directly
  to the container's terminal.
- **Auth**: **web UI** mode generates a fresh token on every run, printed to your
  terminal, that gates access to the forwarded web UI. `--tui` mode needs no
  token - there's no network-exposed UI to protect.

## Requirements

- Linux
- [Podman](https://podman.io/docs/installation), running **rootless** (no
  `sudo`, no root daemon)
- A subuid/subgid range for your user (`ocbox` checks this and tells you how
  to fix it if missing)
- A locally-running LLM server your machine can reach (e.g. Ollama, vLLM,
  LM Studio, etc.)

### Installing Podman

**Ubuntu:**

```sh
sudo apt update
sudo apt install -y podman
```

**Rocky Linux:**

```sh
sudo dnf install -y podman
```

Podman is rootless by default on both once installed - just don't run it (or
`ocbox`) with `sudo`. If your user doesn't have a subuid/subgid range yet
(usually already set up by the package on Ubuntu, sometimes not on a fresh
Rocky install), set one and re-login:

```sh
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$USER"
# then log out and back in, or:
podman system migrate
```

Verify it's actually rootless before running `ocbox`:

```sh
podman info --format '{{.Host.Security.Rootless}}'   # should print "true"
```

`ocbox` never installs Podman or escalates privileges itself - if a
prerequisite is missing, it prints exactly what to run and exits.

## Setup

Install the package:

```sh
pip install -e .          # from a checkout, until this is published
```

Create `~/.config/ocbox/conf.py`:

```python
# ~/.config/ocbox/conf.py
LLM_HOST = "127.0.0.1"
LLM_PORT = 11434           # e.g. Ollama's default port

# Optional overrides (defaults shown):
# BASE_OS = "ubuntu"             # or "debian", "rocky"
# BASE_IMAGE = "ocbox/base:latest"
# CONTAINER_WEB_PORT = 4096
# HOST_WEB_PORT = None          # None picks a free ephemeral port
# EXTRA_APT_DEFAULT = []        # package names for BASE_OS's package manager
# EXTRA_UV_DEFAULT = []
# MEMORY_LIMIT = None           # e.g. "2g"
# PIDS_LIMIT = None             # e.g. 512
```

A project can override any of these by adding its own `ocbox.conf.py` in the
project root.

### Choosing the sandbox's OS

`BASE_OS` picks which distro the sandbox image is built from: `"ubuntu"`
(default, `ubuntu:24.04`), `"debian"` (`debian:bookworm-slim`), or `"rocky"`
(`rockylinux:9`). An unrecognized value raises a clear error at startup
rather than silently falling back to something.

This changes which package manager `--apt`/`EXTRA_APT_DEFAULT` uses too -
`apt` on Debian/Ubuntu, `dnf` on Rocky - so package names need to be valid
for whichever distro you picked (e.g. `EXTRA_APT_DEFAULT = ["git"]` works
unchanged across all three, but a Debian-specific package name won't exist
on Rocky). Switching `BASE_OS` automatically triggers a rebuild the next
time you run `ocbox`, the same way an ocbox upgrade does - see "Verified
against real rootless Podman" below.

## Usage

```sh
cd ~/projects/myapp
ocbox
```

You'll be asked whether to add any extra `apt` or `uv pip` packages to the
sandbox (blank to skip). ocbox then builds/reuses the sandbox image, starts
the container, and prints something like:

```
OpenCode is ready.
  URL:      http://127.0.0.1:53211
  Username: opencode
  Password: 8Kx3n...
  (keep this secret - do not share this terminal output)
```

Open the URL, sign in with the printed credentials, and OpenCode is running
against `myapp/`, isolated from the rest of your machine.

### Terminal UI instead of the web UI

Prefer working in the terminal? Pass `--tui`:

```sh
ocbox --tui
```

This launches OpenCode's interactive terminal UI directly in your current
terminal instead of starting the web server - no port is forwarded, no auth
token is generated (there's nothing exposed to the host network to protect),
but the same filesystem/network sandboxing applies: only your project
directory is mounted, and the only network access is to your configured
`LLM_HOST:LLM_PORT`, exactly as in web mode. Press whatever OpenCode's own
quit key is (or close the terminal) to stop the sandbox.

Useful flags:

| Flag | Effect |
|---|---|
| `--tui` | Launch OpenCode's terminal UI here instead of the web UI |
| `--yes` / `-y` | Skip the interactive package prompt, use config defaults |
| `--apt PKG...` / `--uv PKG...` | Set extra packages non-interactively |
| `--rebuild` | Force a rebuild of the project's sandbox image |
| `--web-port PORT` | Pin the host port for the web UI (ignored with `--tui`) |
| `--agents-dir PATH` / `--skills-dir PATH` | Use custom agents/skills instead of the packaged defaults |
| `--config PATH` | Use a conf.py other than `~/.config/ocbox/conf.py` |

## Default skills & agents

`src/ocbox/data/agents/` and `src/ocbox/data/skills/` hold the agents and
skills you want available in every sandbox, instead of reconfiguring OpenCode
per project. Both are mounted read-only into every container. Point
`--agents-dir`/`--skills-dir` at your own directories to override them per
invocation.

Both follow OpenCode's own conventions (<https://opencode.ai/config.json>):

- **Agents**: one `<name>.md` per agent, with `description`/`mode`
  frontmatter and the body as its prompt. Mounted at
  `~/.config/opencode/agent`, which is where OpenCode looks for global agents
  - there is no config key pointing at an arbitrary agent folder, so the
  mount location is what makes them load. See
  `src/ocbox/data/agents/README.md`.
- **Skills**: one folder per skill, each holding a `SKILL.md` with `name` and
  `description` frontmatter. Registered through `skills.paths` in the
  generated config. See `src/ocbox/data/skills/README.md`.

ocbox ships four agents: `chat` (discussion, editing denied), `review` (finds
bugs, editing denied), plus `build` and `plan`, which override OpenCode's
built-ins of the same name to add the sandbox's constraints - no network, only
`/workspace` writable - to their prompts. Overriding is a merge, so the
built-ins' permission rules (plan mode's edit denial included) still apply.

Check them with `opencode agent list` and `opencode debug skill` from inside a
sandbox, and the generated config with `opencode debug config`. OpenCode
ignores config keys and agent files it doesn't recognise without complaining,
so a mistake shows up as a feature that quietly does nothing rather than an
error.

## How the isolation works

Rootless Podman's default networking (slirp4netns) NATs out to the whole
internet - the opposite of "blocked by default." Instead, `ocbox` runs the
container with `--network=none` (a kernel-level guarantee: no network device
beyond loopback exists in the container's netns at all) and bridges exactly
two channels through Unix sockets bind-mounted from the host:

- **LLM egress**: a host-side relay listens on a Unix socket and dials your
  configured `LLM_HOST:LLM_PORT`; a matching relay inside the container turns
  that socket back into a local TCP port OpenCode talks to as if it were any
  ordinary HTTP endpoint.
- **Web UI ingress**: the same pattern in reverse - OpenCode's web server
  binds loopback inside the container, a relay exposes it on a Unix socket,
  and a host-side relay turns that into the TCP port your browser connects
  to.

No arbitrary destination is ever reachable from inside the sandbox, and no
container-internal port is ever published directly to the host.

## Verified against real OpenCode

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

Worth knowing when changing any of this: OpenCode ignores config keys it
doesn't recognise instead of rejecting them, so a wrong key name disables a
feature with nothing in the output to say so. `opencode debug config` prints
what actually survived, and `opencode debug skill` lists what was discovered.

## Verified against real rootless Podman

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

## Development

```sh
pip install -e ".[dev]"
pytest                                    # unit tests, no podman required
RUN_PODMAN_INTEGRATION=1 pytest tests/integration   # requires real podman
ruff check src tests
```
