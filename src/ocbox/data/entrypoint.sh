#!/bin/sh
# Container entrypoint. The container has --network=none - lo is the only
# device it has - so the LLM-egress relay below is the only way anything in
# here reaches the outside world, purely through a Unix socket bind-mounted
# from the host at /run/ocbox.
#
# Two modes, chosen by OCBOX_MODE:
#   web (default): starts OpenCode's web UI, waits for it to actually be
#     listening, then brings up the second (web-ingress) relay so the host
#     can reach it. Runs detached from any terminal.
#   tui: execs OpenCode's interactive terminal UI directly, attached to
#     whatever terminal `podman run -it` was given. No web relay, no auth
#     token - nothing is exposed to the host network at all in this mode.
set -eu

MODE="${OCBOX_MODE:-web}"
CONTAINER_LLM_PORT="${OCBOX_CONTAINER_LLM_PORT:?OCBOX_CONTAINER_LLM_PORT not set}"

# LLM egress: local TCP port -> /run/ocbox/llm.sock -> (host relay) -> user's LLM.
# Needed in both modes - OpenCode talks to its provider the same way either way.
python3 /usr/local/lib/ocbox/relay.py serve-tcp "127.0.0.1:${CONTAINER_LLM_PORT}" \
    --connect-unix /run/ocbox/llm.sock &

# Wait for the LLM relay to actually be listening before starting OpenCode,
# so its very first provider request doesn't race a not-yet-bound port.
i=0
until python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(0.2)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${CONTAINER_LLM_PORT})) == 0 else 1)
" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 50 ]; then
        echo "ocbox: LLM relay never started listening on port ${CONTAINER_LLM_PORT}" >&2
        exit 1
    fi
    sleep 0.2
done

if [ "$MODE" = "tui" ]; then
    # NOTE: assumes bare `opencode` (no subcommand) launches the interactive
    # TUI, mirroring how e.g. `claude` launches its own REPL with no
    # subcommand - unverified against OpenCode's real CLI, see the project's
    # open questions.
    exec opencode
fi

CONTAINER_WEB_PORT="${OCBOX_CONTAINER_WEB_PORT:?OCBOX_CONTAINER_WEB_PORT not set}"

opencode web --hostname 127.0.0.1 --port "${CONTAINER_WEB_PORT}" &
OPENCODE_PID=$!

# Wait for OpenCode to actually be listening before exposing it through the
# host-facing relay, so the browser's first request doesn't race a
# not-yet-bound port.
i=0
until python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(0.2)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${CONTAINER_WEB_PORT})) == 0 else 1)
" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 150 ]; then
        echo "ocbox: opencode web never started listening on port ${CONTAINER_WEB_PORT}" >&2
        exit 1
    fi
    sleep 0.2
done

# Web ingress: /run/ocbox/web.sock -> (host relay) -> browser, this side -> opencode web.
python3 /usr/local/lib/ocbox/relay.py serve-unix /run/ocbox/web.sock \
    --connect-tcp "127.0.0.1:${CONTAINER_WEB_PORT}" &

wait "$OPENCODE_PID"
