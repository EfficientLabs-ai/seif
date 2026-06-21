#!/usr/bin/env python3
"""Curate a stratified 20-instance eval set from SWE-bench-Verified (light repos for tractable
image pulls + fast tests). Stratify by gold-patch touched-file count — used ONLY for the
degradation-curve buckets, never shown to the agent. Writes logos/eval_set_20.json."""
import json
import re
from collections import defaultdict
from datasets import load_dataset

LIGHT = {"psf/requests", "pytest-dev/pytest", "pylint-dev/pylint"}
OUT = "/home/neo/seif/logos/eval_set_20.json"


def files_touched(patch):
    return len(set(re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)))


def bucket(n):
    return "single" if n <= 1 else ("multi" if n <= 3 else "large")


def main():
    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    by = defaultdict(list)
    for x in ds:
        if x["repo"] in LIGHT:
            by[bucket(files_touched(x["patch"]))].append(x["instance_id"])
    # Fill scarce buckets fully (multi/large are rare in light repos), then top up to 20 with single.
    TARGET = 20
    pick = by["large"][:] + by["multi"][:]
    pick += by["single"][: max(0, TARGET - len(pick))]
    pick = pick[:TARGET]
    json.dump({"instances": pick,
               "strata": {b: by[b][:12] for b in by},
               "counts": {b: len(by[b]) for b in by}},
              open(OUT, "w"), indent=2)
    print(f"curated {len(pick)} instances -> {OUT}")
    print("by bucket:", {b: sum(1 for i in pick if i in by[b]) for b in by})
    print(pick)


if __name__ == "__main__":
    main()
