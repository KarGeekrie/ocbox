Never run Python, or install Python packages, outside a virtual environment.

Before running any Python command or installing any package:

1. Check whether a venv already exists in the project you're working in
   (e.g. `.venv/`, `venv/`, or one referenced by the project's own tooling).
2. If one exists, use it - activate it, or invoke its interpreter/tools
   directly (`.venv/bin/python`, `.venv/bin/pip`, `uv run` if the project
   uses `uv`).
3. If none exists, stop and ask the user before creating one. Tell them
   which tool you intend to use to create it (`uv venv` or `python -m venv`),
   and which packages you need to install into it, and wait for their
   go-ahead before running either.
