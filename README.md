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

Only these sandboxed modes protect the host machine. `--no-sandbox` (see
"Running without a sandbox") runs OpenCode directly on it, with nothing
isolated.

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

`opencode-config/` at the repo root holds what ocbox hands to OpenCode in
every mode: the team's agents, skills, rules (`AGENTS.md`) and model list
(`opencode.jsonc`). This repository is a preconfiguration for our team rather
than a general-purpose package, so that directory arrives already filled in -
see "Default skills & agents" below for what's in it.

Nothing else is required. Machine-specific settings go in an optional
`~/.config/ocbox/conf.py`, where every setting has a default:

```python
# ~/.config/ocbox/conf.py - optional; defaults shown
# BASE_OS = "ubuntu"             # or "debian", "rocky"
# BASE_IMAGE = "ocbox/base:latest"
# CONTAINER_WEB_PORT = 4096
# HOST_WEB_PORT = None          # None picks a free ephemeral port
# EXTRA_APT_DEFAULT = []        # package names for BASE_OS's package manager
# EXTRA_UV_DEFAULT = []
# MEMORY_LIMIT = None           # e.g. "2g"
# PIDS_LIMIT = None             # e.g. 512
```

A project can override any of these with its own `ocbox.conf.py` at its root.
The LLM's address doesn't belong in either: it is the `baseURL` in
`opencode-config/opencode.jsonc` (see below). A `conf.py` that still sets
`LLM_HOST` or `LLM_PORT` is rejected with an error pointing there, rather than
silently ignored.

### The team's OpenCode configuration

`opencode-config/opencode.jsonc` arrives **pre-configured** for the team: the
LLM provider and models, permissions and defaults. It is the one OpenCode file
in your scope. You can edit it, but that isn't recommended: a change made for
one person quietly makes their OpenCode behave differently from everyone
else's, and a change everyone needs belongs in a commit to this repository.

In every mode - web, `--tui` or `--no-sandbox` - ocbox hands this file to
OpenCode; there is no other copy to keep in sync. `--opencode-config PATH`
substitutes another file for a single run.

This file is also where the LLM server's address lives -
`provider.local.options.baseURL` - and every mode reads it. Inside a sandbox,
ocbox makes that address the destination of the relay the sandbox reaches the
LLM through, and points OpenCode at the relay; with `--no-sandbox`, OpenCode
connects to the address directly. It has to be plain `http` for the relay: an
`https` address is refused with an explanation, since OpenCode sees the relay at
`http://127.0.0.1` and no certificate could match that. The value shipped is a
local Ollama, as an example - see "TODO".

To check it landed, run `opencode models` inside a sandbox - you should see
`local/...` lines.

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
time you run `ocbox`, the same way an ocbox upgrade does - see AGENTS.md's
"Verification history" for how that's tested.

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
against `myapp/`, isolated from the rest of your machine. "Workflow" below
covers what to do from there.

### Mounting extra working directories

Only the current directory is mounted by default. `--mount PATH` (repeatable)
adds more - useful when a task spans multiple repos, e.g. an app and the
library it depends on:

```sh
cd ~/projects/myapp
ocbox --mount ~/projects/shared-lib --mount ~/projects/other-repo
```

Each lands read-write at `/mnt/<basename>` (`~/projects/shared-lib` above
becomes `/mnt/shared-lib`), independent of the primary workspace and of each
other - basenames must be distinct across every `--mount`, or ocbox refuses
to start rather than silently mounting one over the other.

OpenCode's permissions follow the mounts. OpenCode refuses its tools any path
outside the project unless `permission.external_directory` allows it, and the
team's `opencode-config/opencode.jsonc` denies every such path. For each
`--mount`, ocbox therefore adds `"/mnt/<basename>/**": "allow"` to the
configuration it generates for the run. OpenCode merges that entry into the
team's rules, which still apply to every other path.

`--no-sandbox` doesn't take `--mount`: OpenCode sees the host's filesystem
directly, and the team's `external_directory` rules apply to it as written.

### Terminal UI instead of the web UI

Prefer working in the terminal? Pass `--tui`:

```sh
ocbox --tui
```

This launches OpenCode's interactive terminal UI directly in your current
terminal instead of starting the web server - no port is forwarded, no auth
token is generated (there's nothing exposed to the host network to protect),
but the same filesystem/network sandboxing applies: only your project
directory is mounted, and the only network access is to the LLM named in
`opencode.jsonc`, exactly as in web mode. Press whatever OpenCode's own
quit key is (or close the terminal) to stop the sandbox.

### Running without a sandbox

`--no-sandbox` runs OpenCode directly on the host, with no Podman involved -
for when you trust what it is about to do and want ocbox's configuration
without the container:

```sh
ocbox --no-sandbox              # OpenCode's TUI, with the team's configuration
ocbox --no-sandbox -- run "..." # any OpenCode CLI form works - nothing is reserved
```

**Nothing is isolated in this mode, and only the sandboxed modes guarantee the
integrity of the host.** OpenCode can touch anything your user can, and reach
any network.

What ocbox does, checked end to end on a host after `opencode uninstall`:

- **OpenCode already installed** (on `PATH`, in `~/.opencode/bin`, or already in
  this checkout's `.ocbox/bin/`): nothing is installed.
- **OpenCode missing**: ocbox runs OpenCode's standard install script, which
  fetches the latest release - so the host's version can be newer than the
  sandbox image's - but installs it inside this checkout, in the gitignored
  `.ocbox/bin/`, rather than in `~/.opencode/bin`, and leaves your shell rc
  files alone. `opencode` therefore isn't on your shell's `PATH`; ocbox runs it
  from `.ocbox/bin/`.
- **Either way, the team's configuration is loaded**: ocbox assembles
  `opencode-config/`'s agents, skills and `opencode.jsonc` (or the
  `--agents-dir`/`--skills-dir`/`--opencode-config` overrides), plus the
  `AGENTS.md` composed for this mode, in `.ocbox/no-sandbox/`, and points
  OpenCode at it with `OPENCODE_CONFIG_DIR`. Everything ocbox writes for this
  mode stays inside the checkout.

A detail worth knowing: on the host, OpenCode behaves like any standard
OpenCode installation, with side effects a sandbox doesn't have. It creates its
usual directories under your home - `~/.config/opencode/`,
`~/.local/share/opencode/` and `~/.cache/opencode/` - and once a session runs it
installs its plugin SDK (`@opencode-ai/plugin`, about 63 MB) in
`~/.config/opencode/`. It also still reads `~/.config/opencode/`: a personal
`opencode.jsonc` or `agents/` there merges with the team's - the team's value
wins where both set the same key - while a personal `AGENTS.md` is replaced by
the one ocbox composes for this mode. So in this mode, behaviour isn't
guaranteed to be identical for everyone on the team.

One more thing to expect: on the host, OpenCode's own startup occasionally
stalls for minutes before answering, whether ocbox launched it or not - see
AGENTS.md's "Verification history". No sandboxed run has shown it.

**No relay in this mode**: OpenCode connects straight to the `baseURL` in
`opencode-config/opencode.jsonc`, so that address has to be reachable from the
host - see "TODO" at the end.

Not compatible with `--tui`, `--detach`, `--web-port`, `--rebuild`,
`--apt`/`--uv`, `--yes`, `--config` or `--mount` - all sandbox-specific.

### Passing arguments through to OpenCode

Anything after a bare `--` goes to OpenCode itself, verbatim:

```sh
ocbox --tui -- --agent chat                  # start the TUI on a given agent
ocbox --tui -- --model local/qwen2.5:7b      # pick the model up front
ocbox --tui -- --continue                    # resume the last session
ocbox --tui -y -- run "explain src/relay.py" # non-interactive, prints and exits
```

Among the sandboxed modes, passthrough is TUI-only (`--no-sandbox` accepts it
too). Web mode runs `opencode serve`, which doesn't understand most of
OpenCode's own CLI flags - forwarding them there used to just hang until
ocbox's readiness check timed out, with nothing pointing at the real cause.
`ocbox -- ...` without `--tui` is refused outright now instead, with an error
telling you to add `--tui`. See
<https://opencode.ai/docs/cli/> for the full flag surface.

Only the first `--` is ocbox's, so `ocbox --tui -- run -- ...` passes the
second one through untouched. In the sandboxed modes `--port` and `--hostname`
are refused: ocbox sets them to wire OpenCode to the relay, and a second value
would detach it.
Use `--web-port` to choose the host port instead.

### Running detached

`--detach` (`-d`, web mode only) backgrounds the whole sandbox so it survives
closing the terminal - like `nohup ocbox &`, but ocbox does the forking
itself so the relay bridges it owns (the only thing standing between the
network-isolated container and your LLM/browser) stay alive too:

```sh
ocbox --detach
# ocbox: detached (pid 12345), container ocbox-myproj-a1b2c3d4e5f6
#   progress/URL: tail -f /run/user/1000/ocbox/myproj-.../ocbox.log
#   status:       podman ps --filter name=ocbox-myproj-a1b2c3d4e5f6
#   stop:         podman stop ocbox-myproj-a1b2c3d4e5f6
```

Any interactive package prompt still runs before it detaches; everything
after that - including the connect banner with the URL and password - goes
to the printed log file instead of your terminal. There's no `ocbox --list`;
track and stop it with `podman` directly, on the container name ocbox
printed (always `ocbox-<project-slug>`).

Useful flags:

| Flag | Effect |
|---|---|
| `--tui` | Launch OpenCode's terminal UI here instead of the web UI |
| `--yes` / `-y` | Skip the interactive package prompt, use config defaults |
| `--apt PKG...` / `--uv PKG...` | Set extra packages non-interactively |
| `--rebuild` | Force a rebuild of the project's sandbox image |
| `--web-port PORT` | Pin the host port for the web UI (ignored with `--tui`) |
| `--mount PATH` | Mount another directory read-write at `/mnt/<basename>` (repeatable) |
| `--agents-dir PATH` / `--skills-dir PATH` | Use other agents/skills for this run instead of `opencode-config/`'s |
| `--opencode-config PATH` | Use another `opencode.jsonc` for this run instead of `opencode-config/opencode.jsonc` |
| `--config PATH` | Use a conf.py other than `~/.config/ocbox/conf.py` |
| `--detach` / `-d` | Background the sandbox so it survives closing the terminal (web mode only) |
| `--no-sandbox` | Run OpenCode directly on the host - no Podman, no isolation at all |
| `-- ARGS...` | Everything after `--` is forwarded to OpenCode itself |

## Workflow

This follows OpenCode's own recommended workflow (<https://opencode.ai/docs/>),
adapted to how ocbox sets things up.

### 0. The configuration is already in place

There is nothing to configure before starting: the team's `opencode.jsonc`,
agents, skills and rules ship in `opencode-config/` - see "The team's OpenCode
configuration" above and "Default skills & agents" below. Guidance specific to
one project doesn't belong there; it goes in that project's own `AGENTS.md`,
which is the next step.

### 1. Initialise the project with `/init`, then review what it wrote

The first time you work on a repository, run `/init` inside OpenCode - it is a
command in the session, not `opencode init` on the command line. It reads the
code and writes an `AGENTS.md` at the project root: build and test commands,
architecture, conventions. **Read it and correct it before relying on it.**
It is a first draft inferred from what the code looks like, and anything it
got wrong is repeated to the model on every turn afterwards. Then commit it,
so everyone working on the repository gets the same guidance.

That file is the *project* half of two layers of rules. OpenCode sends both,
rather than letting one replace the other:

| Layer | File | Holds | Changed by |
|---|---|---|---|
| Team | `opencode-config/AGENTS.md`, sent within the global `AGENTS.md` ocbox composes | Rules for every project | A commit to this repository |
| Project | `AGENTS.md` at the project root, written by `/init` | This codebase's commands, architecture, conventions | A commit to that project |

The global half isn't one file ocbox ships: it is composed for every run, from
three parts in this order -

1. **Where the agent runs**, from `opencode-config/environments/`: `sandbox.md`
   in web and `--tui` mode, `no-sandbox.md` with `--no-sandbox`. Only the current
   mode's is sent, so an agent on your own machine is never told it is
   sandboxed, or the other way round.
2. **What this sandbox has** - sandboxed modes only, generated by ocbox: whether
   the container has a network, its base distribution, the extra `apt` and `uv`
   packages it was built with, and the project directories mounted into it.
3. **The team rules**, from `opencode-config/AGENTS.md`, the same in every mode.

How the two layers interact:

- **Both reach the model, together.** Neither overrides the other.
- **Nothing resolves conflicts between them.** If the team file says one thing
  and the project file the opposite, the model receives both and has to guess.
  So don't restate team rules in a project file, and when a project genuinely
  needs an exception, say so explicitly: "unlike the team default, this
  project...".
- **Put each rule at the most general level where it holds.** True for all
  our code: the team file. True for one codebase: that project's file.
- **After editing either file, start a new session** so the change is
  certainly in effect.

The team file currently carries one rule. It also shows the shape to aim for -
short, imperative, and explicit about the awkward case:

```markdown
## Python

Never run Python outside a virtual environment. If the project already has
one (`.venv/`, `venv/`), activate it. If it doesn't, ask before creating
one rather than installing into the system interpreter.
```

One thing looks like an alternative and isn't: OpenCode's `instructions`
config key is parsed but never resolved, so files listed there never reach the
model.

### 2. Plan, then build

For anything beyond a small change, work in two passes, as OpenCode
recommends:

1. **Switch to the `plan` agent** (Tab in the terminal UI). Its edit tools
   are disabled, so it investigates and proposes rather than editing - though
   it can still run commands, so it isn't a guarantee that nothing changes.
2. **Describe what you want in detail.** OpenCode's advice is to talk to it
   like a junior developer new to the codebase. Point at files with `@`.
3. **Iterate on the plan until it's right**: correct wrong assumptions, add
   context, push back on an approach. This is the cheap moment to change your
   mind.
4. **Switch to `build`** (Tab again) and ask it to carry out the plan.
5. **Review the result.** `/undo` reverts the last change - repeat it to go
   further back - and `/redo` restores it.

For a small, well-defined change, skip planning and ask `build` directly,
naming the files involved.

When you only want to **talk something through** - how a module works, which
of two designs to choose - use `chat`: it reads the code but can neither edit
files nor run commands, so nothing changes by accident. To find bugs in a
change before it lands, use `review`: editing is denied, and commands run only
with your approval.

### 3. Turn a recurring procedure into a skill

When you find yourself walking an agent through the same multi-step procedure
again, make it a skill: a `SKILL.md` in its own folder under
`opencode-config/skills/`. Where `AGENTS.md` applies on every turn, a skill
applies when it's relevant - the agent only sees each skill's name and
description up front, and loads the body when a task calls for it.

A short example, for finding where a Python program spends its time:

```markdown
---
name: python-hotspots
description: Profile a Python program with py-spy to find where its time goes and judge whether that is expected. Use when asked why Python code is slow or what to optimise.
---

1. Run the workload under py-spy, launching it rather than attaching, with the
   project's venv interpreter:
   `py-spy record --format raw --rate 250 -o profile.txt -- python <script> <args>`
   Add `--subprocesses` for multiprocessing, `--native` for C extensions.
2. Rank lines by time spent in them. Each line of profile.txt is a stack
   followed by a sample count:
   `awk '{c=$NF; $NF=""; sub(/ +$/,""); n=split($0,f,";"); s[f[n]]+=c; t+=c} END{for(k in s) printf "%5.1f%%  %s\n", 100*s[k]/t, k}' profile.txt | sort -nr | head`
3. Read the code at the top entries, and the callers that lead to them.
4. Report without changing any code: where the time goes (percentages, file
   and line), and for each hot spot whether it is expected - genuine work such
   as parsing or numeric loops - or suspicious: repeated work, quadratic loops,
   avoidable I/O. Suggest a fix only for the suspicious ones.
```

Two sandbox specifics this example accounts for, both checked in a real
sandbox: py-spy has to be in the image (`ocbox --uv py-spy`, or
`EXTRA_UV_DEFAULT` in `conf.py`), and it must *launch* the program - attaching
to a running process with `--pid` needs ptrace privileges the sandbox drops,
and fails with "Permission Denied". Run it from `build` or `plan`; `chat` can't
run commands.

## Default skills & agents

Everything under `opencode-config/` is shared by every mode, so editing it
changes behaviour for everyone; `--agents-dir`/`--skills-dir` exist for trying
something out in a single run without touching it.

Agents and skills are found because of *where* they are mounted - OpenCode's
own global config directory - rather than through any config key, so the
`opencode.json` ocbox generates holds nothing but the provider endpoint:

- **Agents**: one `<name>.md` per agent, with `description`/`mode`
  frontmatter and the body as its prompt. Mounted at
  `~/.config/opencode/agents`, where OpenCode looks for global agents. See
  `opencode-config/agents/README.md`.
- **Skills**: one folder per skill, each holding a `SKILL.md` with required
  `name` and `description` frontmatter. Mounted at
  `~/.config/opencode/skills`, the documented location for global skills, so
  the same mechanism as agents - no config key involved. See
  `opencode-config/skills/README.md`, and "Workflow" step 3 for an example.
- **Team rules and environments**: `AGENTS.md` and `environments/`, which ocbox
  composes into the global `AGENTS.md` for each run - see "Workflow" step 1.

ocbox adds two agents next to OpenCode's built-in `build` and `plan`, which it
leaves exactly as OpenCode ships them: `chat` (discussion only - editing *and*
bash denied, since denying edits alone still leaves `echo x > file`) and
`review` (finds bugs; editing denied, bash gated on your approval so `git diff`
still works). Both deny `webfetch`. Their prompts describe a role only; where
they run comes from the composed `AGENTS.md`.

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

- **LLM egress**: a host-side relay listens on a Unix socket and dials the host
  and port of the `baseURL` in `opencode.jsonc`; a matching relay inside the container turns
  that socket back into a local TCP port OpenCode talks to as if it were any
  ordinary HTTP endpoint.
- **Web UI ingress**: the same pattern in reverse - OpenCode's web server
  binds loopback inside the container, a relay exposes it on a Unix socket,
  and a host-side relay turns that into the TCP port your browser connects
  to.

No arbitrary destination is ever reachable from inside the sandbox, and no
container-internal port is ever published directly to the host.

Curious what's actually been checked against real OpenCode and real rootless
Podman, versus what's still a best-effort guess? See AGENTS.md's
"Verification history" - contributor-facing detail moved out of this README
to keep it focused on using ocbox rather than developing it.

## Scheduling runs

`ocbox --tui --yes -- run "..."` is already non-interactive and exits on its
own once OpenCode is done - exactly what a cron job needs, with no `--detach`
involved since cron itself runs headless. `--tui` is there because passthrough
requires it (see "Passing arguments through to OpenCode"); it works without a
terminal, podman merely warning that the input device is not a TTY. Useful for
a nightly review against an LLM that's only free outside working hours, for
instance:

```cron
0 2 * * * cd /path/to/project && /usr/local/bin/ocbox --tui --yes -- run "review everything changed since yesterday" >> ~/ocbox-nightly-review.log 2>&1
```

Once a new release is out, a scheduled run stops with the update message like
any other run, until someone updates the checkout.

ocbox has no scheduler of its own - `cron`/`systemd --user timers` already
do this well, and reimplementing one would be dead weight for what's really
just "run this command later."

## Updating

ocbox runs from a git checkout, so an update is a git update, and ocbox tells
two kinds apart:

- **A new release - a newer `v*` tag - is required.** ocbox stops before
  starting anything: a release is the team deciding everyone should be on it.
- **New commits without a new tag are optional.** ocbox says how many commits
  your branch is behind, and carries on.

Either way it prints the command to run, and doesn't update itself:

```sh
git -C <checkout> pull --ff-only && pip install --upgrade -e <checkout>
```

The pull is what brings the new code. The pip install refreshes what pip
recorded the first time: the version number, the `ocbox` command, any new
dependency. `--ff-only` makes git stop rather than merge when you have local
commits in the way.

The first sandbox run after an update rebuilds the images from scratch, which
takes a few minutes. That rebuild is also how the sandbox gets the current uv
and OpenCode: the images install both unpinned, and refresh them only then.
`opencode-config/` - `opencode.jsonc`, agents, skills, `AGENTS.md` - is not part
of any image: it is mounted at every run, so a change to it applies on the next
run, update or not.

The check fetches from the remote at most once a day, and keeps the timestamp in
the gitignored `.ocbox/update-check.json`. A failed fetch - offline, no SSH
agent - never blocks a run by itself, but a newer tag that has already been
fetched does, online or not. `OCBOX_SKIP_UPDATE_CHECK=1` turns the check off
entirely: an escape hatch for when an update can't be applied right away, not a
way to stay behind.

## Development

```sh
pip install -e ".[dev]"
pytest                                    # unit tests, no podman required
RUN_PODMAN_INTEGRATION=1 pytest tests/integration   # requires real podman
ruff check src tests
```

## What still writes outside the checkout

ocbox keeps what it writes inside this checkout where it can, in the gitignored
`.ocbox/`: the OpenCode binary it installs for `--no-sandbox`, the configuration
directory it assembles for that mode, and the update check's timestamp. The
rest either can't live there or isn't written by ocbox:

| Where | Written by | What |
|---|---|---|
| `~/.local/share/containers/` | Podman, for ocbox | The sandbox images, and one `ocbox-home-<project>` volume per project - the container's home directory, kept between runs. Podman decides where its storage lives. |
| `$XDG_RUNTIME_DIR/ocbox/<project>/`, usually `/run/user/<uid>/` | ocbox, sandboxed modes | Per-run files: the relay sockets, the generated `opencode.json` and `AGENTS.md`, the web UI password, the `--detach` log. Private to your user. |
| `~/.local/state/ocbox/<project>/` | ocbox, sandboxed modes | Which extra packages the project image was built with, and its build context. |
| `~/.config/opencode/`, `~/.local/share/opencode/`, `~/.cache/opencode/` | OpenCode itself, `--no-sandbox` only | OpenCode's standard directories, including its plugin SDK - see "Running without a sandbox". |
| `~/.config/ocbox/conf.py`, `<project>/ocbox.conf.py` | You | Optional settings. ocbox only reads them. |

## TODO

- [ ] Set `provider.local.options.baseURL` in `opencode-config/opencode.jsonc` to
  the team's LLM server - it still holds the example local Ollama,
  `http://127.0.0.1:11434/v1`. Every mode reads it: a sandbox's relay connects
  there, and OpenCode connects there directly under `--no-sandbox`.
