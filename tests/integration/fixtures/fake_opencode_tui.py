#!/usr/bin/env python3
"""Test-only stand-in for what `opencode` (no subcommand, TUI mode) would do
with the LLM provider - see ../opencode's docstring. Makes one request
through the LLM-egress relay and prints the result so the integration test
can confirm the relay chain works in TUI mode too, without needing a real
interactive TUI/pty in the test harness.
"""

from __future__ import annotations

import os
import urllib.request


def main() -> None:
    port = os.environ["OCBOX_CONTAINER_LLM_PORT"]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        print("LLM-CHECK:", resp.read().decode())


if __name__ == "__main__":
    main()
