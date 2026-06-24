#!/usr/bin/env python3
"""SEIF Episodic Export — turn the loop's append-only episode JSONL into a FLAT training table.

The loop (logos/seif_loop.py) records one typed trajectory summary per task into episodic memory
(memory/store/episodes.jsonl). Each record is `{"ts": ..., "summary": {...}}`, where the summary's
`cost` dict carries the per-task TRAINING SIGNAL the loop measured: which model was requested vs
actually served, how many model calls it took, fresh vs cache-read input tokens, USD cost, the
evidence verdict, the final outcome, and the receipt hash that proves it.

This module reads that JSONL and emits BOTH a CSV and a JSONL training table with a STABLE, documented
column schema (see COLUMNS). Nested fields are pulled to top-level scalar columns so the table loads
straight into pandas / a spreadsheet / a fine-tune pipeline with no further unpacking. Missing fields
degrade to a typed empty value (never crash) so a partially-instrumented or torn episode still exports.

Dependency-free (stdlib csv/json only). Pure read side: it never mutates the episode log.

CLI:
  python3 logos/episodic_export.py --in memory/store/episodes.jsonl --out-prefix /tmp/seif_train
    -> writes /tmp/seif_train.csv and /tmp/seif_train.jsonl, prints a one-line summary.
"""
import csv
import json
import os

# Stable, documented training-table schema. ORDER IS THE CONTRACT — append new columns at the END only;
# never reorder/rename/remove (downstream readers and prior exports depend on the position + names).
COLUMNS = (
    "ts",                # ISO-8601 UTC timestamp the episode was recorded (record envelope)
    "task_id",           # backlog task identifier (the unit of work)
    "attempt_id",        # "<task_id>#<idx>" — unique per loop attempt
    "model_requested",   # model the loop ASKED for (None/"" if it let the default stand)
    "model_actual",      # model actually SERVED (CBOM: a silent downgrade shows up here)
    "attempt_number",    # number of model calls spent on the task (usage.calls)
    "fresh_in_tokens",   # fresh (non-cached) input tokens — the real input work
    "cache_read_tokens", # cache-read input tokens — near-free; kept SEPARATE from fresh on purpose
    "cost_usd",          # measured USD cost for the task (summed across attempts)
    "evidence_result",   # "pass" | "fail" — did the project's own tests + integrity gate pass?
    "final_outcome",     # trajectory termination_reason (accepted/rejected/stuck/error/...)
    "receipt_hash",      # SEIF receipt hash — the proof handle for this attempt
    "reusable",          # bool: passed the trajectory_summary reuse filter (accepted + lesson + clean)
)


def _cost(summary):
    c = summary.get("cost")
    return c if isinstance(c, dict) else {}


def _as_int(v):
    """Coerce to int, or 0 — a historical episode whose cost field holds a non-numeric/None value must
    still export (degrade to 0), never raise out of flatten()."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _is_reusable(summary):
    """Cheap inline reuse filter (mirrors trajectory_summary.is_reusable) so export has no import-order
    dependency on logos/ being importable. Reusable = accepted/gate_complete + a lesson + no prohibition."""
    return bool(
        summary.get("termination_reason") in ("accepted", "gate_complete")
        and summary.get("reusable_lesson_candidate")
        and not summary.get("prohibited_reuse_reasons")
    )


def flatten(record):
    """Flatten one episode record `{"ts", "summary"}` into a flat dict keyed by COLUMNS.

    Defensive: a non-dict record/summary, or any missing field, yields typed empties rather than
    raising — a single torn or partial episode never sinks the whole export."""
    if not isinstance(record, dict):
        record = {}
    summary = record.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    cost = _cost(summary)
    return {
        "ts": record.get("ts") or "",
        "task_id": summary.get("task_id") or "",
        "attempt_id": summary.get("attempt_id") or "",
        "model_requested": cost.get("model_requested") or "",
        "model_actual": cost.get("model_actual") or "",
        "attempt_number": _as_int(cost.get("attempt_number")),
        "fresh_in_tokens": _as_int(cost.get("fresh_in")),
        "cache_read_tokens": _as_int(cost.get("cache_read")),
        "cost_usd": _as_float(cost.get("cost_usd")),
        "evidence_result": cost.get("evidence_result") or "",
        "final_outcome": summary.get("termination_reason") or "",
        "receipt_hash": cost.get("receipt_hash") or "",
        "reusable": _is_reusable(summary),
    }


def read_episodes(in_path):
    """Yield episode records from a JSONL file. Missing file → nothing; a torn/non-JSON line is skipped
    (never crashes an export, mirroring EpisodicMemory._iter's tolerance of a torn final line)."""
    if not os.path.exists(in_path):
        return
    with open(in_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def build_rows(in_path):
    """Read the episode log and return the flat training rows (oldest first, the JSONL's natural order)."""
    return [flatten(rec) for rec in read_episodes(in_path)]


def write_csv(rows, out_path):
    """Write rows to CSV with COLUMNS as the header (stable order). Always writes the header, even for
    zero rows, so the schema is self-describing on disk."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(COLUMNS), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return out_path


def write_jsonl(rows, out_path):
    """Write rows to JSONL — one flat JSON object per row, keys in COLUMNS order."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps({k: r.get(k) for k in COLUMNS}) + "\n")
    return out_path


def export(in_path, out_prefix):
    """Read `in_path` (episode JSONL) and write `<out_prefix>.csv` + `<out_prefix>.jsonl`.
    Returns {"rows", "csv", "jsonl"}."""
    rows = build_rows(in_path)
    csv_path = write_csv(rows, out_prefix + ".csv")
    jsonl_path = write_jsonl(rows, out_prefix + ".jsonl")
    return {"rows": len(rows), "csv": csv_path, "jsonl": jsonl_path}


def main():
    import argparse
    here = os.path.dirname(os.path.abspath(__file__))
    default_in = os.path.join(os.path.dirname(here), "memory", "store", "episodes.jsonl")
    ap = argparse.ArgumentParser(description="Export SEIF episodic memory to a flat training table (CSV+JSONL).")
    ap.add_argument("--in", dest="in_path", default=default_in, help="episode JSONL (default memory/store/episodes.jsonl)")
    ap.add_argument("--out-prefix", required=True, help="output path prefix (writes <prefix>.csv and <prefix>.jsonl)")
    a = ap.parse_args()
    out = export(a.in_path, a.out_prefix)
    print(f"[episodic-export] {out['rows']} row(s) -> {out['csv']} + {out['jsonl']}")
    print(f"[episodic-export] columns: {', '.join(COLUMNS)}")


def _selftest():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="seif-export-")
    try:
        ep = os.path.join(tmp, "episodes.jsonl")
        with open(ep, "w") as f:
            # a fully-instrumented accepted episode with a reusable lesson
            f.write(json.dumps({"ts": "2026-06-24T00:00:00Z", "summary": {
                "attempt_id": "t1#0", "task_id": "t1", "hypothesis": "h",
                "termination_reason": "accepted", "reusable_lesson_candidate": "resolve paths first",
                "prohibited_reuse_reasons": [],
                "cost": {"model_requested": "claude-opus-4-8", "model_actual": "claude-opus-4-8",
                         "attempt_number": 2, "fresh_in": 1500, "cache_read": 9000,
                         "cost_usd": 0.0123, "evidence_result": "pass", "receipt_hash": "abc123"}}}) + "\n")
            # a rejected episode (evidence fail), no lesson
            f.write(json.dumps({"ts": "2026-06-24T00:01:00Z", "summary": {
                "attempt_id": "t2#0", "task_id": "t2", "hypothesis": "h2",
                "termination_reason": "rejected", "prohibited_reuse_reasons": ["overfit"],
                "cost": {"model_requested": None, "model_actual": "claude-sonnet",
                         "attempt_number": 1, "fresh_in": 800, "cache_read": 0,
                         "cost_usd": 0.004, "evidence_result": "fail", "receipt_hash": "def456"}}}) + "\n")
            f.write('{"ts":"x","summary":{"torn"\n')                 # torn line — must be skipped
        out = export(ep, os.path.join(tmp, "train"))
        assert out["rows"] == 2, out                                 # torn line skipped, 2 good rows
        rows = build_rows(ep)
        r0 = rows[0]
        assert r0["task_id"] == "t1" and r0["model_actual"] == "claude-opus-4-8"
        assert r0["fresh_in_tokens"] == 1500 and r0["cache_read_tokens"] == 9000
        assert r0["attempt_number"] == 2 and abs(r0["cost_usd"] - 0.0123) < 1e-9
        assert r0["evidence_result"] == "pass" and r0["final_outcome"] == "accepted"
        assert r0["receipt_hash"] == "abc123" and r0["reusable"] is True
        # rejected row: not reusable, model_requested falls back to "" when None
        r1 = rows[1]
        assert r1["reusable"] is False and r1["model_requested"] == "" and r1["final_outcome"] == "rejected"
        # CSV round-trips with the documented header (stable order)
        with open(out["csv"]) as f:
            reader = csv.reader(f)
            header = next(reader)
            body = list(reader)
        assert tuple(header) == COLUMNS, header
        assert len(body) == 2
        # JSONL round-trips with COLUMNS keys
        with open(out["jsonl"]) as f:
            j = [json.loads(line) for line in f if line.strip()]
        assert len(j) == 2 and list(j[0].keys()) == list(COLUMNS)
        assert j[0]["fresh_in_tokens"] == 1500
        # empty input → header-only CSV, empty JSONL, never a crash
        empty_out = export(os.path.join(tmp, "absent.jsonl"), os.path.join(tmp, "empty"))
        assert empty_out["rows"] == 0
        with open(empty_out["csv"]) as f:
            assert next(csv.reader(f)) == list(COLUMNS), "header still written for empty export"
        # a non-dict / empty record flattens to typed empties, doesn't raise
        blank = flatten("nope")
        assert blank["task_id"] == "" and blank["fresh_in_tokens"] == 0 and blank["reusable"] is False
        print("episodic_export selftest PASS — flatten, CSV+JSONL stable schema, torn/empty tolerated")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
