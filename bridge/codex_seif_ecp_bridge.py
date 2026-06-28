#!/usr/bin/env python3
"""Dry-run Codex-SEIF-ECP continuity bridge.

Builds a sanitized Codex task packet from repo metadata, safe docs, test commands,
ECP packet references, and a SEIF continuity snapshot. It never reads env/vault
paths and records every include/exclude decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

DENY_PARTS = {".env", "vault", ".ssh", ".gnupg", "secrets", "private", "keys"}
DENY_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
MAX_DOC_BYTES = 128 * 1024


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(obj: Any) -> str:
    return hashlib.sha256(_canon(obj)).hexdigest()


def _path_parts(path: Path) -> set[str]:
    return {p.lower() for p in path.parts}


def classify_doc(repo: Path, candidate: str) -> tuple[bool, str, Path | None]:
    raw = Path(candidate)
    if raw.is_absolute():
        return False, "absolute paths are not allowed", None
    if any(part == ".." for part in raw.parts):
        return False, "path traversal is not allowed", None
    if _path_parts(raw) & DENY_PARTS:
        return False, "path matches denied secret/vault/key segment", None
    if raw.suffix.lower() in DENY_SUFFIXES:
        return False, "path suffix is denied", None

    candidate_path = repo / raw
    if candidate_path.is_symlink():
        return False, "symlink docs are denied", None

    resolved_repo = repo.resolve(strict=True)
    resolved = candidate_path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_repo)
    except ValueError:
        return False, "resolved path escapes repo", None
    if resolved.is_symlink():
        return False, "symlink docs are denied", None
    if not resolved.exists() or not resolved.is_file():
        return False, "doc is missing or not a file", None
    if resolved.stat().st_size > MAX_DOC_BYTES:
        return False, "doc exceeds size limit", None
    if _path_parts(resolved.relative_to(resolved_repo)) & DENY_PARTS:
        return False, "resolved path matches denied segment", None
    return True, "included", resolved


def build_packet(request: dict[str, Any]) -> dict[str, Any]:
    repo = Path(request["repo"]).expanduser()
    repo_resolved = repo.resolve(strict=True)
    included = []
    excluded = []

    for doc in request.get("docs", []):
        ok, reason, path = classify_doc(repo_resolved, str(doc))
        if not ok:
            excluded.append({"path": str(doc), "reason": reason})
            continue
        rel = str(path.relative_to(repo_resolved))
        content = path.read_text(encoding="utf-8", errors="replace")
        included.append({"path": rel, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "content": content})

    packet = {
        "schema": "codex.seif.ecp.task.v1",
        "mode": "dry-run",
        "repo": str(repo_resolved),
        "issue_id": request.get("issue_id"),
        "branch": request.get("branch"),
        "scope": request.get("scope", []),
        "safety": {
            "deny_env": True,
            "deny_vault": True,
            "deny_private_keys": True,
            "deny_absolute_doc_paths": True,
            "deny_path_traversal": True,
            "max_doc_bytes": MAX_DOC_BYTES,
        },
        "test_commands": request.get("test_commands", []),
        "status_matrix": request.get("status_matrix", {}),
        "ecp_packet": request.get("ecp_packet", {}),
        "seif_continuity_snapshot": request.get("seif_continuity_snapshot", {}),
        "included_docs": included,
        "excluded_docs": excluded,
    }
    packet["receipt_hash"] = _sha256(packet)
    return packet


def write_result_packet(task_packet: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    packet = {
        "schema": "codex.seif.ecp.result.v1",
        "task_receipt_hash": task_packet["receipt_hash"],
        "commands": result.get("commands", []),
        "tests": result.get("tests", []),
        "files_touched": result.get("files_touched", []),
        "assumptions": result.get("assumptions", []),
        "evidence": result.get("evidence", []),
    }
    packet["receipt_hash"] = _sha256(packet)
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a dry-run Codex-SEIF-ECP task packet")
    parser.add_argument("--input", required=True, help="JSON request file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)

    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    packet = build_packet(request)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "task-packet.json").write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    (out / "exclusion-log.json").write_text(json.dumps(packet["excluded_docs"], indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
