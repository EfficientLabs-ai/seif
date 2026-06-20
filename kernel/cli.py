#!/usr/bin/env python3
"""seif — thin CLI so any agent can emit work THROUGH the kernel (events/receipts/ledger).

Usage:
  python3 kernel/cli.py task --id T --objective "..." [--protected] [--by claude]
  python3 kernel/cli.py to   --id T --state PROPOSED [--by codex]
  python3 kernel/cli.py log  [-n 20]
  python3 kernel/cli.py verify
Security note: `to` takes only --id; the kernel derives current state + protected
status from the LEDGER (callers cannot lie about them — see THREAT_MODEL.md).
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import seif_kernel as K


def main():
    p = argparse.ArgumentParser(prog="seif")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    pl = sub.add_parser("log"); pl.add_argument("-n", type=int, default=20)
    pt = sub.add_parser("task")
    pt.add_argument("--id", required=True); pt.add_argument("--objective", required=True)
    pt.add_argument("--workspace", default="seif"); pt.add_argument("--by", default="claude")
    pt.add_argument("--protected", action="store_true")
    po = sub.add_parser("to")
    po.add_argument("--id", required=True); po.add_argument("--state", required=True)
    po.add_argument("--by", default="claude")
    a = p.parse_args()

    if a.cmd == "verify":
        K.verify_chain(); print("chain OK ✅")
    elif a.cmd == "log":
        for e in K._read(K.EVENTS)[-a.n:]:
            print(f"{e['seq']:>3} {e['ts']} {e['actor']:<8} {e['type']:<20} {e.get('task_id') or ''}")
    elif a.cmd == "task":
        K.submit_task({"id": a.id, "schema_version": "0.1", "workspace": a.workspace,
                       "objective": a.objective, "writable_scope": [], "acceptance": ["done"],
                       "output_contract": "report", "budget": {"tokens": None, "seconds": None, "usd": None},
                       "state": "DRAFT", "protected": a.protected, "created_by": a.by, "created_at": K._now()})
        print(f"task {a.id} submitted (DRAFT)")
    elif a.cmd == "to":
        K.transition_task({"id": a.id}, a.state, a.by)
        print(f"{a.id} -> {a.state}")


if __name__ == "__main__":
    main()
