"""HTTP front end: routing, JSON envelope, threaded server."""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import accounts
import wallet
from common import LOCK, ApiError

MODULES = [accounts, wallet]

ROUTES = [(m, re.compile(p), fn) for mod in MODULES for (m, p, fn) in mod.ROUTES]


class Req:
    def __init__(self, method, path, query, headers, raw):
        self.method, self.path, self.query = method, path, query
        self.headers, self.raw = headers, raw
        self.params = ()


def dispatch(req):
    allowed = False
    for method, rx, fn in ROUTES:
        m = rx.fullmatch(req.path)
        if m:
            if method == req.method:
                req.params = m.groups()
                with LOCK:
                    return fn(req)
            allowed = True
    if allowed:
        raise ApiError(405, "method_not_allowed", "method not allowed")
    raise ApiError(404, "not_found", "no such route")


def error_body(code, message):
    return {"error": {"code": code, "message": message}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60

    def log_message(self, *args):
        pass

    def _read_body(self):
        te = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in te:
            chunks = []
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            return b"".join(chunks)
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        return self.rfile.read(int(length))

    def _serve(self):
        try:
            try:
                raw = self._read_body()
            except (ValueError, OSError):
                self.close_connection = True
                raise ApiError(400, "malformed_request", "bad request framing")
            parts = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
            req = Req(self.command, unquote(parts.path), query, self.headers, raw)
            status, payload = dispatch(req)
        except ApiError as e:
            status, payload = e.status, error_body(e.code, e.message)
        except Exception as e:  # never leak a traceback; still a well-formed error body
            status, payload = 500, error_body("internal_error", type(e).__name__)
        if payload is None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _serve


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def make_server(port, host="0.0.0.0"):
    return Server((host, port), Handler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 8080)
    srv = make_server(port)
    print("listening on %d" % port, file=sys.stderr, flush=True)
    srv.serve_forever()
