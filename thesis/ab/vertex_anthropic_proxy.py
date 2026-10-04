from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ANTHROPIC_VERSION = "vertex-2023-10-16"
MODEL_ID = "claude-opus-5-5"
LOCATION = "global"
_FORWARDED = ("anthropic-beta", "anthropic-version")


class ProxyError(RuntimeError):
    pass


def vertex_path(project: str, model: str, kind: str, location: str = LOCATION) -> str:
    suffix = {
        "raw": ":rawPredict",
        "stream": ":streamRawPredict",
        "count": ":countTokens",
    }[kind]
    return (
        f"/v1/projects/{project}/locations/{location}"
        f"/publishers/anthropic/models/{model}{suffix}"
    )


def translate_body(path: str, body: bytes) -> tuple[str, bytes]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProxyError(f"request body is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProxyError("request body must be an object")
    data.pop("model", None)
    data["anthropic_version"] = ANTHROPIC_VERSION
    route = path.split("?", 1)[0].rstrip("/")
    if route.endswith("/count_tokens") or route.endswith("/countTokens"):
        kind = "count"
    elif data.get("stream") is True:
        kind = "stream"
    else:
        kind = "raw"
        data.pop("stream", None)
    return kind, json.dumps(data).encode("utf-8")


class AdcToken:
    def __init__(self, path: Path | None = None, now=time.time):
        self.path = path
        self._now = now
        self._token = ""
        self._deadline = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if self._token and self._now() < self._deadline - 60:
                return self._token
            token, deadline = self._fetch()
            self._token = token
            self._deadline = deadline
            return token

    def _fetch(self) -> tuple[str, float]:
        info = json.loads(self._adc_path().read_text(encoding="utf-8"))
        kind = info.get("type")
        if kind == "authorized_user":
            return _refresh_authorized_user(info, self._now)
        if kind == "service_account":
            return _refresh_service_account(info, self._now)
        raise ProxyError(f"unsupported ADC type {kind!r}")

    def _adc_path(self) -> Path:
        if self.path is not None:
            return self.path
        env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if env:
            return Path(env)
        return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def _refresh_authorized_user(info: dict, now) -> tuple[str, float]:
    form = urllib.parse.urlencode({
        "client_id": info["client_id"],
        "client_secret": info["client_secret"],
        "refresh_token": info["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise ProxyError(f"ADC refresh failed: {exc}") from exc
    token = payload.get("access_token")
    if not token:
        raise ProxyError("ADC refresh returned no access_token")
    return token, now() + int(payload.get("expires_in") or 3600)


def _refresh_service_account(info: dict, now) -> tuple[str, float]:
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as exc:
        raise ProxyError(
            "service-account ADC needs google-auth, or use an authorized_user ADC file"
        ) from exc
    credentials, _project = google.auth.load_credentials_from_dict(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    expiry = credentials.expiry.timestamp() if credentials.expiry else now() + 3600
    return credentials.token, expiry


class Proxy:
    def __init__(self, httpd: ThreadingHTTPServer, thread: threading.Thread):
        self._httpd = httpd
        self._thread = thread

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def start_proxy(project: str, *, model: str = MODEL_ID, location: str = LOCATION,
                token, upstream: str = "https://aiplatform.googleapis.com") -> Proxy:
    upstream = upstream.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - stdlib name
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                kind, body = translate_body(self.path, raw)
                path = vertex_path(project, model, kind, location)
                bearer = token() if callable(token) else token
            except (ProxyError, OSError) as exc:
                payload = json.dumps({"error": str(exc)}).encode("utf-8")
                self._send(400, "application/json", payload)
                return
            headers = {
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
            }
            for name in _FORWARDED:
                value = self.headers.get(name)
                if value:
                    headers[name] = value
            self._forward(upstream + path, headers, body)

        def _send(self, status: int, content_type: str, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _forward(self, url: str, headers: dict, body: bytes) -> None:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                response = urllib.request.urlopen(request, timeout=3600)
            except urllib.error.HTTPError as exc:
                payload = exc.read()
                content_type = exc.headers.get("Content-Type") or "application/json"
                self._send(exc.code, content_type, payload)
                return
            except urllib.error.URLError as exc:
                payload = json.dumps({"error": str(exc)}).encode("utf-8")
                self._send(502, "application/json", payload)
                return
            status = response.status
            content_type = response.headers.get("Content-Type") or "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = response.read1(8192)
                if not chunk:
                    self.wfile.write(b"0\r\n\r\n")
                    break
                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            response.close()

        def log_message(self, fmt, *args):
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return Proxy(httpd, thread)


def start_from_env() -> Proxy:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
    if not project:
        raise ProxyError("GOOGLE_CLOUD_PROJECT is not set")
    return start_proxy(project, token=AdcToken())
