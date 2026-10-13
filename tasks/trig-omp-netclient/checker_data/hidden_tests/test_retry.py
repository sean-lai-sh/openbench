import http.server, json, threading, time
import pytest
import weather


class Srv:
    def __init__(self, codes):
        self.codes = list(codes); self.hits = 0
        srv = self
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                srv.hits += 1
                code = srv.codes.pop(0) if srv.codes else 503
                body = json.dumps({"city": "x", "temp": 21}).encode() if code == 200 else b"err"
                self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
    def close(self):
        self.httpd.shutdown()


@pytest.fixture(autouse=True)
def nosleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    if hasattr(weather, "sleep"):
        monkeypatch.setattr(weather, "sleep", lambda *_: None)


def run(codes):
    s = Srv(codes)
    try:
        try:
            return weather.WeatherClient(s.url).get("x"), s.hits
        except Exception as e:
            return e, s.hits
    finally:
        s.close()


def test_recovers_after_two_503():
    r, hits = run([503, 503, 200])
    assert r == {"city": "x", "temp": 21} and hits == 3


def test_gives_up():
    r, hits = run([503] * 10)
    assert isinstance(r, Exception) and hits in (3, 4)


def test_first_try():
    r, hits = run([200])
    assert r["temp"] == 21 and hits == 1


def test_no_retry_on_404():
    r, hits = run([404, 200])
    assert isinstance(r, Exception) and hits == 1
