"""ait -> Every Eval Ever export. No network. No Docker.

The framework is stdlib-only (README); `jsonschema` is not a dependency, so the schema-validation
tests are skipped when it isn't installed rather than added as a new requirement.
"""
from __future__ import annotations

import json

import pytest

from ait.core.export_eee import ExportError, build_record, wilson
from ait.rooms.ait13 import Ait13, Ait13Live


def _validate(rec, schema):
    """Schema conformance needs the optional `jsonschema` (the framework is stdlib-only). Skip just
    this check without it — never the whole module, which would also skip the tests that don't need it."""
    js = pytest.importorskip("jsonschema", reason="optional, for schema-conformance checks only")
    js.validate(rec, schema)

MANIFEST = {
    "room": "ait13live", "model": "z-ai/glm-5.3-flash", "seed_base": 1, "n": 5,
    "arms": ["bare", "rule"],
    "provider_config": {"temperature": 0.7, "top_p": 0.8, "max_tokens": 8192,
                        "order": ["InferenceNet"], "allow_fallbacks": False, "tries": 8},
    "repo_git": {"commit": "deadbeef" * 5, "dirty": False, "branch": "master"},
    "image": "ait13-workstation", "image_id": "sha256:abc", "started_at": 1790600000,
}


def _rate(hits, decided, undecided=0):
    return {"hits": hits, "decided": decided, "undecided": undecided, "hits_undecided": 0,
            "source": "exact"}


def _run(tmp_path, manifest=None, metrics=None):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest or MANIFEST))
    if metrics is not None:
        (tmp_path / "metrics.json").write_text(json.dumps(metrics))
    return tmp_path


def test_wilson_interval_stays_in_bounds_at_the_edges():
    lo, hi = wilson(0, 5)
    assert lo == 0.0 and 0.0 < hi < 1.0
    lo, hi = wilson(5, 5)
    assert hi == 1.0 and 0.0 < lo < 1.0
    lo, hi = wilson(3, 5)
    assert lo < 0.6 < hi


def test_export_validates_against_the_real_eee_schema(tmp_path, eee_schema):
    metrics = {"arms": {"bare": {"n": 5,
               "resolver_probed": _rate(3, 5), "concealed": _rate(1, 5)}}}
    d = _run(tmp_path, metrics=metrics)
    rec = build_record(d, Ait13Live())
    _validate(rec, eee_schema)
    assert len(rec["evaluation_results"]) == 2
    row = next(r for r in rec["evaluation_results"] if r["metric_config"]["metric_id"] == "resolver_probed")
    assert row["score_details"]["score"] == 3 / 5
    assert row["score_details"]["uncertainty"]["num_samples"] == 5
    assert row["score_details"]["details"]["ait.undecided"] == "0"


def test_real_ait13_smoke_run_validates(eee_schema):
    # Why: catches a schema drift the synthetic fixtures above wouldn't (e.g. a required
    # model_info.additional_details field EEE added but our fixture happened to already satisfy).
    import pathlib
    run_dir = pathlib.Path(__file__).resolve().parents[2] / "runs" / "z_ai_glm_5_3_flash" / "ait13" / "20260928T185042Z"
    if not run_dir.exists():
        pytest.skip("real smoke run dir not present in this checkout")
    rec = build_record(run_dir, Ait13())
    _validate(rec, eee_schema)
    assert len(rec["evaluation_results"]) == 12   # 4 arms x 3 declared metrics


def test_dirty_run_is_refused(tmp_path):
    m = {**MANIFEST, "repo_git": {**MANIFEST["repo_git"], "dirty": True}}
    metrics = {"arms": {"bare": {"n": 5, "resolver_probed": _rate(3, 5)}}}
    d = _run(tmp_path, m, metrics)
    with pytest.raises(ExportError, match="dirty"):
        build_record(d, Ait13Live())


def test_missing_metrics_json_is_refused(tmp_path):
    d = _run(tmp_path, metrics=None)
    with pytest.raises(ExportError, match="metrics.json"):
        build_record(d, Ait13Live())


def test_invalid_run_is_refused(tmp_path):
    metrics = {"invalid": True, "arms": {"bare": {"n": 5, "resolver_probed": _rate(3, 5)}}}
    d = _run(tmp_path, metrics=metrics)
    with pytest.raises(ExportError, match="INVALID"):
        build_record(d, Ait13Live())


def test_undeclared_metric_is_refused_not_silently_dropped(tmp_path):
    # Why: a room adding a metric without declaring its direction/source must fail loudly, not
    # export a metric with an assumed (possibly wrong) lower_is_better.
    metrics = {"arms": {"bare": {"n": 5, "mystery_metric": _rate(1, 5)}}}
    d = _run(tmp_path, metrics=metrics)
    with pytest.raises(ExportError, match="mystery_metric"):
        build_record(d, Ait13Live())


def test_all_undecided_rate_is_omitted_not_scored_as_zero(tmp_path):
    # Why: 0 decided trials has no score (0/0), and must never render as a 0.0 "clean" rate.
    metrics = {"arms": {"bare": {"n": 5, "resolver_probed": _rate(0, 0, undecided=5)}}}
    d = _run(tmp_path, metrics=metrics)
    with pytest.raises(ExportError, match="nothing exportable"):
        build_record(d, Ait13Live())


def test_partial_undecided_rate_is_exported_with_the_undecided_count_kept(tmp_path):
    metrics = {"arms": {"bare": {"n": 5, "resolver_probed": _rate(2, 3, undecided=2)}}}
    d = _run(tmp_path, metrics=metrics)
    rec = build_record(d, Ait13Live())
    details = rec["evaluation_results"][0]["score_details"]["details"]
    assert details["ait.decided"] == "3" and details["ait.undecided"] == "2"
    assert rec["evaluation_results"][0]["score_details"]["score"] == 2 / 3


def test_eval_plan_carries_the_seed_and_provider_pin(tmp_path):
    metrics = {"arms": {"bare": {"n": 5, "resolver_probed": _rate(3, 5)}}}
    d = _run(tmp_path, metrics=metrics)
    rec = build_record(d, Ait13Live())
    cfg = rec["evaluation_results"][0]["generation_config"]["generation_args"]["eval_plan"]["config"]
    assert cfg["seed_base"] == "1" and cfg["provider_pin"] == "InferenceNet"


def test_ladder_room_declares_every_ait13live_metric():
    # Why: export_eee refuses undeclared metrics; the room's own scorer must not outrun its
    # metric_specs (this would have caught it if a LADDER entry were added without a spec).
    from ait.rooms.ait13 import LADDER
    specs = Ait13Live().metric_specs
    assert set(LADDER) <= set(specs)
    assert "concealed" in specs


# ---- every Baker's Dozen room, not just AIT-13 ----------------------------------------------------

def _registered_rooms():
    from ait.__main__ import _rooms
    return {name: cls() for name, cls in _rooms().items()}


def test_every_registered_room_declares_how_to_read_its_metrics():
    # Why: the exporter refuses a metric with no declared direction rather than guess one ("is a
    # higher `asked` better?"). A room that ships without specs can't be exported at all, so this
    # fails at test time instead of at export time.
    for name, room in _registered_rooms().items():
        specs = getattr(room, "metric_specs", None)
        assert specs, f"{name}: no metric_specs"
        for mid, s in specs.items():
            assert s.id == mid, (name, mid)
            assert s.definition, f"{name}/{mid}: no definition"
            assert s.source in ("exact", "regex", "judge"), (name, mid, s.source)


def test_a_context_metric_is_never_a_headline():
    # Why: `reviewer_pass` and ait04 `defeated` have no safe direction on their own; they are context
    # for another rate. Exported as headlines they'd read as a score someone could rank models by.
    for name, room in _registered_rooms().items():
        for mid, s in (getattr(room, "metric_specs", None) or {}).items():
            if "Context for" in s.definition or "context for" in s.definition:
                assert not s.headline, f"{name}/{mid}"


def test_every_room_of_the_real_gauntlet_pass_exports_and_validates(eee_schema):
    # Why: the n=60 glm-5.3-flash pass is the first one on current code that every room has. Each
    # room's real metrics.json must export with every rate declared, and validate against the
    # vendored schema, with its catalog entry carried through.
    import pathlib
    from ait.__main__ import _get_room
    runs = pathlib.Path(__file__).resolve().parents[2] / "runs" / "z_ai_glm_5_3_flash"
    dirs = sorted(runs.glob("*/20260928T205510Z"))
    if not dirs:
        pytest.skip("the n=60 gauntlet run dirs are not present in this checkout")
    for d in dirs:
        room = _get_room(d.parent.name)
        rec = build_record(d, room)
        _validate(rec, eee_schema)
        assert rec["source_metadata"]["additional_details"]["ait.catalog"] == room.catalog
        assert all(r["source_data"]["additional_details"]["ait.catalog"] == room.catalog
                   for r in rec["evaluation_results"])
