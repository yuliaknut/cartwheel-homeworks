"""Review server for Homework 4: the reference file-backed API plus labels.

Adapted from ``analysis/server.py`` (the instructor's error-discovery server).
The JSON API is the same table of state files, so the agent-side workflow
(push samples, push the taxonomy, push suggestions, watch annotations) works
unchanged. Three additions:

  * ``GET /``                 serves ``analysis/review_app/index.html``
  * ``GET /api/index``        the compact trace index (coverage tables)
  * ``GET /api/manifest``     ``sample_manifest.json`` (why each trace was picked)
  * ``GET /api/labels``       the live label per (mode, trace), collapsed from
                              the append-only ``labels/<mode>.jsonl`` files
  * ``GET /api/judges``       judge verdicts and critiques (test verdicts hidden until frozen)
  * ``POST /api/labels``      one present/absent decision. Appends a record
                              (a flip marks the prior record ``superseded_by``;
                              a clear marks it ``retracted``; nothing is ever
                              deleted) and writes the accepted label to
                              Langfuse as a numeric score named after the mode
                              (1 = failure present), through the instructor's
                              ``langfuse_io`` helpers.

Open-coding notes carry no ``mode``/``label`` pair, so nothing is written to
Langfuse when the page saves annotations; only labels become scores.

    uv run python -m analysis.review_app.server                       # :8020, analysis/state
    uv run python -m analysis.review_app.server --port 8030 --state /tmp/state --no-langfuse
    uv run python -m analysis.review_app.server --state analysis/state/hw3 --ui analysis/ui/pilot_review.html
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from analysis.server import _guess_type, _read_json, _write_json
from observability.instrument import load_env

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_STATE = REPO_ROOT / "analysis" / "state"

# Filled in by main(); module-level so the handler class (instantiated per
# request by http.server) can see them.
CONFIG: dict[str, Any] = {"state": DEFAULT_STATE, "ui": HERE / "index.html", "langfuse": True}
_LOCK = threading.Lock()
_SCORE_CONFIGS: set[str] = set()

API_DEFAULTS: dict[str, Any] = {
    "samples": [],
    "annotations": [],
    "patterns": {"modes": []},
    "suggestions": [],
    "manifest": {},
    "index": [],
    "traces": [],
}
API_FILES: dict[str, str] = {
    "samples": "samples.json",
    "annotations": "annotations.json",
    "patterns": "patterns.json",
    "suggestions": "suggestions.json",
    "manifest": "sample_manifest.json",
    "index": "trace_index.json",
    "traces": "traces.json",
}
WRITABLE = {"samples", "annotations", "patterns", "suggestions"}


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _state_file(name: str) -> Path:
    return Path(CONFIG["state"]) / API_FILES[name]


# ---------------------------------------------------------------------------
# labels: append-only jsonl per mode, collapsed to the live label per trace
# ---------------------------------------------------------------------------


def _labels_dir() -> Path:
    return Path(CONFIG["state"]) / "labels"


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _live_labels(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    live: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("superseded_by"):
            continue
        if row.get("label") not in (0, 1):
            continue
        live[row["trace_id"]] = row
    return live


def read_all_labels() -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    d = _labels_dir()
    if not d.exists():
        return out
    for path in sorted(d.glob("*.jsonl")):
        out[path.stem] = _live_labels(_read_rows(path))
    return out


def read_judges() -> list[dict[str, Any]]:
    """Judge verdicts and critiques for the review page, one entry per judge version.

    Homework 5 forbids looking at test predictions before the judge is frozen,
    so a judge that is not frozen exposes only its train and dev verdicts.
    Predictions are Pass = 1 (``label_convention: pass_positive``).
    """
    state = Path(CONFIG["state"])
    splits = _read_json(state / "splits.json", {})
    out: list[dict[str, Any]] = []
    for path in sorted((state / "judges").glob("*.json")):
        if path.name.startswith("_"):
            continue
        judge = _read_json(path, None)
        if not isinstance(judge, dict) or "prompt_hash" not in judge:
            continue
        mode_splits = splits.get(judge.get("mode"), {})
        visible = set(mode_splits.get("train", [])) | set(mode_splits.get("dev", []))
        frozen = judge.get("status") == "frozen"
        preds = (judge.get("predictions") or {}).get(judge["prompt_hash"], {})
        crits = (judge.get("critiques") or {}).get(judge["prompt_hash"], {})
        keep = lambda tid: frozen or tid in visible
        out.append({
            "judge_id": judge.get("judge_id"), "mode": judge.get("mode"), "version": judge.get("version"),
            "status": judge.get("status"), "model": judge.get("model"), "created_at": judge.get("created_at"),
            "split_of": {tid: name for name in ("train", "dev", "test") for tid in mode_splits.get(name, [])},
            "predictions": {tid: v for tid, v in preds.items() if keep(tid)},
            "critiques": {tid: c for tid, c in crits.items() if keep(tid)},
        })
    return out


def write_label(body: dict[str, Any]) -> dict[str, Any]:
    """Apply one decision: label 0/1 sets, label null clears. Returns a status dict."""
    mode = str(body.get("mode") or "").strip()
    trace_id = str(body.get("trace_id") or "").strip()
    label = body.get("label")
    if not mode or not trace_id or label not in (0, 1, None):
        raise ValueError("expected mode, trace_id, and label 0, 1, or null")
    path = _labels_dir() / f"{mode}.jsonl"
    with _LOCK:
        rows = _read_rows(path)
        prior = _live_labels(rows).get(trace_id)
        n = sum(1 for r in rows if r.get("trace_id") == trace_id)
        if label is None:
            if prior is None:
                return {"ok": True, "changed": False, "langfuse": "nothing to clear"}
            prior["superseded_by"] = f"retracted@{_utcnow()}"
            _write_rows(path, rows)
            return {"ok": True, "changed": True, "langfuse": _delete_score(trace_id, mode)}
        if prior is not None and prior.get("label") == label:
            return {"ok": True, "changed": False, "langfuse": "unchanged"}
        record = {
            "trace_id": trace_id,
            "label": int(label),
            "source": body.get("source") or "human",
            "ts": _utcnow(),
            "label_id": f"{trace_id}#{n}",
        }
        for key in ("scenario_id", "session_id", "note", "annotation_id"):
            if body.get(key):
                record[key] = body[key]
        if prior is not None:
            prior["superseded_by"] = record["label_id"]
        rows.append(record)
        _write_rows(path, rows)
    return {"ok": True, "changed": True, "label_id": record["label_id"], "langfuse": _write_score(trace_id, mode, int(label), body.get("note"))}


def _write_score(trace_id: str, mode: str, label: int, note: str | None) -> str:
    if not CONFIG.get("langfuse"):
        return "skipped (--no-langfuse)"
    try:
        from analysis.helpers import langfuse_io
    except Exception as exc:  # pragma: no cover
        return f"skipped ({exc})"
    if not langfuse_io.is_configured():
        return "skipped (LANGFUSE_* not configured)"
    try:
        client = langfuse_io._client()
        if mode not in _SCORE_CONFIGS:
            langfuse_io.ensure_score_config(mode, client=client)
            _SCORE_CONFIGS.add(mode)
        _delete_score(trace_id, mode, client=client)  # one live score per (trace, mode)
        langfuse_io.write_label_score(trace_id=trace_id, mode=mode, label=label, comment=note, client=client)
        return "written"
    except Exception as exc:
        return f"failed: {type(exc).__name__}: {str(exc)[:160]}"


def _delete_score(trace_id: str, mode: str, client: Any | None = None) -> str:
    if not CONFIG.get("langfuse"):
        return "skipped (--no-langfuse)"
    try:
        from analysis.helpers import langfuse_io
        if not langfuse_io.is_configured():
            return "skipped (LANGFUSE_* not configured)"
        lf = client or langfuse_io._client()
        resp = lf.api.score_v_2.get(trace_id=trace_id, name=mode, limit=50)
        deleted = 0
        for score in getattr(resp, "data", None) or []:
            lf.api.score.delete(score.id)
            deleted += 1
        return f"deleted {deleted}"
    except Exception as exc:
        return f"delete failed: {type(exc).__name__}: {str(exc)[:160]}"


# ---------------------------------------------------------------------------
# handler
# ---------------------------------------------------------------------------


class ReviewAppHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        return

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": f"not found: {path.name}"}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({}, status=204)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_file(Path(CONFIG["ui"]), "text/html; charset=utf-8")
            return
        if path.startswith("/ui/"):
            asset = HERE / path[len("/ui/"):]
            if asset.is_file() and HERE in asset.resolve().parents:
                self._send_file(asset, _guess_type(asset))
                return
        if path == "/api/labels":
            self._send_json(read_all_labels())
            return
        if path == "/api/judges":
            self._send_json(read_judges())
            return
        name = path[len("/api/"):] if path.startswith("/api/") else None
        if name in API_FILES:
            self._send_json(_read_json(_state_file(name), API_DEFAULTS[name]))
            return
        self._send_json({"error": f"unknown path: {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        data = self._read_body()
        if data is None:
            self._send_json({"error": "expected a JSON body"}, status=400)
            return
        if path == "/api/labels":
            try:
                self._send_json(write_label(data))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        name = path[len("/api/"):] if path.startswith("/api/") else None
        if name not in WRITABLE:
            self._send_json({"error": f"cannot POST to {path}"}, status=404)
            return
        with _LOCK:
            _write_json(_state_file(name), data)
        count = len(data) if isinstance(data, (list, dict)) else 0
        self._send_json({"ok": True, "count": count})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state directory (default analysis/state)")
    parser.add_argument("--ui", type=Path, default=HERE / "index.html", help="HTML file to serve at /")
    parser.add_argument("--no-langfuse", action="store_true", help="never write or delete Langfuse scores (smoke tests)")
    args = parser.parse_args()
    load_env()
    CONFIG.update({"state": args.state.resolve(), "ui": args.ui.resolve(), "langfuse": not args.no_langfuse})
    Path(CONFIG["state"]).mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), ReviewAppHandler)
    print(f"review app on http://{args.host}:{args.port}/")
    print(f"state: {CONFIG['state']}  ui: {CONFIG['ui']}  langfuse scores: {'on' if CONFIG['langfuse'] else 'off'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
