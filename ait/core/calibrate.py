"""Calibrate the judges against hand labels.

The card reports how often the primary judge's repeat calls agree and how often the second model
family agrees with it. Neither says which is *right*. This does: sample judged rows into a sheet a
person labels, then score each judge against those labels.

  sample(run_dirs, n) -> sheet   rows the primary judge parsed, drawn across rooms; each item has the
                                 same blind view the judges saw, the allowed values, and blank labels
  score(sheet)        -> table   per room and label: how often each judge matches the hand label

The sheet is JSON so it can be edited in any editor: fill each item's `labels` (null = skip).
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Callable

from .runner import load_trials


def _rows(run_dir: Path, spec: Any) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for arm, recs in load_trials(run_dir).items():
        for r in spec.select(recs):
            out[(arm, str(r["trial"]))] = r
    return out


def _judge_file(run_dir: Path, arm: str, kind: str) -> dict[str, Any]:
    f = run_dir / "judge" / f"{arm}.{kind}.json"
    return json.loads(f.read_text()) if f.exists() else {}


def sample(run_dirs: list[Path], n: int, spec_for: Callable[[str], Any], *, seed: int = 0) -> list[dict[str, Any]]:
    pool = []
    for d in run_dirs:
        room = json.loads((d / "manifest.json").read_text())["room"]
        spec = spec_for(room)
        if spec is None:
            continue
        rows = _rows(d, spec)
        for (arm, t), row in rows.items():
            v = _judge_file(d, arm, "judge").get("rows", {}).get(t)
            if v and "_unparsed" not in v:
                pool.append((room, d, arm, t, row, spec))
    rng = random.Random(seed)
    rng.shuffle(pool)
    # spread across rooms: round-robin by room, so one big room can't fill the sheet
    by_room: dict[str, list] = {}
    for item in pool:
        by_room.setdefault(item[0], []).append(item)
    picked = []
    while len(picked) < n and any(by_room.values()):
        for room in sorted(by_room):
            if by_room[room] and len(picked) < n:
                picked.append(by_room[room].pop())
    sheet = []
    for i, (room, d, arm, t, row, spec) in enumerate(picked):
        sheet.append({"id": i, "room": room, "run_dir": str(d), "arm": arm, "trial": t,
                      "view": spec.render(row, {}),
                      "allowed": {k: sorted(v) for k, v in spec.enums.items()},
                      "labels": {k: None for k in spec.enums}})
    return sheet


def score(sheet: list[dict[str, Any]]) -> dict[str, Any]:
    """Per room, per label, per judge: matches / compared. Unlabelled (null) fields are skipped; a
    judge's `split` counts as a miss (it gave no label)."""
    out: dict[str, Any] = {}
    for item in sheet:
        d = Path(item["run_dir"])
        room = out.setdefault(item["room"], {})
        for kind in ("judge", "judge2"):
            v = _judge_file(d, item["arm"], kind).get("rows", {}).get(item["trial"])
            if not v or "_unparsed" in v:
                continue
            for k, human in item["labels"].items():
                if human is None:
                    continue
                cell = room.setdefault(k, {}).setdefault(kind, {"match": 0, "compared": 0})
                cell["compared"] += 1
                cell["match"] += str(v.get(k)).strip().lower() == str(human).strip().lower()
    return {room: keys for room, keys in out.items() if keys}      # rooms with no hand labels drop
