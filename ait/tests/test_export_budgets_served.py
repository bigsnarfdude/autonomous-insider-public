"""The export must state the budgets and the model that actually ran, not the run's defaults
(review 2026-10-02 #5/#6). No network, no Docker."""
import json

import pytest

from ait.core.export_eee import ExportError, build_record


def _rate(h, d):
    return {"hits": h, "decided": d, "undecided": 0, "hits_undecided": 0, "source": "exact"}


def _run(tmp_path, room, model="z-ai/glm-5.3-flash", max_tokens=8192, metrics=None):
    man = {"room": room.name, "model": model, "seed_base": 1, "n": 2, "arms": room.default_arms(),
           "provider_config": {"temperature": 0.7, "top_p": 0.8, "max_tokens": max_tokens,
                               "order": ["P"], "allow_fallbacks": False, "tries": 8},
           "repo_git": {"commit": "deadbeef" * 5, "dirty": False, "branch": "master"},
           "started_at": 1790600000}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "manifest.json").write_text(json.dumps(man))
    specs = getattr(room, "metric_specs", {}) or {}
    mid = next(iter(specs))
    m = metrics or {}
    m.setdefault("arms", {room.default_arms()[0]: {"n": 2, mid: _rate(1, 2)}})
    (tmp_path / "metrics.json").write_text(json.dumps(m))
    return tmp_path


def _gen(rec):
    return rec["evaluation_results"][0]["generation_config"]["generation_args"]


def test_room_token_budgets_are_what_the_calls_used(tmp_path):
    # Why: only ait13 declared max_tokens, so ait12g (fixed 24576) and ait11/ait03b (subject at
    # max(run, 24576)) exported the run's 8192 — a budget their calls never had.
    from ait.rooms.ait12g import Ait12g
    from ait.rooms.ait11 import Ait11
    from ait.rooms.ait03b import Ait03b
    assert _gen(build_record(_run(tmp_path / "a", Ait12g()), Ait12g()))["max_tokens"] == 24576
    for R in (Ait11, Ait03b):
        assert _gen(build_record(_run(tmp_path / f"{R.name}8", R()), R()))["max_tokens"] == 24576
        assert _gen(build_record(_run(tmp_path / f"{R.name}32", R(), max_tokens=32000), R()))["max_tokens"] == 32000


def test_every_multi_turn_room_exports_its_step_cap(tmp_path):
    # Why: eval_limits appeared only for ait13live; every other room's step cap went unstated. ait11's
    # caps differ by arm (D2 runs 6 steps, the J arms 10), so the per-arm caps go out too.
    from ait.__main__ import _rooms
    for name, R in sorted(_rooms().items()):
        room = R()
        if name in ("ait12g", "ait13"):            # prompt-only: one call, no step loop
            assert getattr(room, "max_steps", None) is None, name
            continue
        assert isinstance(getattr(room, "max_steps", None), int) and room.max_steps > 0, name
    from ait.rooms.ait11 import Ait11
    rec = build_record(_run(tmp_path / "s", Ait11()), Ait11())
    assert _gen(rec)["eval_limits"]["message_limit"] == 10
    caps = json.loads(_gen(rec)["eval_plan"]["config"]["step_caps"])
    assert caps["D2"] == 6 and caps["J1"] == 10


def test_the_served_model_is_reported_and_mixed_backends_refused(tmp_path):
    # Why: model_info named the requested slug even when it's an alias for a snapshot; metrics.json
    # already tallies what served each call (served_models).
    from ait.rooms.ait12g import Ait12g
    served = {"deepseek/deepseek-v4-flash-0423": 19, "failed_call": 1}
    rec = build_record(_run(tmp_path / "a", Ait12g(), model="deepseek/deepseek-v4-flash",
                            metrics={"served_models": served}), Ait12g())
    mi = rec["model_info"]
    assert mi["id"] == "deepseek/deepseek-v4-flash"                       # the slug the run asked for
    assert mi["name"] == "deepseek/deepseek-v4-flash-0423"                # what actually answered
    assert json.loads(mi["additional_details"]["served_models"]) == served
    with pytest.raises(ExportError, match="more than one model"):
        build_record(_run(tmp_path / "b", Ait12g(), metrics={"served_models": {"m/a": 3, "m/b": 2}}), Ait12g())
    old = build_record(_run(tmp_path / "c", Ait12g()), Ait12g())           # a run from before the tally
    assert old["model_info"]["additional_details"]["served_models"] == "not recorded"


def test_the_recorded_budget_wins_over_the_derived_one(tmp_path):
    # Why: the export re-derived the provider's max_tokens policy from the model prefix and today's
    # constant, so a run recorded under another policy (before the 32000 floor) was exported with a
    # budget its calls never had. The calls' own record is read at score time instead.
    from ait.core.runner import sent_max_tokens_tally
    from ait.rooms.ait12g import Ait12g
    recs = [{"calls": [{"request": {"max_tokens": 24576}}]},
            {"agents": {"a1": {"calls": [{"max_tokens": 24576}, {"ok": False}]}}}]
    assert sent_max_tokens_tally(recs) == {"24576": 2}
    from ait.core.runner import score_records
    from ait.tests.test_gauntlet import FakeRoom
    assert score_records(FakeRoom(), [{"arm": "A", "trial": 0, "end_reason": "harness_error",
                                       **recs[0]}])["sent_max_tokens"] == {"24576": 1}   # metrics.json has it
    rec = build_record(_run(tmp_path / "a", Ait12g(), model="anthropic/claude-opus-5-5",
                            metrics={"sent_max_tokens": {"24576": 6}}), Ait12g())
    assert _gen(rec)["max_tokens"] == 24576
    assert rec["source_metadata"]["additional_details"]["ait.max_tokens_source"] == "recorded"
    old = build_record(_run(tmp_path / "b", Ait12g(), model="anthropic/claude-opus-5-5"), Ait12g())
    assert _gen(old)["max_tokens"] == 32000                                 # no record: derived, and says so
    assert old["source_metadata"]["additional_details"]["ait.max_tokens_source"] == "derived"


def test_an_anthropic_run_exports_what_its_calls_had(tmp_path):
    # Why: an anthropic/ run exported the manifest's temperature 0.7 / top_p 0.8 (never sent: the API
    # rejects sampling params) and inference_platform "openrouter".
    from ait.rooms.ait12g import Ait12g
    rec = build_record(_run(tmp_path / "a", Ait12g(), model="anthropic/claude-opus-5-5"), Ait12g())
    assert _gen(rec)["temperature"] is None and _gen(rec)["top_p"] is None
    assert rec["model_info"]["inference_platform"] == "anthropic"
    glm = build_record(_run(tmp_path / "b", Ait12g()), Ait12g())
    assert _gen(glm)["temperature"] == 0.7 and glm["model_info"]["inference_platform"] == "openrouter"
