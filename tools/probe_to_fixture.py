#!/usr/bin/env python3
"""Turn a decoded `rail` probe CSV into a replay fixture for smm2-decomp.

    python3 probe.py decode probe.log -o rail.csv
    python3 probe_to_fixture.py rail.csv > rail_mover_track_note_<date>.csv

Keeps one row per frame in state 1 (cState_TargetPointMove) and writes the
columns tests/bridge/test_rail_mover_replay.py replays: the mover's state
counter, position, velocity and target. Rows whose fields were unreadable
(`-` in the log, empty after decode) are dropped, which splits the trace into
contiguous segments the test replays independently.
"""
from __future__ import annotations

import csv
import sys

COLUMNS = ["counter", "mv_x", "mv_y", "vel_x", "vel_y", "tgt_x", "tgt_y"]
SOURCE = {"counter": "counter", "mv_x": "mv_x", "mv_y": "mv_y", "vel_x": "vel_x",
          "vel_y": "vel_y", "tgt_x": "tgt_x", "tgt_y": "tgt_y"}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(COLUMNS)
    kept = dropped = 0
    with open(argv[0], newline="") as f:
        for row in csv.DictReader(f):
            if row.get("hook") != "rail" or row.get("state") != "1":
                dropped += 1
                continue
            vals = [row.get(SOURCE[c], "") for c in COLUMNS]
            if any(v == "" for v in vals):
                dropped += 1
                continue
            w.writerow([int(float(vals[0]))] + [float(v) for v in vals[1:]])
            kept += 1
    print(f"kept {kept} rows, dropped {dropped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
