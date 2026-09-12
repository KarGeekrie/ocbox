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
- Everything outside the mounted project directories - including the rest of
  this container's filesystem - is thrown away when the sandbox exits. Nothing
  written there needs redirecting or cleaning up for the user's sake.
- Profilers and debuggers have to launch the program they inspect. Attaching to
  an already-running process is not permitted here.
