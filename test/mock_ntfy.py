#!/usr/bin/env python3
"""Small reusable ntfy-compatible HTTP fixture for bridge tests and manual checks."""

from __future__ import annotations

import argparse
import base64
import json
import queue
import secrets
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class MockState:
    def __init__(self, name: str, token: str = "") -> None:
        self.name = name
        self.token = token
        self.cache: list[dict[str, Any]] = []
        self.listeners: list[queue.Queue[dict[str, Any]]] = []
        self.actions: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> dict[str, Any]:
        item = dict(event)
        item.setdefault("event", "message")
        item.setdefault("id", secrets.token_hex(6))
        item.setdefault("time", int(time.time()))
        with self.lock:
            self.cache.append(item)
            listeners = list(self.listeners)
        for listener in listeners:
            listener.put(item)
        return item


class MockNtfyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mock-ntfy/1"

    @property
    def state(self) -> MockState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def authorized(self) -> bool:
        return not self.state.token or self.headers.get("Authorization") == f"Bearer {self.state.token}"

    def send_bytes(self, status: int, body: bytes = b"", content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)
            self.wfile.flush()

    def send_json(self, status: int, value: Any) -> None:
        self.send_bytes(status, json.dumps(value, separators=(",", ":")).encode(), "application/json")

    def read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/last-action":
            with self.state.lock:
                value = self.state.actions[-1] if self.state.actions else {}
            self.send_json(200, value)
            return
        if parsed.path in {"/view-target", "/action-target"}:
            if parsed.path == "/action-target":
                self.record_action(b"")
            self.send_bytes(200, b"ok", "text/plain")
            return
        if parsed.path == "/capture.png":
            self.record_action(b"")
            self.send_bytes(200, PNG, "image/png")
            return
        if parsed.path in {"/icon.png", "/attachment.png"}:
            if not self.authorized():
                self.send_bytes(401)
                return
            self.send_bytes(200, PNG, "image/png")
            return
        if parsed.path == "/huge.png":
            huge = PNG[:16] + (5000).to_bytes(4, "big") + PNG[20:]
            self.send_bytes(200, huge, "image/png")
            return
        if parsed.path == "/oversized.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(5 * 1024 * 1024 + 1))
            self.end_headers()
            return
        if parsed.path == "/bad-media":
            self.send_bytes(200, b"not an image", "application/octet-stream")
            return
        if parsed.path == "/redirect":
            target = urllib.parse.parse_qs(parsed.query).get("to", [""])[0]
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path.endswith("/json"):
            self.handle_stream(parsed)
            return
        self.send_bytes(404)

    def handle_stream(self, parsed: urllib.parse.SplitResult) -> None:
        if not self.authorized():
            self.send_bytes(401)
            return
        topic_segment = parsed.path.rsplit("/", 2)[-2]
        topics = set(urllib.parse.unquote(topic_segment).split(","))
        query = urllib.parse.parse_qs(parsed.query)
        since = query.get("since", ["all"])[0]
        poll = query.get("poll", ["0"])[0] == "1"
        with self.state.lock:
            cached = list(self.state.cache)
        if since == "latest":
            cached = []
        elif since != "all":
            found = next((index for index, item in enumerate(cached) if str(item.get("id")) == since), -1)
            cached = cached[found + 1:] if found >= 0 else cached
        cached = [item for item in cached if item.get("topic") in topics]

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close" if poll else "keep-alive")
        self.end_headers()
        if self.server.buffered_stream and not poll:
            time.sleep(1)
            self.close_connection = True
            return
        self.write_event({"event": "open", "id": secrets.token_hex(6), "time": int(time.time())})
        for event in cached:
            self.write_event(event)
        if poll:
            self.close_connection = True
            return

        listener: queue.Queue[dict[str, Any]] = queue.Queue()
        with self.state.lock:
            self.state.listeners.append(listener)
        try:
            while True:
                event = listener.get(timeout=30)
                if event.get("topic") in topics:
                    self.write_event(event)
        except (queue.Empty, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with self.state.lock:
                if listener in self.state.listeners:
                    self.state.listeners.remove(listener)
            self.close_connection = True

    def write_event(self, event: dict[str, Any]) -> None:
        self.wfile.write(json.dumps(event, separators=(",", ":")).encode() + b"\n")
        self.wfile.flush()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        body = self.read_body()
        if parsed.path == "/emit":
            if not self.authorized():
                self.send_bytes(401)
                return
            try:
                event = json.loads(body)
                if not isinstance(event, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                self.send_bytes(400)
                return
            self.send_json(200, self.state.emit(event))
            return
        if parsed.path == "/action-target":
            self.record_action(body)
            self.send_bytes(204)
            return
        self.send_bytes(404)

    def do_PUT(self) -> None:
        self.handle_action_method()

    def do_PATCH(self) -> None:
        self.handle_action_method()

    def do_DELETE(self) -> None:
        self.handle_action_method()

    def do_HEAD(self) -> None:
        if urllib.parse.urlsplit(self.path).path == "/action-target":
            self.record_action(b"")
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def handle_action_method(self) -> None:
        if urllib.parse.urlsplit(self.path).path != "/action-target":
            self.send_bytes(404)
            return
        body = self.read_body()
        self.record_action(body)
        self.send_bytes(204)

    def record_action(self, body: bytes) -> None:
        value = {
            "method": self.command,
            "path": urllib.parse.urlsplit(self.path).path,
            "headers": dict(self.headers.items()),
            "body": body.decode("utf-8", "replace"),
        }
        with self.state.lock:
            self.state.actions.append(value)


class MockNtfyServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], name: str = "Mock", token: str = "",
                 buffered_stream: bool = False) -> None:
        self.state = MockState(name, token)
        self.buffered_stream = buffered_stream
        super().__init__(address, MockNtfyHandler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--name", default="Mock")
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    server = MockNtfyServer(("127.0.0.1", args.port), args.name, args.token)
    print(f"{args.name} mock ntfy listening on 127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
