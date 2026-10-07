"""Turn the annotation store into one JSONL row per reviewed item, applying the config's defaults.

    python export.py --samples review/samples.json --annotations review/annotations.json \
                     --config review/review.json --out review/decisions.jsonl [--all]

Each row: {"id", <one key per config field>, "inline_notes": [{"quote", "note"}], "ts"}.
Flag fields default per the config when the reviewer never touched them. Only reviewed items are
exported unless --all is given. Reshape the rows afterwards if a deliverable wants other names.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else default


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=Path, required=True)
    ap.add_argument("--annotations", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--all", action="store_true", help="export every sample, reviewed or not")
    args = ap.parse_args()

    samples = load(args.samples, [])
    ann = load(args.annotations, [])
    ann = ann.get("annotations", []) if isinstance(ann, dict) else ann
    fields = (load(args.config, {}) or {}).get("fields", [])
    items = {a["item_id"]: a for a in ann if a.get("kind") == "item"}
    inline: dict[str, list] = {}
    for a in ann:
        if a.get("kind") == "inline":
            inline.setdefault(a["item_id"], []).append({"quote": a.get("quote", ""), "note": (a.get("note") or "").strip()})

    rows, skipped = [], 0
    for s in samples:
        rec = items.get(s["id"], {})
        vals = dict(rec.get("fields") or {})
        touched = any(v not in (None, "", []) for v in vals.values()) or bool(inline.get(s["id"]))
        if not touched and not args.all:
            skipped += 1
            continue
        row = {"id": s["id"]}
        for f in fields:
            v = vals.get(f["key"])
            if f.get("type") == "flag" and v is None:
                v = f.get("default", True)
            if isinstance(v, str):
                v = v.strip() or None
            row[f["key"]] = v
        for k, v in vals.items():  # fields not in the config still come through
            row.setdefault(k, v)
        row["inline_notes"] = inline.get(s["id"], [])
        row["ts"] = rec.get("ts")
        rows.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {args.out} ({skipped} unreviewed skipped)")
    for f in fields:
        if f.get("type") in ("flag", "yesno", "passfail", "select", "verdict"):
            print(f"  {f['key']}: {dict(Counter(str(r.get(f['key'])) for r in rows))}")


if __name__ == "__main__":
    main()
