"""An OpenAI-compatible stand-in for the team's LLM server, recording what
OpenCode sends it.

The real OpenCode suite (test_opencode_real.py) points ocbox at this instead of
a model: every request body is kept, so a test can read the exact system
prompt and tool list OpenCode assembled. It can also play a scripted
conversation: given a list of tool calls, it issues the next one each time the
conversation holds one more tool result, then answers with plain text. That is
how a test makes OpenCode actually exercise a tool - and a permission - without
a model deciding to.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _text(content: Any) -> str:
    """A message's content as plain text: OpenCode sends a string or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


class StubLLM:
    def __init__(self, scenario: list[dict] | None = None) -> None:
        self.scenario = list(scenario or [])
        self.requests: list[dict] = []
        self.port = 0
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    # ---- what OpenCode sent ------------------------------------------------------

    def tool_requests(self) -> list[dict]:
        """The requests of the agent loop itself; title generation carries no tools."""
        with self._lock:
            return [body for body in self.requests if body.get("tools")]

    @staticmethod
    def system_prompt(request: dict) -> str:
        messages = request.get("messages", [])
        return "\n".join(_text(m.get("content")) for m in messages if m.get("role") == "system")

    @staticmethod
    def tool_names(request: dict) -> set[str]:
        return {tool["function"]["name"] for tool in request.get("tools", [])}

    @staticmethod
    def tool_results(request: dict) -> list[str]:
        messages = request.get("messages", [])
        return [_text(m.get("content")) for m in messages if m.get("role") == "tool"]

    # ---- serving -------------------------------------------------------------------

    def _reply(self, body: dict) -> dict:
        if not body.get("tools"):
            return {"role": "assistant", "content": "stub title"}
        done = sum(1 for m in body.get("messages", []) if m.get("role") == "tool")
        if done < len(self.scenario):
            call = self.scenario[done]
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": f"call_{done}",
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "stub done"}

    def __enter__(self) -> StubLLM:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # untyped args: stdlib signature
                pass

            def _send_json(self, payload: dict, status: int = 200) -> None:
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_body(self) -> bytes:
                if "chunked" not in self.headers.get("Transfer-Encoding", ""):
                    return self.rfile.read(int(self.headers.get("Content-Length", 0)))
                data = b""
                while True:
                    size = int(self.rfile.readline().strip() or b"0", 16)
                    if size == 0:
                        self.rfile.readline()
                        return data
                    data += self.rfile.read(size)
                    self.rfile.readline()

            def do_GET(self) -> None:  # non-PEP8 name: stdlib handler method
                self._send_json({"object": "list", "data": [{"id": "stub", "object": "model"}]})

            def do_POST(self) -> None:  # non-PEP8 name: stdlib handler method
                body = json.loads(self._read_body() or b"{}")
                with stub._lock:
                    stub.requests.append(body)
                    n = next(stub._ids)
                message = stub._reply(body)
                finish = "tool_calls" if "tool_calls" in message else "stop"
                base = {"id": f"cmpl-{n}", "created": int(time.time()), "model": "stub"}
                usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
                if not body.get("stream"):
                    self._send_json(
                        {
                            **base,
                            "object": "chat.completion",
                            "usage": usage,
                            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        }
                    )
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                chunks = [
                    {"choices": [{"index": 0, "delta": message, "finish_reason": None}]},
                    {
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                        "usage": usage,
                    },
                ]
                for chunk in chunks:
                    payload = {**base, "object": "chat.completion.chunk", **chunk}
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
