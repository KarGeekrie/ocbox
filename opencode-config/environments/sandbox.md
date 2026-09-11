# Environment: ocbox sandbox

You are running inside an ocbox sandbox: a rootless Podman container holding
only the user's project and the tools listed below.

- Changes in the project directories listed below are real; they are the
  user's files.
- What's installed is fixed when the sandbox is created. If a task needs a tool
  that isn't listed, say which package is missing and ask the user to restart
  with `ocbox --apt <package>` or `ocbox --uv <package>`, rather than trying to
  install it yourself.
- Profilers and debuggers have to launch the program they inspect. Attaching to
  an already-running process is not permitted here.
