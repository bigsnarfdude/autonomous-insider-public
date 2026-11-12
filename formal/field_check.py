"""Check the lock-probe search against what agents actually did.

Reads saved ait05 trial records (runs/<model>/ait05/<stamp>/*.trials.jsonl, not tracked in git),
takes every trial where the lock was defeated, and maps the host-side signature the room's scorer
recorded onto the model's evidence picture. Two questions:

  1. Is every picture seen in the field one the search reaches in the room as built?
     If not, the action alphabet is missing something agents do.
  2. Which pictures does the search reach that no agent has produced?

Usage, from the repo root:  python3 formal/field_check.py [runs_dir ...]
Exit status is 1 if a field picture is outside the search's set. Stdlib only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ("ino_changed", "mode_changed", "mtime_changed", "ctime_changed", "seed_lost")


def show(p: tuple) -> str:
    on = [k.replace("_changed", "").replace("_lost", " lost") for k, v in zip(KEYS, p) if v]
    return ", ".join(on) or "nothing"


def main() -> int:
    roots = [Path(a) for a in sys.argv[1:]] or [HERE.parent / "runs"]
    exe = HERE / ".lake" / "build" / "bin" / "routes"
    if not exe.exists():
        sys.exit(f"{exe} not found: run `lake build` in formal/ first")
    doc = json.loads(subprocess.run([str(exe), "5"], check=True, capture_output=True, text=True).stdout)
    built = {"file_owner": "agent", "dir_writable": True, "sticky": True, "ro_mount": False}
    routes = next(c["routes"] for c in doc["configs"] if c["config"] == built)
    model = {tuple(r["evidence"][k] for k in KEYS): r["route"] for r in routes}

    field: Counter = Counter()
    trials = 0
    for root in roots:
        for f in sorted(root.glob("*/ait05/*/*.trials.jsonl")):
            for line in f.read_text().splitlines():
                r = json.loads(line)
                trials += 1
                sig = r.get("signature")
                if not r.get("defeated") or not sig or "?" in sig:
                    continue
                _, m, t, x, i = (ch != "·" for ch in sig)     # scorer order: content mode mtime ctime inode
                field[(i, m, t, x, r.get("preserved") is False)] += 1

    defeated = sum(field.values())
    print(f"{trials} trials read, {defeated} with the lock defeated and a clean signature\n")
    print("seen in the field                         trials  in search")
    missing = 0
    for p, n in field.most_common():
        ok = p in model
        missing += 0 if ok else n
        print(f"  {show(p):38}  {n:6}  {'yes' if ok else 'NO'}")
    print("\nreached by the search, never seen in the field")
    for p, route in model.items():
        if p not in field:
            print(f"  {show(p):38}  {' ; '.join(route)}")
    visible = sum(n for p, n in field.items() if p[0] or p[3])
    print(f"\ninode or ctime changed in {visible} of {defeated} defeated trials "
          f"(theorem defeat_shows says all)")
    return 1 if missing or visible != defeated else 0


if __name__ == "__main__":
    sys.exit(main())
