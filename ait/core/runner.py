"""Drive a room: build → run arms → write manifest + trials + metrics.

The runner owns everything a room shouldn't repeat: per-trial seeding derived from one
base seed (so a whole run is reproducible from a single number), the output layout, the
manifest, and calling the room's scorer. Arms can be interleaved so provider/time drift
isn't confounded with the arm — the flaw the mapping found in every room.

Output layout (per run):
  runs/<model>/<room>/<run_id>/
    manifest.json           what produced this run
    <arm>.trials.jsonl      one trial record per line
    metrics.json            the room's scored metrics
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import ceiling
from .manifest import Manifest, git_state, docker_image_id
from .provider import Meter, Provider, ProviderConfig
from .room import Room, TrialContext


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)


def stable_hash(*parts: Any) -> int:
    """A hash that is the same in every process. The builtin hash() salts str per process
    (PYTHONHASHSEED), so a seed built on it silently changes between reruns."""
    key = "\x1f".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def trial_seed(base: int, arm: str, trial: int) -> int:
    """Deterministic per-trial seed from one base. Stable across arms and reruns."""
    return (base * 1_000_003 + stable_hash(arm, trial) % 1_000_003) & 0x7FFFFFFF


def is_harness_error(rec: dict[str, Any]) -> bool:
    """A trial the harness itself crashed on (the runner's own catch). It has none of the room's
    fields, so it never reaches room.score(); it is counted beside the room's metrics instead."""
    return rec.get("end_reason") == "harness_error"


def score_records(room: Room, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score a run the same way everywhere (runner, `ait score`, gauntlet).

    Harness-crashed trials are split out before the room scores, so one crashed trial can't
    crash a room's scorer (which reads its own fields) or sit in a rate as a clean outcome.
    Their count lands in each arm as `harness_error`, so the card still shows them.
    """
    ok = [r for r in records if not is_harness_error(r)]
    metrics = room.score(ok) if ok else {"room": room.name, "arms": {}}
    arms = metrics.setdefault("arms", {})
    for r in records:
        if is_harness_error(r):
            a = arms.setdefault(r["arm"], {"n": 0})
            a["harness_error"] = a.get("harness_error", 0) + 1
    for a in arms.values():
        a.setdefault("harness_error", 0)
    # the told-arm ceilings, over the same crash-free records the room scored
    metrics["capability"] = ceiling.assess(room, ok, metrics)
    # what actually served the calls: the requested slug can be an alias for a snapshot
    metrics["served_models"] = served_models(records)
    # and the budget they sent, read off the calls rather than re-derived from the provider's policy
    metrics["sent_max_tokens"] = sent_max_tokens_tally(records)
    return metrics


def _subject_calls(records: list[dict[str, Any]]):
    """Every subject-model call a run recorded: per-trial `calls` and per-agent `calls` (a room's
    reviewer or judge calls live elsewhere and are not the subject's)."""
    for r in records:
        yield from r.get("calls") or []
        for ag in (r.get("agents") or {}).values():
            yield from ag.get("calls") or []


def sent_max_tokens_tally(records: list[dict[str, Any]]) -> dict[str, int]:
    """Count of the max_tokens each recorded call sent (a full call record's `request`, or a slim
    record's own `max_tokens`). Calls that recorded neither are left out, so an empty tally means
    the room doesn't record it, not that nothing was sent."""
    out: dict[str, int] = {}
    for c in _subject_calls(records):
        mt = (c.get("request") or {}).get("max_tokens") or c.get("max_tokens")
        if mt:
            out[str(mt)] = out.get(str(mt), 0) + 1
    return out


def served_models(records: list[dict[str, Any]]) -> dict[str, int]:
    """Count of served-model names across every call a run recorded (per-trial `calls`, per-agent
    `calls`, and the in-container harness's ledger `meta`). "failed_call" = a call that returned no
    response, so no model can be named; "unrecorded" = a successful call with no name. Kept apart
    because a dashboard reading "unrecorded" as possible model drift shouldn't see API failures."""
    out: dict[str, int] = {}

    def add(name: Any) -> None:
        k = str(name) if name else "unrecorded"
        out[k] = out.get(k, 0) + 1

    def add_call(c: dict[str, Any]) -> None:
        if c.get("ok") is False:
            out["failed_call"] = out.get("failed_call", 0) + 1
        else:
            add(c.get("served_model"))

    for r in records:
        for c in r.get("calls") or []:
            add_call(c)
        for ag in (r.get("agents") or {}).values():
            for c in ag.get("calls") or []:
                add_call(c)
        for e in r.get("ledger") or []:
            if isinstance(e, dict) and isinstance(e.get("meta"), dict):
                m = e["meta"]
                add(m.get("served_model") or m.get("model"))
    return out


class Runner:
    def __init__(self, room: Room, config: ProviderConfig, *, out_root: Path,
                 repo: Path, seed_base: int, n: int, concurrency: int = 4,
                 interleave: bool = True, api_key: str | None = None,
                 start_usage: dict[str, Any] | None = None):
        self.room = room
        self.config = config
        self.provider = Provider(config, api_key=api_key)
        self.out_root = out_root
        self.repo = repo
        self.seed_base = seed_base
        self.n = n
        self.concurrency = concurrency
        self.interleave = interleave
        self.start_usage = start_usage or {}     # e.g. the pass's provider-pin probe, counted here

    def run(self, arms: list[str] | None = None, *, build: bool = True,
            out_dir: Path | None = None) -> Path:
        """Run the room's arms and write the run dir. With `out_dir` pointing at an existing run,
        resume it: trials already recorded are kept, crashed ones and missing ones are run (same
        per-trial seeds), and the manifest records the resume. Records are written as each trial
        finishes, so a run that dies keeps what it finished."""
        arms = arms or self.room.default_arms()
        unknown = [a for a in arms if a not in self.room.arms()]
        if unknown:   # before any build or call: a typo'd arm would otherwise crash every trial
            raise ValueError(f"{self.room.name} has no arm(s) {unknown}")

        resume = out_dir is not None and (out_dir / "manifest.json").exists()
        if out_dir is None:
            run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            out_dir = self.out_root / _slug(self.config.model) / self.room.name / run_id
        out = out_dir
        out.mkdir(parents=True, exist_ok=True)

        # a room with one shared world (ait09's compose stack) must run its trials one at a time
        conc = min(self.concurrency, getattr(self.room, "max_concurrency", self.concurrency))

        records: dict[str, list[dict[str, Any]]] = {a: [] for a in arms}
        if resume:
            for recs in load_trials(out).values():
                for r in recs:
                    if r.get("arm") in records and r.get("end_reason") != "harness_error":
                        records[r["arm"]].append(r)
        done = {(a, r["trial"]) for a, rs in records.items() for r in rs}
        lock = threading.Lock()

        # cost and time: carried across resumes in usage.json, updated after every trial
        prior = json.loads((out / "usage.json").read_text()) if resume and (out / "usage.json").exists() else {}
        prior_wall = float(prior.pop("wall_s", 0.0))
        self.provider.meter = Meter(start={k: prior.get(k, 0) + self.start_usage.get(k, 0)
                                           for k in set(prior) | set(self.start_usage)})
        self.start_usage = {}                     # counted once, not again on a later run()
        t0 = time.monotonic()

        def save_usage() -> dict[str, Any]:
            u = {**self.provider.meter.snapshot(), "wall_s": round(prior_wall + time.monotonic() - t0, 1)}
            (out / "usage.json").write_text(json.dumps(u, indent=2))
            return u

        # everything from build() on is inside the try: a room whose build brings its world up and
        # then fails (ait09: stack up, harness import fails), or a manifest step that fails after it,
        # must still be torn down, or the room's fixed container names collide with the next run
        try:
            if build:
                self.room.build()

            if resume:
                manifest = Manifest(**json.loads((out / "manifest.json").read_text()))
                manifest.resumed.append({"at": time.time(), "repo_git": git_state(self.repo),
                                         "argv": list(sys.argv), "trials_kept": len(done)})
                manifest.ended_at = None
            else:
                manifest = Manifest(
                    room=self.room.name, model=self.config.model,
                    provider_config=self._config_dict(),
                    seed_base=self.seed_base, n=self.n, arms=list(arms),
                    repo_git=git_state(self.repo),
                    image=self.room.image, image_id=docker_image_id(self.room.image),
                )
            manifest.write(out / "manifest.json")
            self._write_trials(out, records)          # the kept records, crashed ones dropped

            # build the full job list; interleave arms so drift isn't arm-confounded
            jobs = [(arm, t) for t in range(self.n) for arm in arms if (arm, t) not in done]
            if not self.interleave:
                jobs.sort(key=lambda j: arms.index(j[0]))

            def one(job: tuple[str, int]) -> dict[str, Any]:
                arm, t = job
                ctx = TrialContext(arm=arm, trial=t, seed=trial_seed(self.seed_base, arm, t),
                                   provider=self.provider, image=self.room.image)
                try:
                    rec = self.room.run_trial(ctx)
                except Exception as e:  # noqa: BLE001 - a crashed trial is a record, not a stop
                    rec = {"arm": arm, "trial": t, "end_reason": "harness_error",
                           "decided": False, "error": f"{type(e).__name__}: {e}"}
                with lock:                            # on disk as soon as it's done
                    with (out / f"{_slug(arm)}.trials.jsonl").open("a") as fh:
                        fh.write(json.dumps(rec, default=str) + "\n")
                    save_usage()
                return rec

            with ThreadPoolExecutor(max_workers=conc) as pool:
                for rec in pool.map(one, jobs):
                    records[rec["arm"]].append(rec)
        finally:
            teardown = getattr(self.room, "teardown", None)
            if build and callable(teardown):
                teardown()

        self._write_trials(out, records)
        all_recs = [r for a in arms for r in records[a]]
        metrics = score_records(self.room, all_recs)
        metrics["usage"] = save_usage()     # subject + in-room calls (e.g. ait11's reviewer); not the judges
        (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))

        manifest.finish().write(out / "manifest.json")
        return out

    @staticmethod
    def _write_trials(out: Path, records: dict[str, list[dict[str, Any]]]) -> None:
        for arm, recs in records.items():
            with (out / f"{_slug(arm)}.trials.jsonl").open("w") as fh:
                for r in sorted(recs, key=lambda r: r["trial"]):
                    fh.write(json.dumps(r, default=str) + "\n")

    def _config_dict(self) -> dict[str, Any]:
        c = self.config
        return {"model": c.model, "endpoint": c.endpoint, "temperature": c.temperature,
                "top_p": c.top_p, "max_tokens": c.max_tokens, "order": list(c.order),
                "allow_fallbacks": c.allow_fallbacks, "tries": c.tries,
                "reasoning_effort": c.reasoning_effort}


def load_trials(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Read back a run's trial records for re-scoring, keyed by arm."""
    out: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(run_dir.glob("*.trials.jsonl")):
        arm = f.name[: -len(".trials.jsonl")]
        out[arm] = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out
