"""trace-review-kit server: serves the review page and a JSON annotation store. Standard library only.

    python server.py --samples review/samples.json --annotations review/annotations.json \
                     [--config review/review.json] [--port 8020]

Routes:  GET /            the page          GET /theme.css
         GET /api/samples GET /api/config   GET /api/annotations   POST /api/annotations (whole list, atomic write)
The page autosaves on every change, so the annotations file is always current; keep it in git if the
review is a deliverable. Samples are re-read on every request, so regenerating them needs no restart.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = threading.Lock()
PATHS: dict[str, Path | None] = {}


def _read_json(path: Path | None, default):
    if not path or not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"error": f"{path.name}: invalid JSON: {exc.msg}"}


def _write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html")
        if path == "/theme.css":
            return self._send(200, (HERE / "theme.css").read_bytes(), "text/css")
        if path == "/api/samples":
            return self._send(200, _read_json(PATHS["samples"], []))
        if path == "/api/config":
            return self._send(200, _read_json(PATHS["config"], {"fields": []}))
        if path == "/api/annotations":
            return self._send(200, _read_json(PATHS["annotations"], []))
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/api/annotations":
            return self._send(404, {"error": "not found"})
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0)
        try:
            data = json.loads(raw or b"[]")
        except json.JSONDecodeError as exc:
            return self._send(400, {"ok": False, "error": f"invalid JSON: {exc.msg}"})
        if isinstance(data, dict):
            data = data.get("annotations", [])
        if not isinstance(data, list):
            return self._send(400, {"ok": False, "error": "expected a list of annotations"})
        with LOCK:
            _write_json_atomic(PATHS["annotations"], data)
        self._send(200, {"ok": True, "count": len(data)})

    def log_message(self, *_args) -> None:  # keep the terminal quiet
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=Path, required=True, help="normalized samples JSON written by your adapter")
    ap.add_argument("--annotations", type=Path, required=True, help="where decisions are stored (created on first save)")
    ap.add_argument("--config", type=Path, default=None, help="review.json describing the decision fields (default: a single note)")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    PATHS.update(samples=args.samples, annotations=args.annotations, config=args.config)
    if not args.samples.exists():
        print(f"warning: {args.samples} does not exist yet; the page will show an empty state until it does")
    print(f"trace review on http://{args.host}:{args.port}/  samples={args.samples}  annotations={args.annotations}  config={args.config or '(default)'}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
