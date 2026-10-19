#!/usr/bin/env python3
"""Fetch an uploaded course from the TheGreatRambler/mm2_level dataset.

The dataset (26.6M courses uploaded until 2022) is served row by row by
huggingface's datasets-server, sorted by data_id, so one course is a binary
search away and the 150 GB dump is not needed. `level_data` is the zlib of the
decrypted course body: the sim's public/courses/hf/<id>.zlib layout, which
level_install and game_boot(file=...) take as is.

    python3 tools/hf_course.py 3002534 -o /tmp/courses     # -> 3002534.zlib
    python3 tools/hf_course.py --offset 2534 -o /tmp/courses
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

SERVER = "https://datasets-server.huggingface.co"
DATASET = "dataset=TheGreatRambler/mm2_level"
ROWS = f"{SERVER}/rows?{DATASET}&config=default&split=train"


def row(offset: int, tries: int = 8) -> dict:
    """The dataset row at `offset`, retried: the server answers 429 to a burst
    of requests and 5xx under load."""
    url = f"{ROWS}&offset={offset}&length=1"
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                rows = json.load(r)["rows"]
            if not rows:
                raise IndexError(f"no row at offset {offset}")
            return rows[0]["row"]
        except (OSError, ValueError, KeyError) as e:
            if attempt == tries - 1:
                raise
            after = getattr(e, "headers", None) and e.headers.get("Retry-After")
            wait = int(after) if after and after.isdigit() else 5 * 2 ** attempt
            print(f"offset {offset}: {e}; retrying in {wait} s", file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("unreachable")


def find(data_id: int) -> dict:
    """The row with `data_id`: a binary search over the sorted offsets."""
    with urllib.request.urlopen(f"{SERVER}/size?{DATASET}", timeout=60) as r:
        rows = json.load(r)["size"]["dataset"]["num_rows"]
    lo, hi = 0, rows - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            r = row(mid)
        except IndexError:
            hi = mid - 1
            continue
        if r["data_id"] == data_id:
            return r
        if r["data_id"] < data_id:
            lo = mid + 1
        else:
            hi = mid - 1
    raise LookupError(f"data_id {data_id} is not in the dataset")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_id", nargs="?", type=int, help="the course's data_id")
    ap.add_argument("--offset", type=int, help="take the row at this offset instead")
    ap.add_argument("-o", "--out", type=Path, default=Path("."), help="directory for <data_id>.zlib")
    args = ap.parse_args()
    if (args.data_id is None) == (args.offset is None):
        ap.error("give a data_id or --offset")
    try:
        r = row(args.offset) if args.offset is not None else find(args.data_id)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{r['data_id']}.zlib"
    path.write_bytes(base64.b64decode(r["level_data"]))
    print(json.dumps({"file": str(path), "data_id": r["data_id"], "name": r["name"],
                      "gamestyle": r["gamestyle"], "theme": r["theme"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
