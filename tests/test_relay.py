"""Exercises data/relay.py directly via asyncio - no podman, no subprocess."""

import asyncio
import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

RELAY_PATH = Path(__file__).parent.parent / "src" / "ocbox" / "data" / "relay.py"
spec = importlib.util.spec_from_file_location("relay", RELAY_PATH)
relay = importlib.util.module_from_spec(spec)
sys.modules["relay"] = relay
spec.loader.exec_module(relay)


async def _echo_server():
    async def handle(r, w):
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
        w.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_unix_to_tcp_roundtrip():
    server, port = await _echo_server()
    try:
        with tempfile.TemporaryDirectory() as d:
            sock_path = str(Path(d) / "relay.sock")

            async def on_connect(r, w):
                await relay.handle(r, w, lambda: asyncio.open_connection("127.0.0.1", port))

            unix_server = await asyncio.start_unix_server(on_connect, path=sock_path)
            serve_task = asyncio.ensure_future(unix_server.serve_forever())
            await asyncio.sleep(0.05)

            r, w = await asyncio.open_unix_connection(sock_path)
            w.write(b"round-trip-payload")
            w.write_eof()
            await w.drain()
            data = await r.read(100)
            assert data == b"round-trip-payload"

            serve_task.cancel()
            unix_server.close()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_pipe_forwards_partial_reads_until_eof():
    class FakeReader:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        async def read(self, n):
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

    class FakeWriter:
        def __init__(self):
            self.received = b""
            self.eof = False

        def write(self, data):
            self.received += data

        async def drain(self):
            pass

        def can_write_eof(self):
            return True

        def write_eof(self):
            self.eof = True

        def close(self):
            pass

    reader = FakeReader([b"hello-", b"world"])
    writer = FakeWriter()
    await relay.pipe(reader, writer)
    assert writer.received == b"hello-world"
    assert writer.eof is True


def test_parse_host_port():
    assert relay._parse_host_port("127.0.0.1:8080") == ("127.0.0.1", 8080)


def test_parse_host_port_rejects_missing_host():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        relay._parse_host_port(":8080")
