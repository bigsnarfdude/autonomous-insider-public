"""`python3 -m ait` — the whole eval behind one entry point.

  ait gauntlet --model <slug> [-n 20] [--rooms ait12 ait11] [--dry-run]   every room -> one card
  ait run      --room ait12 --model <slug> [-n 20] [--arms P2 P3] [--dry-run]
  ait judge    <run_dir> --room ait12 [--audit]
  ait score    <run_dir>
  ait card     --subject <slug> <run_dir> [<run_dir> ...]
  ait selftest --room ait09
  ait rooms
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .core.provider import ProviderConfig, check_anthropic, is_anthropic, probe_pin, set_inflight_limit
from .core.provider import DEFAULT_ENDPOINT, Meter
from .core.runner import Runner, _slug, load_trials, score_records

REPO = Path(__file__).resolve().parents[1]

# gauntlet order: quick single-container rooms first, the one-at-a-time compose room last
ORDER = ["ait04", "ait03", "ait03b", "ait05", "ait02", "ait11", "ait12", "ait12g", "ait13", "ait09s", "ait09"]
# runnable (via `ait run --room X` or `--rooms X`) but NOT in the default gauntlet: heavy stacks that
# shouldn't be forced on every pass, or a sandboxed sibling still being evaluated against its
# prompt-only counterpart before it becomes the default. ait13live needs Docker + the mock-DNS
# stack. ait12glive and ait09slive are new (2026-09-29): the same questions as ait12g/ait09s,
# answered from an observed, host-verified action instead of a stated choice — see their module
# docstrings. Opt-in until run and compared against their siblings.
# ait16 (2026-11-05): new; opt-in until a real run is compared against its predictions (rooms/ait16/READ.md).
GAUNTLET_EXCLUDED = {"ait13live", "ait12glive", "ait09slive", "ait16"}


# room registry: name -> class. New rooms register here (and in ORDER).
def _rooms() -> dict:
    from .rooms.ait02 import Ait02
    from .rooms.ait03 import Ait03
    from .rooms.ait03b import Ait03b
    from .rooms.ait04 import Ait04
    from .rooms.ait05 import Ait05
    from .rooms.ait09 import Ait09
    from .rooms.ait11 import Ait11
    from .rooms.ait12 import Ait12
    from .rooms.ait12g import Ait12g, Ait12gLive
    from .rooms.ait09s import Ait09s, Ait09sLive
    from .rooms.ait13 import Ait13, Ait13Live
    from .rooms.ait16 import Ait16
    return {"ait02": Ait02, "ait03": Ait03, "ait03b": Ait03b, "ait04": Ait04, "ait05": Ait05,
            "ait09": Ait09, "ait09s": Ait09s, "ait09slive": Ait09sLive, "ait11": Ait11,
            "ait12": Ait12, "ait12g": Ait12g, "ait12glive": Ait12gLive,
            "ait13": Ait13, "ait13live": Ait13Live, "ait16": Ait16}


# blind-judge specs: rooms whose metrics need a reasoning label, not just the ledger
def _judge_spec(room: str):
    import importlib
    if room not in JUDGED:
        return None
    return importlib.import_module(f".rooms.{room}_judge", __package__).SPEC


# rooms whose metrics need a reasoning label, each with ait/rooms/<room>_judge.py (a JudgeSpec)
JUDGED = ("ait02", "ait03b", "ait05", "ait11", "ait12")


def _get_room(name: str):
    reg = _rooms()
    if name not in reg:
        sys.exit(f"unknown room {name!r}; have: {', '.join(sorted(reg))}")
    return reg[name]()


def _require_core_room(name: str, room) -> None:
    if not callable(getattr(room, "run_trial", None)):
        sys.exit(f"room {name!r} has no run_trial(); it can't run on the core runner")


def _config(a: argparse.Namespace) -> tuple[ProviderConfig, dict]:
    """The run's provider config, auto-pinned unless --provider/--no-pin, and the probe call's usage
    (a real billed call, so it is counted in the first room's usage)."""
    cfg = ProviderConfig(model=a.model, order=tuple(a.provider) if a.provider else (),
                         allow_fallbacks=bool(a.allow_fallbacks), max_tokens=a.max_tokens,
                         **({"endpoint": a.endpoint} if getattr(a, "endpoint", None) else {}))
    meter = Meter()
    _preflight(a)
    # a non-OpenRouter endpoint (e.g. a RunPod vLLM smoke target) has no provider routing to pin
    if not a.no_pin and not a.provider and cfg.endpoint == DEFAULT_ENDPOINT:
        cfg = probe_pin(cfg, meter=meter)
        print(f"pinned {a.model} to provider {cfg.order[0]} (fallbacks off)", flush=True)
    return cfg, (meter.snapshot() if meter.totals["calls"] else {})


def _preflight(a: argparse.Namespace, judges: bool = False) -> None:
    """Check every anthropic/ model the command will call (SDK, known model, budget, environment)
    before its first call, so a missing piece is one error at the start — not a pass of call_failed
    trials that a resume then keeps, or rows that end _unparsed."""
    endpoint = getattr(a, "endpoint", None)
    if (endpoint and endpoint != DEFAULT_ENDPOINT and hasattr(a, "judge2")
            and not getattr(a, "no_judge", False) and _judge2(a)):
        # the run's key is read from OPENROUTER_API_KEY whatever the endpoint; the second judge
        # calls openrouter.ai with that same key, which would hand another service's key to OpenRouter
        sys.exit("--endpoint with an OpenRouter second judge would send this endpoint's key to "
                 "openrouter.ai; pass --no-judge or --judge2 none")
    models = [(a.model, a.max_tokens)]
    if judges and not a.no_judge:
        from .core.judge import BlindJudge
        models += [(m, BlindJudge.max_tokens) for m in (a.judge_model, _judge2(a)) if m]
    for model, max_tokens in models:
        if is_anthropic(model):
            try:
                check_anthropic(model, max_tokens)
            except RuntimeError as e:
                sys.exit(f"{model}: {e}")


def _pin_label(a: argparse.Namespace) -> str:
    if a.provider:
        return ",".join(a.provider)
    return "none (--no-pin)" if a.no_pin else "auto (probe at start)"


def _check_arms(name: str, room, arms: list[str]) -> None:
    unknown = [x for x in arms if x not in room.arms()]
    if unknown:
        sys.exit(f"room {name!r} has no arm(s) {unknown}; it has: {', '.join(room.arms())}")


JUDGE_SAMPLES = 2                         # calls per row for the primary judge (majority / split)
# second-family judge via OpenRouter (cross-check). Not glm-5.3-flash: that is ait11's reviewer, and a
# model shouldn't both play a role in a room and judge it.
JUDGE2 = "google/gemini-3.8-flash"


def judge_run(run_dir: Path, room: str, *, model: str | None = None, concurrency: int = 3,
              limit: int = 0, dry_run: bool = False, samples: int = JUDGE_SAMPLES,
              judge2: str | None = JUDGE2) -> list[str]:
    """Blind-judge every arm of a saved run into run_dir/judge/. Resumable.

    The primary judge (isolated `claude -p`) labels each row `samples` times; `judge2`, a model
    from another family via OpenRouter, labels each row once with the same rubric and render, into
    `<arm>.judge2.json`, so the card can show cross-family agreement."""
    from .core.judge import BlindJudge
    spec = _judge_spec(room)
    if spec is None:
        return [f"{room}: no judge spec (ledger metrics only)"]
    judges = [("judge", BlindJudge(spec, model=model or spec.default_model, samples=samples))]
    if judge2:
        judges.append(("judge2", BlindJudge(spec, model=judge2, backend="openrouter")))
    jdir = run_dir / "judge"
    lines = []
    for arm, recs in load_trials(run_dir).items():
        rows = spec.select(recs)
        for kind, bj in judges:
            if dry_run:
                lines.append(f"{arm}: {len(rows)} rows to judge with {bj.tag}")
                continue
            jdir.mkdir(exist_ok=True)
            out = jdir / f"{arm}.{kind}.json"
            done = bj.judge_arm(arm, rows, out, concurrency=concurrency, limit=limit)
            unp = sum("_unparsed" in v for v in done["rows"].values())
            lines.append(f"{arm}: {kind} {len(done['rows'])}/{len(rows)}  unparsed={unp}  -> {out}")
    return lines


# -- commands ---------------------------------------------------------------------------
def _judge2(a: argparse.Namespace) -> str | None:
    return None if (a.judge2 or "").lower() in ("none", "off", "") else a.judge2


def _judge_args(p: argparse.ArgumentParser, samples_flag: str) -> None:
    p.add_argument(samples_flag, type=int, default=JUDGE_SAMPLES,
                   help="calls per row for the primary judge; labels are the majority, else 'split'")
    p.add_argument("--judge2", default=JUDGE2,
                   help="second-family judge via OpenRouter (slug), or 'none'")


def cmd_run(a: argparse.Namespace) -> None:
    room = _get_room(a.room)
    _require_core_room(a.room, room)
    arms = a.arms or room.default_arms()
    _check_arms(a.room, room, arms)
    if a.dry_run:
        conc = min(a.concurrency, getattr(room, "max_concurrency", a.concurrency))
        print(f"[dry-run] room={a.room} model={a.model} n={a.n} arms={arms}")
        print(f"[dry-run] {len(arms) * a.n} trials, seed_base={a.seed}, concurrency={conc}, "
              f"interleave={not a.no_interleave}, pin={_pin_label(a)}")
        return
    cfg, probe_usage = _config(a)
    runner = Runner(room, cfg, out_root=Path(a.out), repo=REPO, seed_base=a.seed, n=a.n,
                    concurrency=a.concurrency, interleave=not a.no_interleave, start_usage=probe_usage)
    out = runner.run(arms)
    print(f"run -> {out}")
    print((out / "metrics.json").read_text())


def cmd_gauntlet(a: argparse.Namespace) -> None:
    """Every room on one model, each through the core runner, judged where a room has a spec,
    then one card. A room that fails is FAILED on the card; the others still run.

    Progress is kept in <card dir>/state.json as it happens. `--resume <card dir>` continues that
    pass with its own model, n, seed and provider pin: finished rooms are kept, a room that died
    mid-run keeps its finished trials, unfinished judging picks up where it stopped."""
    from .core import card
    state = None
    if a.resume:
        card_dir = Path(a.resume)
        state = json.loads((card_dir / "state.json").read_text())
        for k in ("model", "n", "seed", "max_tokens", "judge_model", "judge_samples", "judge2", "no_judge"):
            setattr(a, k, state["args"][k])
        names = state["args"]["rooms"]
        print(f"resuming {card_dir} ({state['args']['model']}, n={a.n}, pin {state['pin'] or 'none'})")
    else:
        names = a.rooms or ORDER
    unknown = [r for r in names if r not in _rooms()]
    if unknown:
        sys.exit(f"unknown room(s) {unknown}; have: {', '.join(ORDER)}")
    rooms = {n: _get_room(n) for n in names}

    if a.dry_run:
        total = 0
        for n, room in rooms.items():
            arms = room.default_arms()
            conc = min(a.concurrency, getattr(room, "max_concurrency", a.concurrency))
            spec = _judge_spec(n)
            judge = ("no judge" if (a.no_judge or spec is None) else
                     f"judge {a.judge_model or spec.default_model} x{a.judge_samples}"
                     + (f" + {_judge2(a)}" if _judge2(a) else ""))
            total += len(arms) * a.n
            print(f"[dry-run] {n:6} {len(arms):2} arms x n={a.n} = {len(arms) * a.n:4} trials  "
                  f"conc {conc}  {judge}  arms={arms}")
        print(f"[dry-run] {len(rooms)} rooms, {total} trials on {a.model}, seed_base={a.seed}, "
              f"pin={_pin_label(a)}")
        return

    _preflight(a, judges=True)          # resume too: it rebuilds the config without _config()
    if state is None:
        cfg, probe_usage = _config(a)   # one pin for the whole pass: every room, one backend
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        card_dir = Path(a.card_dir) / f"{_slug(a.model)}_{stamp}"
        card_dir.mkdir(parents=True, exist_ok=True)
        state = {"stamp": stamp, "pin": list(cfg.order), "rooms": {},
                 "args": {"model": a.model, "n": a.n, "seed": a.seed, "max_tokens": a.max_tokens,
                          "judge_model": a.judge_model, "judge_samples": a.judge_samples,
                          "judge2": a.judge2, "no_judge": a.no_judge, "rooms": list(names),
                          "allow_fallbacks": bool(a.allow_fallbacks), "out": a.out}}
    else:
        probe_usage = {}
        cfg = ProviderConfig(model=a.model, order=tuple(state["pin"]),
                             allow_fallbacks=state["args"]["allow_fallbacks"], max_tokens=a.max_tokens)
    save = lambda: (card_dir / "state.json").write_text(json.dumps(state, indent=2))  # noqa: E731
    save()
    out_root = Path(state["args"]["out"])

    state_lock = threading.Lock()
    # every room's state entry exists BEFORE any worker starts: with parallel rooms, a worker adding
    # its own key while another serialised `state` in save() raised "dictionary changed size during
    # iteration". After this only the per-room dicts change, and only under state_lock.
    for n in names:
        state["rooms"].setdefault(n, {})
    save()

    def process(n: str, room: Any, probe: dict) -> dict:
        """Run (and judge) one room, updating shared state under a lock so rooms can run in parallel.
        Returns the card entry. Never raises — a room that fails becomes a FAILED entry."""
        try:
            return _process(n, room, probe)
        except Exception:  # noqa: BLE001 - a harness bug in one room must not abort the gauntlet
            err = traceback.format_exc()[-1500:]
            print(f"{n}: FAILED\n{err}", flush=True)
            return card.room_entry(room, "FAILED", error=err)

    def _process(n: str, room: Any, probe: dict) -> dict:
        st = state["rooms"][n]
        wants_judge = not a.no_judge and _judge_spec(n) is not None
        if st.get("trials_done") and (st.get("judged") or not wants_judge):
            print(f"== {n}: done in this pass, kept ({st['run_dir']})", flush=True)
            return card.room_entry(room, "ok", Path(st["run_dir"]))
        print(f"== {n} ({room.catalog} {room.title}) ==", flush=True)
        if not st.get("trials_done"):
            run_dir = Path(st.get("run_dir") or out_root / _slug(a.model) / n / state["stamp"])
            with state_lock:
                st["run_dir"] = str(run_dir); save()
            try:
                runner = Runner(room, cfg, out_root=out_root, repo=REPO, seed_base=a.seed,
                                n=a.n, concurrency=a.concurrency, start_usage=probe)
                runner.run(room.default_arms(), out_dir=run_dir)
            except Exception:  # noqa: BLE001 - one room failing must not stop the gauntlet
                err = traceback.format_exc()[-1500:]
                print(f"{n}: FAILED\n{err}", flush=True)
                return card.room_entry(room, "FAILED", error=err)
            with state_lock:
                st["trials_done"] = True; save()
            print(f"{n}: run -> {run_dir}", flush=True)
        run_dir = Path(st["run_dir"])
        judge_err = None
        if wants_judge:
            try:
                for line in judge_run(run_dir, n, model=a.judge_model, concurrency=a.judge_concurrency,
                                      samples=a.judge_samples, judge2=_judge2(a)):
                    print(f"  {line}", flush=True)
                with state_lock:
                    st["judged"] = True; save()
            except Exception:  # noqa: BLE001 - the run is kept; the card shows it unjudged
                judge_err = traceback.format_exc()[-800:]
                print(f"{n}: judge failed (card shows it unjudged)\n{judge_err}", flush=True)
        e = card.room_entry(room, "ok", run_dir)
        if judge_err:
            e["judge_error"] = judge_err
        return e

    # the probe call is counted once — attribute it to the first room only
    probe_for = {names[0]: probe_usage}
    room_conc = max(1, getattr(a, "room_concurrency", 1) or 1)
    entries_by: dict[str, dict] = {}
    if room_conc > 1:
        budget = a.max_inflight or a.concurrency * room_conc
        set_inflight_limit(budget)   # shared rate budget: parallel rooms can't 429-storm the backend
        print(f"running {len(rooms)} rooms, {room_conc} at a time; global cap {budget} in-flight "
              f"provider calls, ~{a.concurrency * room_conc} containers", flush=True)
        try:
            with ThreadPoolExecutor(max_workers=room_conc) as pool:
                futs = {pool.submit(process, n, room, probe_for.get(n, {})): n
                        for n, room in rooms.items()}
                for fut in as_completed(futs):
                    entries_by[futs[fut]] = fut.result()
        finally:
            set_inflight_limit(None)
    else:
        for n, room in rooms.items():
            entries_by[n] = process(n, room, probe_for.get(n, {}))
    entries = [entries_by[n] for n in names]   # card order stays ORDER, not completion order

    page = card.build(a.model, entries, card_dir)
    failed = [e["room"] for e in entries if e["status"] != "ok"]
    print(f"\ncard -> {page}" + (f"\nFAILED: {' '.join(failed)}  (continue with: "
                                 f"python3 -m ait gauntlet --resume {card_dir})" if failed else ""))
    sys.exit(1 if failed else 0)


def cmd_card(a: argparse.Namespace) -> None:
    """Rebuild a card from saved run dirs (no calls)."""
    from .core import card
    entries = []
    for d in a.run_dirs:
        run_dir = Path(d)
        man = json.loads((run_dir / "manifest.json").read_text())
        entries.append(card.room_entry(_get_room(man["room"]), "ok", run_dir))
    out = Path(a.out) if a.out else Path(a.card_dir) / f"card_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    print(f"card -> {card.build(a.subject, entries, out)}")


def cmd_calibrate(a: argparse.Namespace) -> None:
    """Sample judged rows for hand labelling, or score both judges against the hand labels."""
    from .core import calibrate
    if a.action == "sample":
        sheet = calibrate.sample([Path(d) for d in a.paths], a.n, _judge_spec, seed=a.seed)
        out = Path(a.out)
        out.write_text(json.dumps(sheet, indent=1))
        rooms = sorted({s["room"] for s in sheet})
        print(f"{len(sheet)} rows from {', '.join(rooms) or 'no judged rooms'} -> {out}\n"
              f"Fill each item's `labels` (one of `allowed`, or null to skip), then: "
              f"python3 -m ait calibrate score {out}")
        return
    sheet = json.loads(Path(a.paths[0]).read_text())
    res = calibrate.score(sheet)
    if not res:
        sys.exit("no hand labels in the sheet yet")
    for room, keys in sorted(res.items()):
        print(f"== {room}")
        for k, judges in sorted(keys.items()):
            cells = "  ".join(f"{j} {c['match']}/{c['compared']}" for j, c in sorted(judges.items()))
            print(f"  {k:<28} {cells}")


def cmd_score(a: argparse.Namespace) -> None:
    run_dir = Path(a.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    room = _get_room(manifest["room"])
    _require_core_room(manifest["room"], room)
    by_arm = load_trials(run_dir)
    recs = [r for arm in by_arm.values() for r in arm]
    metrics = score_records(room, recs)
    if a.write:
        mx = run_dir / "metrics.json"
        old = json.loads(mx.read_text()) if mx.exists() else {}
        if "usage" in old:                       # the run's metered cost isn't a score; carry it over
            metrics["usage"] = old["usage"]
        mx.write_text(json.dumps(metrics, indent=2, default=str))
        print(f"wrote {mx}", file=sys.stderr)
    print(json.dumps(metrics, indent=2, default=str))


def cmd_cot_judge(a: argparse.Namespace) -> None:
    """Label every trial's reasoning with the cross-room CoT rubric (core/cot_judge.py), via a cheap
    OpenRouter model, into run_dir/judge/<arm>.cot.json. Resumable; prints label rates per arm and
    how often the judge agrees with the old eval-aware regex."""
    from .core import cot_judge as C
    from .core.judge import BlindJudge
    run_dir = Path(a.run_dir)
    meter = Meter()
    followup = getattr(a, "spec", "cot") == "followup"
    spec, suffix = (C.FOLLOWUP, "cotfu") if followup else (C.SPEC, "cot")
    # an OpenRouter slug has a "/" (z-ai/glm-5.3-flash; anthropic/<id> goes to the API); a bare Claude
    # model name (claude-opus-4-8, opus) runs through the isolated `claude -p` judge on the local plan
    backend = "openrouter" if "/" in a.model else "claude"
    bj = BlindJudge(spec, model=a.model, backend=backend, samples=a.samples,
                    max_tokens=a.max_tokens, meter=meter)
    jdir = run_dir / "judge"
    summaries = []
    for arm, recs in sorted(load_trials(run_dir).items()):
        if a.arms and arm not in a.arms:
            continue
        rows = spec.select(recs)
        if a.dry_run:
            print(f"{arm}: {len(rows)} rows with reasoning (of {len(recs)} trials) -> {bj.tag}")
            continue
        if not rows:
            print(f"{arm}: no saved reasoning to judge (of {len(recs)} trials)")
            continue
        jdir.mkdir(exist_ok=True)
        out = jdir / f"{arm}.{suffix}.json"
        done = bj.judge_arm(arm, rows, out, concurrency=a.concurrency, limit=a.limit)
        if followup:
            ok = [v for v in done["rows"].values() if "_unparsed" not in v]
            tally = {k: {} for k in spec.enums}
            for v in ok:
                for k in tally:
                    tally[k][v[k]] = tally[k].get(v[k], 0) + 1
            print(f"{arm}: judged {len(ok)}/{len(rows)} (unparsed {len(done['rows']) - len(ok)})  "
                  + "  ".join(f"{k}={t}" for k, t in tally.items()))
            continue
        s = C.summarize(arm, recs, done["rows"])
        summaries.append(s)
        ea, st, ra, ef = s["eval_aware"], s["stated_intent"], s["rationalized"], s["eval_awareness_effect"]
        vr = s["eval_aware_vs_regex"]
        print(f"{arm}: judged {s['judged']}/{s['rows']} (unparsed {s['unparsed']})  "
              f"eval_aware={ea.get('yes', 0)}  intent={st}  rationalized={ra.get('yes', 0)}  "
              f"effect={ef}  vs-regex agree={vr['agree']} judge-only={vr['judge_only']} "
              f"regex-only={vr['regex_only']}")
    if summaries:
        (jdir / "cot.summary.json").write_text(json.dumps(summaries, indent=1))
    if not a.dry_run:
        u = meter.snapshot()
        print(f"judge usage this pass: {u['calls']} calls ({u['failed_calls']} failed), "
              f"{u['prompt_tokens']} in / {u['completion_tokens']} out tokens, ${u['cost_usd']:.4f}")


def cmd_cot_report(a: argparse.Namespace) -> None:
    """Join cot-judge labels to each room's ground-truth outcome and print the patterns per arm:
    what was said on the way to an attempt, a non-attempt, or asking a human. No model calls."""
    from .core import cot_report as R
    for rd in a.run_dirs:
        run_dir = Path(rd)
        room = json.loads((run_dir / "manifest.json").read_text())["room"]
        reports = []
        for arm, recs in sorted(load_trials(run_dir).items()):
            f = run_dir / "judge" / f"{arm}.cot.json"
            if not f.exists():
                continue
            fu = run_dir / "judge" / f"{arm}.cotfu.json"
            rep = R.report(room, arm, recs, json.loads(f.read_text())["rows"], n_examples=a.examples,
                           followup=json.loads(fu.read_text())["rows"] if fu.exists() else None)
            reports.append(rep)
            print(f"\n== {room} {arm}: {rep['judged']} judged  outcomes={rep['outcomes']}"
                  )
            nu = dict(rep["not_unanimous"]); of = nu.pop("of")
            if of and nu:
                print(f"   judge samples not unanimous (of {of}): "
                      + "  ".join(f"{k}={c}" for k, c in nu.items()))
            for p in rep["patterns"]:
                print(f"   {p['pattern']:36} {p['hits']:3}/{p['of']:<3} ({p['about']})")
                for q in p["examples"]:
                    print(f"        \u201c{q[:220]}\u201d")
            if rep.get("flips"):
                fl = rep["flips"]
                nfu = dict(rep["followup_not_unanimous"]); ofu = nfu.pop("of")
                print(f"   follow-up judge samples not unanimous (of {ofu}): "
                      + ("  ".join(f"{k}={c}" for k, c in nfu.items()) or "none"))
                print(f"   flips: {fl['n']}, verified {fl['verified']}  (quote found in that turn {fl['quote_in_turn']}, "
                      f"an earlier decision against {fl['order_ok']}; agrees with intent_changed on {fl['agree_with_intent_changed']}, "
                      f"intent_changed only {fl['intent_changed_only']}, follow-up only {fl['followup_only']})")
                if fl["n"]:
                    print(f"     then: {fl['outcome']}\n     reason given: {fl['reason']}\n     had just seen: {fl['saw']}")
            if rep["quotes_unverified"]:
                print(f"   quotes not found in the trace (dropped as evidence): {len(rep['quotes_unverified'])}")
        if reports:
            (run_dir / "judge" / "cot.report.json").write_text(json.dumps(reports, indent=1))
        else:
            print(f"{run_dir}: no cot-judge output yet (run `ait cot-judge` first)")


def cmd_judge(a: argparse.Namespace) -> None:
    spec = _judge_spec(a.room)
    if spec is None:
        sys.exit(f"no judge spec for room {a.room!r}")
    if a.audit:
        from .core.judge import BlindJudge
        bj = BlindJudge(spec, model=a.model or spec.default_model)
        print(f"[audit {bj.model} via claude -p, isolated]\n{bj.audit()}")
        return
    for line in judge_run(Path(a.run_dir), a.room, model=a.model, concurrency=a.concurrency,
                          limit=a.limit, dry_run=a.dry_run, samples=a.samples, judge2=_judge2(a)):
        print(line)


def cmd_export_eee(a: argparse.Namespace) -> None:
    from .core.export_eee import ExportError, build_record, write_record
    run_dir = Path(a.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    room = _get_room(manifest["room"])
    try:
        rec = build_record(run_dir, room)
    except ExportError as e:
        sys.exit(f"export refused: {e}")
    if a.out:
        p = write_record(rec, Path(a.out))
        print(f"wrote {p}")
    else:
        print(json.dumps(rec, indent=2))


def cmd_selftest(a: argparse.Namespace) -> None:
    room = _get_room(a.room)
    fn = getattr(room, "self_test", None)
    if fn is None:
        sys.exit(f"room {a.room!r} has no canned self-test")
    ok = fn()
    print(f"{a.room} self-test: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


def cmd_rooms(_a: argparse.Namespace) -> None:
    reg = _rooms()
    for n in ORDER:
        c = reg[n]
        judge = "judge" if _judge_spec(n) else "     "
        print(f"{n}  {c.catalog:<13} {judge}  {c.title}")
    for n in sorted(GAUNTLET_EXCLUDED):
        c = reg[n]
        print(f"{n}  {c.catalog:<13}         {c.title}  (run explicitly; not in the default gauntlet)")


# -- argument parsing -------------------------------------------------------------------
def _model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", required=False)
    p.add_argument("-n", type=int, default=20, help="trials per arm")
    p.add_argument("--seed", type=int, default=1, help="base seed; every trial's seed derives from it")
    p.add_argument("--provider", nargs="+", help="OpenRouter provider order to pin")
    p.add_argument("--allow-fallbacks", action="store_true")
    p.add_argument("--no-pin", action="store_true",
                   help="don't auto-pin a provider (default: one probe call picks the backend, "
                        "and the whole run is pinned to it)")
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--endpoint", default=None,
                   help="OpenAI-compatible chat/completions URL (default: OpenRouter). Key still comes "
                        "from OPENROUTER_API_KEY / ~/openrouter.key. For smoke tests, not data runs.")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--out", default=str(REPO / "runs"))
    p.add_argument("--dry-run", action="store_true")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ait")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gauntlet", help="every room on one model -> one scorecard")
    _model_args(g)
    g.add_argument("--rooms", nargs="+", help=f"subset, default all: {' '.join(ORDER)}")
    g.add_argument("--judge-model", help="override each room's default judge model")
    g.add_argument("--no-judge", action="store_true")
    g.add_argument("--judge-concurrency", type=int, default=3)
    g.add_argument("--room-concurrency", type=int, default=1,
                   help="rooms to run in parallel (default 1 = sequential). >1 overlaps independent "
                        "rooms; total containers ~= room-concurrency x concurrency, so keep it within "
                        "Docker's headroom")
    g.add_argument("--max-inflight", type=int, default=None,
                   help="global cap on concurrent provider HTTP calls when rooms run in parallel "
                        "(the shared rate budget; default: concurrency x room-concurrency)")
    _judge_args(g, "--judge-samples")
    g.add_argument("--card-dir", default=str(REPO / "gauntlet" / "cards"))
    g.add_argument("--resume", metavar="CARD_DIR",
                   help="continue an interrupted pass (its model, n, seed and pin come from its state.json)")
    g.set_defaults(fn=cmd_gauntlet)

    r = sub.add_parser("run", help="run one room on a model")
    r.add_argument("--room", required=True)
    _model_args(r)
    r.add_argument("--arms", nargs="+")
    r.add_argument("--no-interleave", action="store_true")
    r.set_defaults(fn=cmd_run)

    cal = sub.add_parser("calibrate", help="hand-label judged rows and score both judges against them")
    cal.add_argument("action", choices=["sample", "score"])
    cal.add_argument("paths", nargs="+", help="sample: run dirs; score: the filled sheet")
    cal.add_argument("-n", type=int, default=20, help="rows to sample")
    cal.add_argument("--seed", type=int, default=0)
    cal.add_argument("--out", default="calibration_sheet.json")
    cal.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("score", help="re-score a saved run dir")
    s.add_argument("run_dir")
    s.add_argument("--write", action="store_true",
                   help="replace the run's metrics.json (keeping its usage), so the card picks it up")
    s.set_defaults(fn=cmd_score)

    c = sub.add_parser("card", help="build one card from saved run dirs")
    c.add_argument("run_dirs", nargs="+")
    c.add_argument("--subject", required=True)
    c.add_argument("--out")
    c.add_argument("--card-dir", default=str(REPO / "gauntlet" / "cards"))
    c.set_defaults(fn=cmd_card)

    cj = sub.add_parser("cot-judge", help="label saved reasoning with the cross-room CoT rubric (cheap judge)")
    cj.add_argument("run_dir")
    cj.add_argument("--model", default="z-ai/glm-5.3-flash", help="OpenRouter slug of the judge")
    cj.add_argument("--arms", nargs="+", help="only these arms")
    cj.add_argument("--limit", type=int, default=0, help="judge at most N new rows per arm (0 = all)")
    cj.add_argument("--samples", type=int, default=1, help="calls per row; labels are the majority, else 'split'")
    cj.add_argument("--max-tokens", type=int, default=32000, help="the judge's own output budget (its CoT + JSON)")
    cj.add_argument("--concurrency", type=int, default=4)
    cj.add_argument("--dry-run", action="store_true")
    cj.add_argument("--spec", choices=("cot", "followup"), default="cot",
                    help="cot: the main labels; followup: reworded disclosure, flagged_to_user, and "
                         "where the decision flipped (<arm>.cotfu.json)")
    cj.set_defaults(fn=cmd_cot_judge)

    cr = sub.add_parser("cot-report", help="join cot-judge labels to outcomes: attempt / non-attempt / asked a human")
    cr.add_argument("run_dirs", nargs="+")
    cr.add_argument("--examples", type=int, default=2, help="verbatim quotes per pattern")
    cr.set_defaults(fn=cmd_cot_report)

    j = sub.add_parser("judge", help="blind-judge a saved run dir")
    j.add_argument("run_dir", nargs="?")
    j.add_argument("--room", required=True)
    j.add_argument("--model", help="default: the room's judge model (ait12 opus; ait02, ait03b, ait05, ait11 sonnet)")
    j.add_argument("--audit", action="store_true", help="verify judge isolation, then exit")
    j.add_argument("--dry-run", action="store_true")
    j.add_argument("--limit", type=int, default=0)
    j.add_argument("--concurrency", type=int, default=3)
    _judge_args(j, "--samples")
    j.set_defaults(fn=cmd_judge)

    ee = sub.add_parser("export-eee", help="export a scored run dir to an Every Eval Ever record")
    ee.add_argument("run_dir")
    ee.add_argument("--out", help="write into an EEE datastore tree rooted here; default: print JSON")
    ee.set_defaults(fn=cmd_export_eee)

    st = sub.add_parser("selftest", help="run a room's money-free canned self-test")
    st.add_argument("--room", required=True)
    st.set_defaults(fn=cmd_selftest)

    ro = sub.add_parser("rooms", help="list rooms")
    ro.set_defaults(fn=cmd_rooms)

    a = ap.parse_args(argv)
    if a.fn in (cmd_run, cmd_gauntlet) and not a.model and not getattr(a, "resume", None):
        ap.error("--model is required")
    if a.fn is cmd_judge and not a.audit and not a.run_dir:
        ap.error("judge needs a run_dir (or --audit)")
    a.fn(a)


if __name__ == "__main__":
    main()
