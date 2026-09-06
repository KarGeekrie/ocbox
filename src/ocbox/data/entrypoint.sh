#!/bin/sh
# Container entrypoint: starts OpenCode's web UI, waits for it to actually be
# listening, then brings up the two host-facing/host-reaching relays. The
# container has --network=none - lo is the only device it has - so both
# relays talk to the outside world purely through Unix sockets bind-mounted
# from the host at /run/ocbox.
set -eu

CONTAINER_LLM_PORT="${OCBOX_CONTAINER_LLM_PORT:?OCBOX_CONTAINER_LLM_PORT not set}"
CONTAINER_WEB_PORT="${OCBOX_CONTAINER_WEB_PORT:?OCBOX_CONTAINER_WEB_PORT not set}"

# LLM egress: local TCP port -> /run/ocbox/llm.sock -> (host relay) -> user's LLM.
python3 /usr/local/lib/ocbox/relay.py serve-tcp "127.0.0.1:${CONTAINER_LLM_PORT}" \
    --connect-unix /run/ocbox/llm.sock &

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
