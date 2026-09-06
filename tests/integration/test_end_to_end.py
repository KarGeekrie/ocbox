"""Real end-to-end test against actual Podman. Skipped unless Podman is
installed AND RUN_PODMAN_INTEGRATION=1 is set, since it builds a real image
and runs a real rootless container - too slow/heavy for the default unit
test run and not available in most CI sandboxes.
"""

import os
import shutil

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("podman") is None or os.environ.get("RUN_PODMAN_INTEGRATION") != "1",
    reason="requires podman installed and RUN_PODMAN_INTEGRATION=1",
)


def test_placeholder_for_future_real_podman_run():
    """Placeholder: exercising a real `ocbox` run needs a stub local-LLM HTTP
    server and a lightweight stand-in for the OpenCode image (the real
    Containerfile pulls OpenCode from the network and is too slow/flaky for
    routine test runs). Wire this up once the open questions in the project
    plan (OpenCode's real CLI flags/config schema) are confirmed.
    """
    pytest.skip("not yet implemented - see module docstring")
