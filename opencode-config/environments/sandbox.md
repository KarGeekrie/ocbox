# Environment: ocbox sandbox

You are running inside an ocbox sandbox: a rootless Podman container holding
only the user's project and the tools listed below.

- Changes in the project directories listed below are real; they are the
  user's files. This includes anything mounted via `--mount` at `/mnt/<name>` -
  those are real host directories too, not sandbox-local scratch.
- Destructive or history-rewriting git operations (`reset --hard`, `clean`,
  `rebase`, `commit --amend`, ...) still act on the user's real work here, even
  though nothing else about the container is real to the host - see the team
  `AGENTS.md` for what to say before running one.
- There is no network beyond the LLM connection ocbox sets up for you, so
  installing packages, cloning a new repository, or pushing/pulling from a
  remote will simply fail here rather than needing to be refused - it's not
  worth attempting mid-session.
- What's installed is fixed when the sandbox is created. If a task needs a tool
  that isn't listed, say which package is missing and ask the user to restart
  with `ocbox --apt <package>` or `ocbox --uv <package>`, rather than trying to
  install it yourself.
- Python: run the image's `python3` directly - the packages the sandbox was
  built with are installed into it. A virtual environment already in the
  project was made on the user's machine: its interpreter, `activate` script
  and entry points point at paths this container doesn't have, so don't
  activate, repair or rebuild it. Don't create a new one in the project either:
  it would stay in the user's directory, pointing at this container's Python.
  `uv run` and `uv sync` use a separate environment outside the project (see
  the facts below), so they leave the project's `.venv` alone - but they still
  can't download anything.
- Your home directory, `/home/ocbox`, is kept from one session of this project
  to the next: OpenCode's session history lives there, and so does anything you
  write there, so don't treat it as scratch space. `/tmp` is discarded when the
  sandbox exits, and most of the rest of the container's filesystem is
  read-only.
- Profilers and debuggers have to launch the program they inspect. Attaching to
  an already-running process is not permitted here.
