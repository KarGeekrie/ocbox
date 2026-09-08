#!/bin/sh
# Container entrypoint. The container has --network=none - lo is the only
# device it has - so the LLM-egress relay below is the only way anything in
# here reaches the outside world, purely through a Unix socket bind-mounted
# from the host at /run/ocbox.
#
# Two modes, chosen by OCBOX_MODE:
#   web (default): starts OpenCode's web server, waits for it to actually
#     be listening, then brings up the second (web-ingress) relay so the host
#     can reach it. Runs detached from any terminal.
#   tui: execs OpenCode's interactive terminal UI directly, attached to
#     whatever terminal `podman run -it` was given. No web relay, no auth
#     token - nothing is exposed to the host network at all in this mode.
set -eu

# Polls 127.0.0.1:<port> until something is listening, or gives up after
# <max_tries> * 0.2s and exits the whole script. Used for both the LLM relay
# (so OpenCode's first provider request doesn't race a not-yet-bound port)
# and, in web mode, for OpenCode's own web server (so the browser's first
# request doesn't race it either).
wait_for_port() {
    _port="$1"
    _max_tries="$2"
    _label="$3"
    _i=0
    until python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(0.2)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${_port})) == 0 else 1)
" 2>/dev/null; do
        _i=$((_i + 1))
        if [ "$_i" -ge "$_max_tries" ]; then
            echo "ocbox: ${_label} never started listening on port ${_port}" >&2
            exit 1
        fi
        sleep 0.2
    done
}

MODE="${OCBOX_MODE:-web}"
CONTAINER_LLM_PORT="${OCBOX_CONTAINER_LLM_PORT:?OCBOX_CONTAINER_LLM_PORT not set}"

# LLM egress: local TCP port -> /run/ocbox/llm.sock -> (host relay) -> user's LLM.
# Needed in both modes - OpenCode talks to its provider the same way either way.
python3 /usr/local/lib/ocbox/relay.py serve-tcp "127.0.0.1:${CONTAINER_LLM_PORT}" \
    --connect-unix /run/ocbox/llm.sock &

wait_for_port "$CONTAINER_LLM_PORT" 50 "LLM relay"

if [ "$MODE" = "tui" ]; then
    # Verified against opencode 1.18.29: `opencode --help` lists
    # `opencode [project]  start opencode tui  [default]`, so bare `opencode`
    # with no subcommand is indeed the interactive TUI.
    exec opencode
fi

CONTAINER_WEB_PORT="${OCBOX_CONTAINER_WEB_PORT:?OCBOX_CONTAINER_WEB_PORT not set}"

# Basic Auth is the only thing gating the forwarded web UI, so an empty
# password would quietly expose it to anything that can reach the host port.
# OpenCode merely warns about that, on the stdout we drop just below - so
# check it here instead, where it can still fail closed.
: "${OPENCODE_SERVER_PASSWORD:?refusing to start web mode without a password}"

# `serve`, not `web`: both serve the identical UI (verified byte-for-byte),
# but `opencode web` also spawns xdg-open, which doesn't exist in this image -
# it dumped a stack trace into the user's terminal on every run. ocbox prints
# the URL instead and lets the user open it themselves.
#
# stdout is dropped because its only content is a banner advertising
# http://127.0.0.1:${CONTAINER_WEB_PORT} - the *container-internal* port,
# unreachable from the host and contradicting the URL ocbox prints. stderr
# stays attached so genuine failures still surface.
opencode serve --hostname 127.0.0.1 --port "${CONTAINER_WEB_PORT}" >/dev/null &
OPENCODE_PID=$!

wait_for_port "$CONTAINER_WEB_PORT" 150 "opencode serve"

# Web ingress: /run/ocbox/web.sock -> (host relay) -> browser, this side -> opencode serve.
python3 /usr/local/lib/ocbox/relay.py serve-unix /run/ocbox/web.sock \
    --connect-tcp "127.0.0.1:${CONTAINER_WEB_PORT}" &

wait "$OPENCODE_PID"
