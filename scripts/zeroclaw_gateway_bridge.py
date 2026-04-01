#!/usr/bin/env python3
"""
ZeroClaw Gateway Bridge

A lightweight HTTP bridge for remote orchestration workflows:
1) OTP / pairing-code operations (read / rotate / pair)
2) Config operations (read / update)

Design intent:
- Run this script on the same host as `zeroclaw gateway`.
- It can access localhost-only admin routes (`/admin/paircode*`).
- It exposes a narrow external API that your B-side can call.

No third-party dependencies; uses Python stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Optional


@dataclass
class BridgeConfig:
    gateway_base: str
    listen_host: str
    listen_port: int
    bridge_token: Optional[str]
    default_pairing_code: Optional[str]


def _json_dumps(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout: float = 10.0,
) -> tuple[int, bytes, Dict[str, str]]:
    req = urllib.request.Request(url=url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            data = resp.read()
            resp_headers = {k: v for k, v in resp.headers.items()}
            return status, data, resp_headers
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b"", {k: v for k, v in e.headers.items()}


def _decode_json_or_text(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="replace")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


class BridgeHandler(BaseHTTPRequestHandler):
    server: "BridgeServer"

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        data = _json_dumps(payload)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _require_bridge_token(self) -> bool:
        token = self.server.bridge_cfg.bridge_token
        if not token:
            return True
        incoming = self.headers.get("X-Bridge-Token", "")
        if incoming != token:
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": "Unauthorized: invalid or missing X-Bridge-Token"},
            )
            return False
        return True

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _gateway_url(self, path: str) -> str:
        base = self.server.bridge_cfg.gateway_base.rstrip("/")
        return f"{base}{path}"

    def _get_bearer(self) -> Optional[str]:
        auth = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if auth.startswith(prefix):
            return auth[len(prefix) :].strip()
        return None

    def log_message(self, format: str, *args: Any) -> None:
        # concise stderr logging
        sys.stderr.write("[bridge] " + (format % args) + "\n")

    # ---------- Routes ----------
    def do_GET(self) -> None:
        if not self._require_bridge_token():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "zeroclaw-gateway-bridge"})
            return

        if path == "/otp":
            status, raw, _ = _http_request("GET", self._gateway_url("/admin/paircode"))
            payload = _decode_json_or_text(raw)
            self._send_json(status, {"ok": 200 <= status < 300, "gateway": payload})
            return

        if path == "/config":
            token = self._get_bearer()
            if not token:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Missing Authorization: Bearer <token>"},
                )
                return
            status, raw, _ = _http_request(
                "GET",
                self._gateway_url("/api/config"),
                headers={"Authorization": f"Bearer {token}"},
            )
            payload = _decode_json_or_text(raw)
            self._send_json(status, {"ok": 200 <= status < 300, "gateway": payload})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not Found"})

    def do_POST(self) -> None:
        if not self._require_bridge_token():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        raw_body = self._read_body()
        body_json: Dict[str, Any] = {}

        if raw_body:
            try:
                decoded = json.loads(raw_body.decode("utf-8"))
                if isinstance(decoded, dict):
                    body_json = decoded
            except json.JSONDecodeError:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Body must be valid JSON object"},
                )
                return

        if path == "/otp/new":
            status, raw, _ = _http_request("POST", self._gateway_url("/admin/paircode/new"))
            payload = _decode_json_or_text(raw)
            self._send_json(status, {"ok": 200 <= status < 300, "gateway": payload})
            return

        if path == "/pair":
            code = str(body_json.get("pairing_code") or "").strip()
            if not code:
                code = (self.server.bridge_cfg.default_pairing_code or "").strip()
            if not code:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "pairing_code is required (or set BRIDGE_DEFAULT_PAIRING_CODE)",
                    },
                )
                return

            status, raw, _ = _http_request(
                "POST",
                self._gateway_url("/pair"),
                headers={"X-Pairing-Code": code},
            )
            payload = _decode_json_or_text(raw)
            self._send_json(status, {"ok": 200 <= status < 300, "gateway": payload})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not Found"})

    def do_PUT(self) -> None:
        if not self._require_bridge_token():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path != "/config":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not Found"})
            return

        token = self._get_bearer()
        if not token:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "Missing Authorization: Bearer <token>"},
            )
            return

        raw_body = self._read_body()
        if not raw_body:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Empty body"})
            return

        # Accept either raw TOML bytes or JSON {"content": "...toml..."}
        content_type = self.headers.get("Content-Type", "")
        toml_payload: bytes

        if "application/json" in content_type:
            try:
                obj = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid JSON"})
                return
            if not isinstance(obj, dict) or not isinstance(obj.get("content"), str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "JSON body must be {\"content\": \"<toml>\"}"},
                )
                return
            toml_payload = obj["content"].encode("utf-8")
        else:
            toml_payload = raw_body

        status, raw, _ = _http_request(
            "PUT",
            self._gateway_url("/api/config"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/plain; charset=utf-8",
            },
            body=toml_payload,
            timeout=20.0,
        )
        payload = _decode_json_or_text(raw)
        self._send_json(status, {"ok": 200 <= status < 300, "gateway": payload})


class BridgeServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_cls: type[BridgeHandler], cfg: BridgeConfig):
        super().__init__(server_address, handler_cls)
        self.bridge_cfg = cfg


def parse_args() -> BridgeConfig:
    parser = argparse.ArgumentParser(description="ZeroClaw gateway bridge")
    parser.add_argument("--gateway-base", default=os.environ.get("ZEROCLAW_GATEWAY_BASE", "http://127.0.0.1:42617"))
    parser.add_argument("--host", default=os.environ.get("BRIDGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BRIDGE_PORT", "18080")))
    parser.add_argument("--bridge-token", default=os.environ.get("BRIDGE_TOKEN"))
    parser.add_argument(
        "--default-pairing-code",
        default=os.environ.get("BRIDGE_DEFAULT_PAIRING_CODE"),
        help="optional fallback pairing code for /pair when body omits pairing_code",
    )
    args = parser.parse_args()
    return BridgeConfig(
        gateway_base=args.gateway_base,
        listen_host=args.host,
        listen_port=args.port,
        bridge_token=args.bridge_token,
        default_pairing_code=args.default_pairing_code,
    )


def main() -> int:
    cfg = parse_args()
    print("[bridge] starting")
    print(f"[bridge] listen: http://{cfg.listen_host}:{cfg.listen_port}")
    print(f"[bridge] gateway: {cfg.gateway_base}")
    if cfg.bridge_token:
        print("[bridge] auth: X-Bridge-Token enabled")
    else:
        print("[bridge] auth: disabled (set BRIDGE_TOKEN to enable)")

    srv = BridgeServer((cfg.listen_host, cfg.listen_port), BridgeHandler, cfg)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] stopping")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
