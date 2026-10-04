"""Browser UI: one static shell, rendered client-side per route."""
import os

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PAGES = {"/": "Wallet", "/requests": "Requests", "/split": "Split a bill", "/signup": "Sign up",
         "/login": "Log in", "/authorizations": "Holds"}
SHARED = ("/requests", "/authorizations")  # also JSON API paths: HTML only for Accept: text/html
ASSETS = {"/static/app.css": "text/css; charset=utf-8",
          "/static/app.js": "application/javascript; charset=utf-8"}


def _read(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read()


def serve(req):
    """Return (status, bytes, content-type) for a UI request, or None."""
    if req.method not in ("GET", "HEAD"):
        return None
    path = req.path.rstrip("/") or "/"
    if path in ASSETS:
        return 200, _read(path.rsplit("/", 1)[1]), ASSETS[path]
    if path not in PAGES:
        return None
    if path in SHARED and "text/html" not in req.headers.get("Accept", ""):
        return None
    html = _read("index.html").decode("utf-8").replace("{{title}}", PAGES[path])
    return 200, html.encode("utf-8"), "text/html; charset=utf-8"
