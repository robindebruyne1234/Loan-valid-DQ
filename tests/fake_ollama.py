"""A stand-in for the Ollama HTTP API, for tests that must not need a model.

It answers ``/api/generate`` and ``/api/tags`` in Ollama's own shapes with
whatever the test scripts, and records every request body so a test can
assert on what was actually sent. It never writes SQL of its own: every
statement it returns is one a test put there.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

MODEL = "qwen2.5-coder:3b"


def answer(sql: str) -> str:
    """The text a well-behaved model returns: the answer contract as JSON.

    :param sql: The statement to put in it.
    :returns: The JSON text.
    """
    return json.dumps({"sql": sql, "reasoning": "scripted by the test",
                       "assumptions": [], "caveats": []})


def generate_payload(response_text: str, **overrides: Any) -> dict[str, Any]:
    """An ``/api/generate`` reply as Ollama shapes it.

    :param response_text: The model's text.
    :param overrides: Fields to replace, for example ``done_reason``.
    :returns: The reply body.
    """
    payload: dict[str, Any] = {
        "model": MODEL, "created_at": "2026-10-27T00:00:00Z", "response": response_text,
        "done": True, "done_reason": "stop", "context": list(range(50)),
        "total_duration": 2_000_000_000, "load_duration": 100_000_000,
        "prompt_eval_count": 8_000, "prompt_eval_duration": 1_500_000_000,
        "eval_count": 120, "eval_duration": 400_000_000,
    }
    payload.update(overrides)
    return payload


@dataclass
class FakeOllama:
    """What the fake server returns, and what it was sent.

    :ivar url: Base URL of the running server.
    :ivar status: HTTP status for ``/api/generate``.
    :ivar body: Reply for ``/api/generate``: a dict is sent as JSON, a str raw.
    :ivar delay: Seconds to wait before replying, to provoke a timeout.
    :ivar models: Model tags ``/api/tags`` lists.
    :ivar requests: Every ``/api/generate`` request body received.
    """

    url: str = ""
    status: int = 200
    body: Any = None
    delay: float = 0.0
    models: list[str] = field(default_factory=lambda: [MODEL])
    requests: list[dict[str, Any]] = field(default_factory=list)

    def answers(self, sql: str) -> None:
        """Script a normal, successful answer carrying this SQL.

        :param sql: The statement the "model" returns.
        :returns: ``None``.
        """
        self.status, self.body, self.delay = 200, generate_payload(answer(sql)), 0.0


@contextmanager
def running() -> Iterator[FakeOllama]:
    """Run a fake Ollama on an ephemeral local port.

    :yields: The :class:`FakeOllama` controlling it.
    """
    fake = FakeOllama()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _reply(self, status: int, body: Any) -> None:
            data = (body.encode("utf-8") if isinstance(body, str)
                    else json.dumps(body).encode("utf-8"))
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # the client gave up first, which is what a timeout test wants

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/tags":
                return self._reply(200, {"models": [{"name": m} for m in fake.models]})
            return self._reply(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            fake.requests.append(json.loads(self.rfile.read(length) or b"{}"))
            if fake.delay:
                time.sleep(fake.delay)
            return self._reply(fake.status, fake.body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()


def closed_port_url() -> str:
    """A local URL on which nothing is listening.

    :returns: ``http://127.0.0.1:<port>`` for a port that was free a moment ago.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"
