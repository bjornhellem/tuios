#!/usr/bin/env python3
"""Simple HTTP chat server for TuiOS."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from chat_common import CHAT_PORT, append_log, load_peers, peer_name


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class ChatHandler(BaseHTTPRequestHandler):
        server_version = "TuiOSChat/0.1"

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path.rstrip("/") != "/message":
                self.send_error(404, "Not Found")
                return

            client_ip = self.client_address[0]
            peers = load_peers()
            if client_ip not in peers:
                self.send_error(403, "Forbidden")
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            message = ""
            content_type = (self.headers.get("Content-Type") or "").lower()

            if "application/json" in content_type:
                try:
                    payload = json.loads(raw.decode("utf-8", errors="replace"))
                    message = str(payload.get("message", "")).strip()
                except Exception:
                    message = ""
            else:
                message = raw.decode("utf-8", errors="replace").strip()

            if not message:
                self.send_error(400, "Empty message")
                return

            append_log(
                {
                    "direction": "in",
                    "ip": client_ip,
                    "nickname": peer_name(client_ip, peers),
                    "message": message,
                }
            )

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path.rstrip("/") != "/status":
                self.send_error(404, "Not Found")
                return

            client_ip = self.client_address[0]
            peers = load_peers()
            if client_ip not in peers:
                self.send_error(403, "Forbidden")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            payload = json.dumps({"ok": True, "nickname": peer_name(client_ip, peers)})
            self.wfile.write(payload.encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            # Silence default console logging.
            return

    return ChatHandler


class ChatServer:
    def __init__(self, host: str = "0.0.0.0", port: int = CHAT_PORT) -> None:
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> tuple[bool, str]:
        try:
            self._server = ThreadingHTTPServer((self._host, self._port), _make_handler())
            self._server.daemon_threads = True
        except OSError as exc:
            return False, f"Chat server failed to bind {self._host}:{self._port} ({exc})."

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return True, f"Chat server listening on {self._port}."

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass
        self._server = None
