#!/usr/bin/env python3
"""Pure-stdlib TCP<->UNIX socket relay, used identically on the host and inside
the sandbox container to bridge network-isolated (`--network=none`) containers
to specific outside destinations without giving them a real network device.

Usage:
    relay.py serve-unix <socket-path> --connect-tcp <host>:<port>
    relay.py serve-tcp <host>:<port>  --connect-unix <socket-path>

Every accepted connection on the "serve" side opens one new connection on the
"connect" side and pipes bytes bidirectionally until either end closes.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from collections.abc import Awaitable, Callable

StreamPair = tuple[asyncio.StreamReader, asyncio.StreamWriter]


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Forwards reader -> writer until EOF, then half-closes writer's write side.

    Uses write_eof() (a socket shutdown(SHUT_WR)) rather than close() so the
    other pipe direction - sharing the same underlying connection - can keep
    flowing (e.g. an HTTP client that finishes its request body before
    reading the response).
    """
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        with contextlib.suppress(Exception):
            if writer.can_write_eof():
                writer.write_eof()


async def handle(
    local_r: asyncio.StreamReader,
    local_w: asyncio.StreamWriter,
    opener: Callable[[], Awaitable[StreamPair]],
) -> None:
    try:
        remote_r, remote_w = await opener()
    except OSError:
        local_w.close()
        return
    await asyncio.gather(
        pipe(local_r, remote_w),
        pipe(remote_r, local_w),
        return_exceptions=True,
    )
    for writer in (local_w, remote_w):
        with contextlib.suppress(Exception):
            writer.close()


def _parse_host_port(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host:
        raise argparse.ArgumentTypeError(f"expected host:port, got {value!r}")
    return host, int(port)


async def run_serve_unix(socket_path: str, connect_tcp: tuple[str, int]) -> None:
    host, port = connect_tcp

    async def opener() -> StreamPair:
        return await asyncio.open_connection(host, port)

    async def on_connect(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        await handle(r, w, opener)

    if os.path.exists(socket_path):
        os.unlink(socket_path)
    server = await asyncio.start_unix_server(on_connect, path=socket_path)
    os.chmod(socket_path, 0o600)
    async with server:
        await server.serve_forever()


async def run_serve_tcp(listen: tuple[str, int], connect_unix: str) -> None:
    async def opener() -> StreamPair:
        return await asyncio.open_unix_connection(connect_unix)

    async def on_connect(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        await handle(r, w, opener)

    host, port = listen
    server = await asyncio.start_server(on_connect, host=host, port=port)
    async with server:
        await server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    serve_unix = sub.add_parser("serve-unix", help="Listen on a Unix socket")
    serve_unix.add_argument("socket_path")
    serve_unix.add_argument("--connect-tcp", type=_parse_host_port, required=True)

    serve_tcp = sub.add_parser("serve-tcp", help="Listen on a TCP host:port")
    serve_tcp.add_argument("listen", type=_parse_host_port)
    serve_tcp.add_argument("--connect-unix", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "serve-unix":
            asyncio.run(run_serve_unix(args.socket_path, args.connect_tcp))
        else:
            asyncio.run(run_serve_tcp(args.listen, args.connect_unix))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
