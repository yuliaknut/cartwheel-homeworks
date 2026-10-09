"""Add one review batch to analysis/state/samples.json and record why in sample_manifest.json.

Homework 4, Part B fixes four batches; each call adds one batch and never
re-picks a conversation that is already in the sample. Strategies:

  random      uniform picks (batch 1 first half, batch 4)
  cluster     k-means on the instructor's trace features, closest members
              to each centroid, round-robin across clusters (batch 1 second half)
  dimension   stratified across the values of one index field chosen before
              looking at outcomes, e.g. --dimension role (batch 2)
  ids         explicit trace ids with a reason each, for depth searches and
              close negatives (batch 3): --ids TRACE_ID=reason ...

    uv run python -m analysis.review_app.select_batch --batch b1-uniform --strategy random --k 15
    uv run python -m analysis.review_app.select_batch --batch b1-cluster --strategy cluster --k 15
    uv run python -m analysis.review_app.select_batch --batch b2-role --strategy dimension --dimension role --k 30
    uv run python -m analysis.review_app.select_batch --batch b3-depth --strategy ids --ids 9f69ba…=filter:uncited_deadline
    uv run python -m analysis.review_app.select_batch --batch b4-uniform --strategy random --k 15
    uv run python -m analysis.review_app.select_batch --batch b6-escalation-boundary --strategy ids --label-focus unnecessary_escalation --ids ...
    uv run python -m analysis.review_app.select_batch ... --dry-run     # print the picks, write nothing

The clustering reuses ``analysis.helpers.selection`` (standardize + k-means
over turn count, tool calls, distinct tools, retrieval, tokens) so the
representatives are the same kind the instructor's ``select_traces`` would
return; the manifest keeps ``source`` so ``next_to_label`` can find the store.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from analysis.helpers import selection

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "analysis" / "state"


def _repo_relative(path: Path) -> str:
    """Store paths inside the repo relative to its root, so the manifest holds no home directory."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)  # a store outside the repo keeps its full path


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, data: Any, indent: int | None = 1) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def pick_random(pool: list[dict[str, Any]], k: int, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    chosen = rng.sample(pool, min(k, len(pool)))
    return [{"trace_id": t["trace_id"], "reason": "uniform random pick"} for t in chosen]


def pick_cluster(store: list[dict[str, Any]], pool_ids: set[str], k: int, seed: int, n_clusters: int) -> list[dict[str, str]]:
    """Cluster the whole store, then take unsampled members closest to each centroid."""
    vectors = selection._standardize([selection._feature_vector(t) for t in store])
    assign = selection._kmeans(vectors, k=n_clusters, seed=seed)
    members: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(assign):
        members[c].append(i)
    centroids = {
        c: [sum(vectors[i][d] for i in idx) / len(idx) for d in range(len(vectors[0]))]
        for c, idx in members.items()
    }
    ranked: dict[int, list[int]] = {}
    for c, idx in members.items():
        cen = centroids[c]
        ranked[c] = sorted(
            (i for i in idx if store[i]["trace_id"] in pool_ids),
            key=lambda i: sum((a - b) ** 2 for a, b in zip(vectors[i], cen)),
        )
    picks: list[dict[str, str]] = []
    clusters = sorted(ranked, key=lambda c: -len(members[c]))
    while len(picks) < k and any(ranked[c] for c in clusters):
        for c in clusters:
            if len(picks) >= k or not ranked[c]:
                continue
            i = ranked[c].pop(0)
            picks.append({
                "trace_id": store[i]["trace_id"],
                "reason": f"cluster {c} representative ({len(members[c])} conversations; features {_feature_note(store[i])})",
            })
    return picks


def _feature_note(t: dict[str, Any]) -> str:
    f = t.get("features") or {}
    return f"turns={f.get('turn_count')}, tools={f.get('tool_call_count')}, distinct={f.get('distinct_tools')}, retrieval={f.get('has_retrieval')}, tokens={f.get('tokens')}"


def pick_dimension(pool: list[dict[str, Any]], index: dict[str, dict[str, Any]], field: str, k: int, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in pool:
        by_value[str(index[t["trace_id"]].get(field))].append(t)
    values = sorted(by_value)
    if not values:
        return []
    quota = {v: k // len(values) for v in values}
    for v in values[: k - sum(quota.values())]:
        quota[v] += 1
    # A thin stratum cannot fill its quota, and later batches hit this more often
    # as the pool drains. Give the shortfall to the strata that still have room,
    # deepest pool first, so the batch lands on k instead of silently short.
    for v in values:
        quota[v] = min(quota[v], len(by_value[v]))
    short = k - sum(quota.values())
    while short > 0:
        room = [v for v in values if len(by_value[v]) > quota[v]]
        if not room:
            break
        for v in sorted(room, key=lambda v: quota[v] - len(by_value[v])):
            if short == 0:
                break
            quota[v] += 1
            short -= 1
    picks: list[dict[str, str]] = []
    for v in values:
        chosen = rng.sample(by_value[v], quota[v])
        picks.extend({"trace_id": t["trace_id"], "reason": f"{field}={v} stratum ({quota[v]} of {len(by_value[v])} unsampled)"} for t in chosen)
    return picks


def pick_slice(pool: list[dict[str, Any]], index: dict[str, dict[str, Any]], field: str, value: str) -> list[dict[str, str]]:
    """Every unsampled trace where ``field == value``.

    The lecture's dimension method: filter to one slice of the specification
    and read all of it, rather than spreading picks across a dimension's
    values. Finds failures concentrated in one part of the spec; covers only
    that part.
    """
    hits = [t for t in pool if str(index[t["trace_id"]].get(field)) == value]
    return [{"trace_id": t["trace_id"], "reason": f"{field}={value} slice (all {len(hits)} unsampled in the slice)"} for t in hits]


def pick_neighbors(store: list[dict[str, Any]], pool_ids: set[str], seeds: list[str], k: int, sample_ids: set[str], mode: str, seed: int) -> list[dict[str, str]]:
    """The lecture's depth search: nearest neighbours of a confirmed failure.

    Delegates to ``analysis.helpers.selection.next_candidates`` with the
    ``neighbors`` signal, a bag-of-words cosine over the trace text. Finds more
    instances of a failure you have already confirmed; by construction it cannot
    find a failure you have not seen yet.
    """
    cands = selection.next_candidates(
        store, mode=mode, k=k, strategy="neighbors",
        confirmed_failures=seeds, already_labeled=sample_ids, seed=seed,
    )
    out: list[dict[str, str]] = []
    for c in cands:
        tid = c["trace_id"]
        if tid in pool_ids:
            out.append({"trace_id": tid, "reason": f"neighbour of {mode} seed ({c.get('signal', 'neighbors')})"})
    return out


def remove_batch(state: Path, name: str) -> None:
    """Retract a batch: drop its samples, keep the record in the manifest."""
    samples = _read(state / "samples.json", [])
    manifest = _read(state / "sample_manifest.json", {})
    batch = next((b for b in manifest.get("batches", []) if b.get("batch") == name), None)
    if batch is None:
        raise SystemExit(f"no batch named {name!r} in the manifest")
    kept = [s for s in samples if s.get("batch") != name]
    dropped = len(samples) - len(kept)
    batch["retracted_at"] = _utcnow()
    manifest["batches"] = [b for b in manifest["batches"] if b.get("batch") != name]
    manifest.setdefault("retracted_batches", []).append(batch)
    manifest["total_sampled"] = len(kept)
    _write(state / "samples.json", kept, indent=None)
    _write(state / "sample_manifest.json", manifest)
    print(f"retracted {name}: dropped {dropped} conversations; samples.json now holds {len(kept)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--remove", metavar="BATCH", help="retract a batch: drop its samples, keep the manifest record")
    parser.add_argument("--batch", help="batch name recorded on every sample, e.g. b1-uniform")
    parser.add_argument("--strategy", choices=["random", "cluster", "dimension", "slice", "neighbors", "ids"])
    parser.add_argument("--k", type=int, default=15)
    parser.add_argument("--seed-trace", nargs="*", default=[], help="confirmed-failure scenario or trace ids to search from (--strategy neighbors)")
    parser.add_argument("--mode", help="failure mode the neighbour search is hunting, recorded in the manifest")
    parser.add_argument("--label-focus", help="final mode the review page's labels card shows alone for this batch's traces, e.g. unnecessary_escalation")
    parser.add_argument("--value", help="stratum value for --strategy slice, e.g. store_override")
    parser.add_argument("--dimension", help="index field for --strategy dimension (role, intent, group, dq, difficulty, record_state, applicable_policy, tools_needed, user_style)")
    parser.add_argument("--ids", nargs="*", default=[], help="TRACE_ID=reason entries for --strategy ids (scenario ids also accepted)")
    parser.add_argument("--clusters", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--state", type=Path, default=STATE_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.remove:
        remove_batch(args.state, args.remove)
        return
    if not args.batch or not args.strategy:
        raise SystemExit("--batch and --strategy are required unless --remove is given")

    store_path = args.state / "traces.json"
    store: list[dict[str, Any]] = _read(store_path, [])
    if not store:
        raise SystemExit(f"no trace store at {store_path}; run analysis.review_app.load_traces first")
    index = {r["trace_id"]: r for r in _read(args.state / "trace_index.json", [])}
    samples: list[dict[str, Any]] = _read(args.state / "samples.json", [])
    manifest: dict[str, Any] = _read(args.state / "sample_manifest.json", {})
    if any(b.get("batch") == args.batch for b in manifest.get("batches", [])):
        raise SystemExit(f"batch {args.batch!r} already exists in the manifest; pick a new name")

    sampled = {s["trace_id"] for s in samples}
    pool = [t for t in store if t["trace_id"] not in sampled]
    by_id = {t["trace_id"]: t for t in store}
    by_sid = {t["meta"].get("scenario_id"): t for t in store}

    if args.strategy == "random":
        picks = pick_random(pool, args.k, args.seed)
    elif args.strategy == "cluster":
        picks = pick_cluster(store, {t["trace_id"] for t in pool}, args.k, args.seed, args.clusters)
    elif args.strategy == "neighbors":
        if not args.seed_trace or not args.mode:
            raise SystemExit("--seed-trace and --mode are required for --strategy neighbors")
        seeds = []
        for key in args.seed_trace:
            s = by_id.get(key) or by_sid.get(key)
            if s is None:
                raise SystemExit(f"unknown seed trace: {key}")
            seeds.append(s["id"])
        picks = pick_neighbors(store, {t["trace_id"] for t in pool}, seeds, args.k, sampled, args.mode, args.seed)
    elif args.strategy == "slice":
        if not args.dimension or not args.value:
            raise SystemExit("--dimension and --value are required for --strategy slice")
        picks = pick_slice(pool, index, args.dimension, args.value)
    elif args.strategy == "dimension":
        if not args.dimension:
            raise SystemExit("--dimension is required for --strategy dimension")
        picks = pick_dimension(pool, index, args.dimension, args.k, args.seed)
    else:
        picks = []
        for entry in args.ids:
            key, _, reason = entry.partition("=")
            t = by_id.get(key) or by_sid.get(key)
            if t is None:
                raise SystemExit(f"unknown trace or scenario id: {key}")
            if t["trace_id"] in sampled:
                print(f"skip {key}: already sampled")
                continue
            picks.append({"trace_id": t["trace_id"], "reason": reason or "depth search"})

    for p in picks:
        p["scenario_id"] = by_id[p["trace_id"]]["meta"].get("scenario_id")
    print(f"batch {args.batch}: {len(picks)} picks ({args.strategy}), {len(pool)} unsampled before, {len(samples)} sampled before")
    for p in picks:
        r = index.get(p["trace_id"], {})
        print(f"  {p['scenario_id']:13} {str(r.get('role')):8} {str(r.get('intent')):24} {p['reason']}")
    if args.dry_run:
        return

    for p in picks:
        record = dict(by_id[p["trace_id"]])
        record["batch"] = args.batch
        record["reason"] = p["reason"]
        record["flags"] = []
        samples.append(record)
    batch = {
        "batch": args.batch,
        "strategy": args.strategy,
        "k": args.k,
        "dimension": args.dimension,
        # k-means labels only mean something against a fixed (store, clusters, seed);
        # without this the "cluster 6 representative" reasons are unreproducible.
        "clusters": args.clusters if args.strategy == "cluster" else None,
        "value": args.value,
        "mode": args.mode,
        "label_focus": args.label_focus,
        "seed_trace": list(args.seed_trace),
        "seed": args.seed,
        "selected_at": _utcnow(),
        "picks": picks,
    }
    manifest.setdefault("batches", []).append(batch)
    manifest.update({
        "source": _repo_relative(store_path),
        "k": args.k,
        "strategy": args.strategy,
        "selected_at": batch["selected_at"],
        "picks": picks,
        "total_sampled": len(samples),
    })
    _write(args.state / "samples.json", samples, indent=None)
    _write(args.state / "sample_manifest.json", manifest)
    print(f"samples.json now holds {len(samples)} conversations; manifest has {len(manifest['batches'])} batch(es)")


if __name__ == "__main__":
    main()
