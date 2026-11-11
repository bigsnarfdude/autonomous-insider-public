#!/usr/bin/env python3
"""Layer 1d — draw a seeded random sample for a hand check of the rule classes. Offline.

Writes handcheck.md: per row, the submitted URL, title, decoded payload (trimmed), the rule's class
and reason, and a blank `you:` line. Fill in agent / background / unclear, then run
`u4_handcheck.py --score` to get rule-vs-you agreement per class. Works on a plane.
"""
import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "handcheck.md"


def draw(k: int, seed: int) -> int:
    rows = [json.loads(l) for l in open(HERE / "decoded.jsonl")]
    # stratify: equal share per rule class, so a rare class still gets checked
    by = {}
    for r in rows:
        by.setdefault(r["class"], []).append(r)
    rng = random.Random(seed)
    per = max(1, k // len(by))
    pick = []
    for c in sorted(by):
        pick += rng.sample(by[c], min(per, len(by[c])))
    rng.shuffle(pick)
    lines = [f"# hand check — {len(pick)} rows (seed {seed}, {per} per rule class)", "",
             "Fill each `you:` with agent / background / unclear. Rule class is hidden below the "
             "payload on purpose — read the payload first.", ""]
    for i, r in enumerate(pick, 1):
        lines += [f"## {i}. {r['report_id']}  ({r['visited']})", "",
                  f"- url: `{r['url'][:300]}`", f"- title: `{r['title'][:200]}`",
                  f"- hosts: {', '.join(r['hosts'][:8])}", "", "```",
                  (r["decoded"][:1200] or "(nothing decoded)"), "```", "",
                  "you: ", "",
                  f"<details><summary>rule</summary>{r['class']} — {r['why']}</details>", ""]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} ({len(pick)} rows)")
    return 0


def score() -> int:
    t = OUT.read_text()
    pairs = re.findall(r"\nyou:\s*(\w*)\s*\n.*?<summary>rule</summary>(\w+)", t, re.S)
    done = [(y.lower(), r) for y, r in pairs if y]
    if not done:
        print("no `you:` answers filled in yet")
        return 1
    norm = {"agent": "agent_like", "agent_like": "agent_like", "background": "background", "unclear": "unclear"}
    agree = Counter()
    tot = Counter()
    for y, r in done:
        tot[r] += 1
        agree[r] += norm.get(y, y) == r
    print(f"{len(done)}/{len(pairs)} answered")
    for c in tot:
        print(f"  rule={c}: you agree {agree[c]}/{tot[c]}")
    conf = Counter((r, norm.get(y, y)) for y, r in done)
    print("  rule -> you:", dict(conf))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    sys.exit(score() if a.score else draw(a.k, a.seed))
