#!/usr/bin/env python3
"""Append-only annotation mechanism for the founder queue (kernel/ledger/founder_queue.jsonl).

History is NEVER rewritten: `annotate()` only ever opens the queue file in append mode, and every
existing line stays byte-identical. An annotation is a distinct JSON-line record
({"type": "annotation", ...}) that references an existing queue entry via field-equality `match` —
it never edits that entry in place. `read_queue()` joins annotations back onto their entries at
read time so callers can filter (e.g. drop fixture noise) without the ledger itself losing history.
"""
import argparse
import json
import sys
from datetime import datetime, timezone


def _read_records(queue_path):
    """Yield parsed JSON-object lines from queue_path. Missing file -> no lines. Malformed lines
    (bad JSON, or JSON that isn't an object) are skipped, never fatal."""
    try:
        f = open(queue_path)
    except FileNotFoundError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                yield rec


def _matches(entry, match):
    return all(entry.get(k) == v for k, v in match.items())


def annotate(queue_path, match, reason, kind="fixture"):
    """Append ONE annotation record to queue_path: {"type": "annotation", "kind", "reason", "match",
    "ts"}. Raises ValueError if `match` matches ZERO existing non-annotation entries — an annotation
    must reference something real. Only ever opens the file in append mode."""
    found = any(rec.get("type") != "annotation" and _matches(rec, match)
                for rec in _read_records(queue_path))
    if not found:
        raise ValueError(f"no queue entry in {queue_path} matches {match!r}")
    record = {
        "type": "annotation",
        "kind": kind,
        "reason": reason,
        "match": dict(match),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(queue_path, "a") as f:
        f.write(json.dumps(record) + "\n")


def read_queue(queue_path, include_annotated=True):
    """Parse queue_path into a list of non-annotation entries, each carrying an `_annotations` list of
    the annotation records whose `match` fields all equal that entry's fields. `include_annotated=False`
    filters OUT entries carrying any kind="fixture" annotation. Annotation records themselves never
    appear in the returned list. Malformed lines are skipped, never fatal."""
    entries, annotations = [], []
    for rec in _read_records(queue_path):
        if rec.get("type") == "annotation":
            annotations.append(rec)
        else:
            entries.append(dict(rec))
    for entry in entries:
        entry["_annotations"] = [a for a in annotations
                                 if isinstance(a.get("match"), dict) and _matches(entry, a["match"])]
    if not include_annotated:
        entries = [e for e in entries if not any(a.get("kind") == "fixture" for a in e["_annotations"])]
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser(description="Append-only annotation for the founder queue.")
    ap.add_argument("--queue", required=True, help="path to founder_queue.jsonl")
    ap.add_argument("--task-id", help="match entries by task_id")
    ap.add_argument("--queued-at", help="match entries by queued_at")
    ap.add_argument("--reason", help="annotation reason (required unless --list)")
    ap.add_argument("--kind", default="fixture", help="annotation kind (default: fixture)")
    ap.add_argument("--list", action="store_true", help="list every entry with its annotation status")
    a = ap.parse_args(argv)

    if a.list:
        for entry in read_queue(a.queue):
            fixture = any(x.get("kind") == "fixture" for x in entry["_annotations"])
            status = ("annotated (fixture)" if fixture else "annotated") if entry["_annotations"] else "unannotated"
            print(f"{entry.get('task_id')}\t{entry.get('queued_at')}\t{status}")
        return 0

    match = {}
    if a.task_id is not None:
        match["task_id"] = a.task_id
    if a.queued_at is not None:
        match["queued_at"] = a.queued_at
    if not match:
        print("founder_queue_annotate: need --task-id and/or --queued-at to match an entry", file=sys.stderr)
        return 1
    if not a.reason:
        print("founder_queue_annotate: --reason is required", file=sys.stderr)
        return 1
    try:
        annotate(a.queue, match, a.reason, kind=a.kind)
    except ValueError as e:
        print(f"founder_queue_annotate: {e}", file=sys.stderr)
        return 1
    print(f"annotated: {match}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
