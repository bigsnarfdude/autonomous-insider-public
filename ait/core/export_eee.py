"""Export a scored run dir to an Every Eval Ever (EEE) aggregate record.

EEE is the run-data schema behind Evaluation Cards (github.com/evaleval/every_eval_ever,
`eval.schema.json`). This maps what a run already wrote — manifest.json + metrics.json — onto it,
using native fields wherever they exist and `details` (string values only, per the schema) for
what EEE has no field for, under stable `ait.` keys so nothing is silently dropped:

  one evaluation_results entry per (arm, rate)   score = hits / decided
  uncertainty.num_samples = decided, confidence_interval = Wilson 95%
  details: ait.hits, ait.decided, ait.undecided, ait.hits_undecided, ait.n, ait.source
  generation_args: temperature / top_p (null for anthropic/: none are sent) / max_tokens (what the
                   calls recorded, else the room's budget, labelled ait.max_tokens_source),
                   eval_plan (arms, seed, pin, per-arm step caps), eval_limits (the room's largest
                   step cap), sandbox (docker image)
  model_info: id = the requested slug, name = the model that served it (metrics' served_models);
              a run served by more than one model is refused

Refusals, not silent fixes: a dirty or unfinished run, a room with a harness INVALID banner, and
any rate the room hasn't declared a direction for (`metric_specs`) all raise. A rate with 0
decided trials has no score and is left out, listed under `ait.omitted`.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

from .benchcard import MetricSpec
from .provider import is_anthropic

SCHEMA_VERSION = "0.3.0"
COLLECTION = "autonomous-insider"


def wilson(hits: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """95% Wilson score interval for hits/n (n > 0). Stays inside [0, 1] at 0 and n hits."""
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _is_rate(v: Any) -> bool:
    return isinstance(v, dict) and {"hits", "decided", "undecided"} <= v.keys()


def _s(v: Any) -> str:
    return json.dumps(v) if isinstance(v, (dict, list)) else str(v)


class ExportError(ValueError):
    pass


def _max_tokens(room: Any, cfg: dict[str, Any], model: str,
                metrics: dict[str, Any]) -> tuple[int, str]:
    """(the budget the calls used, where that number came from). The calls' own record wins
    (metrics' sent_max_tokens; the largest if they differ, e.g. ait11's subject and a floored retry);
    a run scored before calls recorded it falls back to the room's declared budget, passed through
    the provider's current policy — labelled "derived", since that policy may postdate the run."""
    from .provider import sent_max_tokens
    tally = metrics.get("sent_max_tokens") or {}
    if tally:
        return max(int(k) for k in tally), "recorded"
    run = int(cfg.get("max_tokens") or 0)
    fn = getattr(room, "effective_max_tokens", None)
    mt = int(fn(run)) if callable(fn) else int(getattr(room, "max_tokens", None) or run or 1)
    return sent_max_tokens(model, mt), "derived"


_NOT_A_MODEL = {"unrecorded", "failed_call"}


def _served(metrics: dict[str, Any]) -> tuple[str | None, str]:
    """(the one model that served the run, or None if not recorded; the tally as a details string).
    More than one served model in a pinned run is provider drift: refuse, don't pick one."""
    tally = metrics.get("served_models")
    if not tally:
        return None, "not recorded"
    names = sorted(k for k in tally if k not in _NOT_A_MODEL)
    if len(names) > 1:
        raise ExportError(f"run was served by more than one model {names}; the rates mix backends")
    return (names[0] if names else None), json.dumps(tally)


def build_record(run_dir: Path, room: Any, *, org: str = "bigsnarfdude",
                 now: float | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    man = json.loads((run_dir / "manifest.json").read_text())
    mpath = run_dir / "metrics.json"
    if not mpath.exists():
        raise ExportError(f"{run_dir}: no metrics.json (run not finished or not scored)")
    metrics = json.loads(mpath.read_text())
    git = man.get("repo_git") or {}
    if git.get("dirty"):
        raise ExportError(f"{run_dir}: run was made from a dirty tree; the commit isn't the code that ran")
    if metrics.get("invalid"):
        raise ExportError(f"{run_dir}: the room marked this run INVALID")
    specs: dict[str, MetricSpec] = getattr(room, "metric_specs", None) or {}

    model = man["model"]
    served_name, served_detail = _served(metrics)
    developer, _, short = model.partition("/")
    cfg = man.get("provider_config") or {}
    pin = ",".join(cfg.get("order") or []) or "none"
    now = time.time() if now is None else now
    started = man.get("started_at") or now

    anthropic = is_anthropic(model)
    max_tokens, max_tokens_source = _max_tokens(room, cfg, model, metrics)
    gen_args: dict[str, Any] = {
        # the Anthropic API takes no sampling params, so none were sent (the manifest's are unused)
        "temperature": None if anthropic else cfg.get("temperature"),
        "top_p": None if anthropic else cfg.get("top_p"),
        # what the calls actually used (see _max_tokens)
        "max_tokens": max_tokens,
        "eval_plan": {
            "name": f"ait:{man['room']}",
            "steps": [json.dumps({"arms": man.get("arms"), "interleave": True})],
            "config": {"seed_base": _s(man.get("seed_base")), "n_per_arm": _s(man.get("n")),
                       "provider_pin": pin, "allow_fallbacks": _s(cfg.get("allow_fallbacks")),
                       "tries": _s(cfg.get("tries")),
                       **({"step_caps": json.dumps(caps)} if (caps := getattr(room, "step_caps", None)) else {})},
        },
    }
    steps = getattr(room, "max_steps", None)
    if steps:
        gen_args["eval_limits"] = {"message_limit": int(steps)}
    if man.get("image"):
        gen_args["sandbox"] = {"type": "docker", "config": f"{man['image']}@{man.get('image_id') or 'unknown'}"}

    # the told-arm ceilings (core/ceiling.py): an intent rate the card withholds must not leave as a
    # bare score, or the export reintroduces couldn't-vs-wouldn't (review 2026-10-02)
    cap = metrics.get("capability")
    cap_status = ("not assessed (run predates capability ceilings)" if not cap
                  else f"{cap.get('status')}" + (f": {cap.get('reason')}" if cap.get("reason") else ""))
    told_of: dict[tuple[str, str], dict[str, Any]] = {}      # (told arm, metric) -> ceiling
    intent_of: dict[tuple[str, str], dict[str, Any]] = {}    # (intent arm, metric) -> ceiling
    for c in (cap or {}).get("ceilings") or []:
        told_of[(c["told_arm"], c["metric"])] = c
        for arm_id in (c.get("arms") or {}):
            intent_of[(arm_id, c["metric"])] = c

    def ceiling_details(arm: str, mid: str) -> dict[str, str]:
        if (arm, mid) in told_of:
            c = told_of[(arm, mid)]
            return {"ait.arm_role": "told (capability ceiling)", "ait.ceiling.verdict": _s(c["verdict"])}
        c = intent_of.get((arm, mid))
        if c is None:
            return {}
        e = c["arms"][arm]
        out = {"ait.arm_role": "intent", "ait.ceiling.verdict": _s(c["verdict"]),
               "ait.ceiling.told_arm": _s(c["told_arm"]), "ait.ceiling.value": _s(c.get("ceiling")),
               "ait.ceiling.bound": _s(c.get("bound")),
               "ait.withheld": _s(e.get("normalised") is None)}
        if e.get("normalised") is not None:
            out["ait.normalised"] = _s(e["normalised"])
            out["ait.normalised_ci"] = _s(e.get("normalised_ci"))
        return out

    results: list[dict[str, Any]] = []
    omitted: list[str] = []
    undeclared: list[str] = []
    for arm, block in sorted((metrics.get("arms") or {}).items()):
        for mid, v in block.items():
            if not _is_rate(v):
                continue
            key = f"{man['room']}/{arm}/{mid}"
            spec = specs.get(mid)
            if spec is None:
                undeclared.append(mid)
                continue
            if v["decided"] == 0:
                omitted.append(key)
                continue
            lo, hi = wilson(v["hits"], v["decided"])
            results.append({
                "evaluation_result_id": key,
                "evaluation_name": f"{man['room']}/{arm}",
                "source_data": {"dataset_name": f"{COLLECTION}/{man['room']}", "source_type": "other",
                                "additional_details": {"arm": arm, "ait.catalog": _s(getattr(room, "catalog", ""))}},
                "evaluation_timestamp": _s(int(started)),
                "metric_config": {
                    **({"evaluation_description": spec.definition} if spec.definition else {}),
                    "metric_id": spec.id, "metric_name": spec.name or spec.id,
                    "metric_kind": spec.kind, "metric_unit": spec.unit,
                    "lower_is_better": spec.lower_is_better, "score_type": "continuous",
                    "min_score": 0, "max_score": 1,
                    "additional_details": {"ait.source": spec.source, "ait.headline": _s(spec.headline)},
                },
                "score_details": {
                    "score": v["hits"] / v["decided"],
                    "details": {"ait.hits": _s(v["hits"]), "ait.decided": _s(v["decided"]),
                                "ait.undecided": _s(v["undecided"]),
                                "ait.hits_undecided": _s(v.get("hits_undecided", 0)),
                                "ait.n": _s(block.get("n")), "ait.source": _s(v.get("source")),
                                "ait.harness_error": _s(block.get("harness_error", 0)),
                                **ceiling_details(arm, mid)},
                    "uncertainty": {"confidence_interval": {"lower": lo, "upper": hi,
                                                            "confidence_level": 0.95, "method": "wilson"},
                                    "num_samples": v["decided"]},
                },
                "generation_config": {"generation_args": gen_args},
            })
    if undeclared:
        raise ExportError(f"{man['room']}: no metric_specs entry (direction/source) for "
                          f"{sorted(set(undeclared))}; declare them on the room before exporting")
    if not results:
        raise ExportError(f"{run_dir}: nothing exportable (every rate had 0 decided trials)")

    return {
        "schema_version": SCHEMA_VERSION,
        "evaluation_id": f"{COLLECTION}/{man['room']}/{model}/{int(now)}",
        "evaluation_timestamp": _s(int(started)),
        "retrieved_timestamp": _s(int(now)),
        "source_metadata": {"source_name": "Autonomous Insider gauntlet", "source_type": "evaluation_run",
                            "source_organization_name": org, "evaluator_relationship": "third_party",
                            "additional_details": {"ait.catalog": _s(getattr(room, "catalog", "")),
                                                   "ait.capability": _s(cap_status),
                                                   "ait.omitted": _s(omitted),
                                                   "ait.max_tokens_source": max_tokens_source,
                                                   "ait.rates_over": "decided trials only; undecided "
                                                   "trials are counted in details, never as clean"}},
        "eval_library": {"name": "ait", "version": (git.get("commit") or "unknown")[:12],
                         "additional_details": {"dirty": _s(bool(git.get("dirty"))),
                                                "branch": _s(git.get("branch"))}},
        # id = the slug the run requested; name = what actually answered (an alias resolves to a snapshot)
        "model_info": {"name": served_name or model, "id": model, "developer": developer or "unknown",
                       "inference_platform": "anthropic" if anthropic else "openrouter",
                       "additional_details": {
                           # required by the schema; "unknown" is honest here — the run doesn't
                           # record either, and OpenRouter serves both open- and closed-weight models
                           "deployment_type": "unknown", "model_availability": "unknown",
                           "provider_pin": pin, "model_short": short or model,
                           "served_models": served_detail}},
        "evaluation_results": results,
    }


def write_record(rec: dict[str, Any], out_root: Path) -> Path:
    """EEE datastore layout: data/<collection>/<developer>/<model>/<uuid>.json"""
    dev, _, short = rec["model_info"]["id"].partition("/")
    d = Path(out_root) / "data" / COLLECTION / (dev or "unknown") / (short or dev)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid5(uuid.NAMESPACE_URL, rec['evaluation_id'])}.json"
    p.write_text(json.dumps(rec, indent=2))
    return p
