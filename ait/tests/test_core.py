"""Core-framework tests. No network, no docker — pure logic.

They pin the reproducibility guarantees the rooms lacked: a call records what served it and
never silently returns empty; the decided gate keeps undecided trials out of denominators;
seeds are deterministic; manifests diff on what makes runs incomparable.
"""
import json
from pathlib import Path

import pytest

from ait.core import gate
from ait.core.manifest import Manifest, hash_paths
from ait.core.provider import CallResult, Provider, ProviderConfig
from ait.core.runner import trial_seed
from ait.core.sandbox import Ledger, ExecResult


# ---- provider: pinning + full record, no silent empty ----------------------

def test_provider_sends_seed_and_pin():
    cfg = ProviderConfig(model="m", order=("fireworks",), allow_fallbacks=False)
    captured = {}

    def fake_post(body):
        captured.update(body)
        return "hi", "because", {"finish_reason": "stop", "model": "m",
                                 "provider": "Fireworks", "id": "gen-1",
                                 "usage": {"total_tokens": 3}}

    p = Provider(cfg, api_key="k")
    p._post = fake_post
    r = p.chat([{"role": "user", "content": "x"}], seed=42, sleep=lambda s: None)
    assert r.ok
    assert captured["seed"] == 42
    assert captured["provider"] == {"allow_fallbacks": False, "order": ["fireworks"]}
    assert r.finish_reason == "stop"
    assert r.served_provider == "Fireworks"
    assert r.request["seed"] == 42


def test_provider_failure_is_explicit_not_empty():
    cfg = ProviderConfig(model="m", tries=3)

    def boom(body):
        raise RuntimeError("503")

    p = Provider(cfg, api_key="k")
    p._post = boom
    r = p.chat([{"role": "user", "content": "x"}], seed=1, sleep=lambda s: None)
    assert r.ok is False
    assert r.attempts == 3
    assert "503" in r.error
    # a caller can distinguish this from a model that chose to stop
    assert r.finish_reason is None and r.content == ""


def test_pin_with_no_order_and_fallbacks_is_omitted():
    cfg = ProviderConfig(model="m", allow_fallbacks=True)
    assert cfg.provider_block() is None


# ---- decided-trial gate ----------------------------------------------------

def test_undecided_stays_out_of_denominator():
    recs = [
        {"arm": "A", "trial": 0, "end_reason": "answer", "hacked": True},
        {"arm": "A", "trial": 1, "end_reason": "answer", "hacked": False},
        {"arm": "A", "trial": 2, "end_reason": "call_failed"},   # undecided
        {"arm": "A", "trial": 3, "end_reason": "maxsteps"},       # undecided
    ]
    r = gate.rate("hacked", recs, lambda x: x.get("hacked", False))
    assert r.hits == 1
    assert r.decided == 2
    assert r.undecided == 2
    assert "1/2 decided (2 undecided, 0 of them hit)" in str(r)


def test_one_step_limit_rule_and_post_change_cutoff_is_decided():
    # Why: rooms disagreed — ait02 called an out-of-steps trial honest_fail, ait09 kept it in the
    # denominator, ait12 excluded it. One rule now: the agent ran out of steps -> undecided; the
    # harness's own stop after the agent acted (post_change_cutoff) -> decided.
    for end in ("maxsteps", "step_budget", "trial_deadline", "call_failed", "sandbox_error"):
        assert not gate.agent_decided(end), end
    for end in ("done", "answer", "giveup", "post_change_cutoff", "model_stopped", "asked"):
        assert gate.agent_decided(end), end
    recs = [{"end_reason": "done", "x": True}, {"end_reason": "maxsteps", "x": True},
            {"end_reason": "maxsteps", "x": False}]
    r = gate.rate("x", recs, lambda z: z["x"])
    assert (r.hits, r.decided, r.undecided, r.hits_undecided) == (1, 1, 2, 1)


def test_explicit_decided_flag_wins():
    recs = [{"decided": False, "end_reason": "answer"},   # explicit override
            {"decided": True, "end_reason": "maxsteps"}]
    r = gate.rate("x", recs, lambda _: True)
    assert r.decided == 1 and r.undecided == 1


def test_empty_ledger_no_decision_is_undecided():
    assert gate.is_decided({"end_reason": None, "final_answer": None}) is False
    assert gate.is_decided({"end_reason": None, "final_answer": "7"}) is True


# ---- deterministic seeding -------------------------------------------------

def test_trial_seed_deterministic_and_arm_distinct():
    assert trial_seed(100, "P2", 3) == trial_seed(100, "P2", 3)
    assert trial_seed(100, "P2", 3) != trial_seed(100, "P3", 3)
    assert trial_seed(100, "P2", 3) != trial_seed(101, "P2", 3)


def test_trial_seed_stable_across_processes():
    # Why: the manifest promises a run is reproducible from its seed_base. builtin hash() of a str
    # is salted per process, so a seed built on it changed on every rerun of `ait run --seed N`.
    import subprocess, sys, os
    code = "from ait.core.runner import trial_seed; print(trial_seed(100, 'P2', 3))"
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                           env={**os.environ, "PYTHONHASHSEED": hs}).stdout.strip()
            for hs in ("1", "2", "3")}
    assert outs == {str(trial_seed(100, "P2", 3))}


# ---- ledger ----------------------------------------------------------------

def test_ledger_caps_output_and_records_exit():
    lg = Ledger(record_cap=10)
    e = lg.add(1, "cat big", ExecResult(out="x" * 100, exit=0))
    assert len(e["out"]) == 10
    assert e["exit"] == 0 and e["turn"] == 1
    assert lg.commands() == ["cat big"]


# ---- manifest --------------------------------------------------------------

def test_manifest_diff_flags_incomparable_fields(tmp_path):
    a = {"room": "ait12", "model": "m1", "seed_base": 1, "arms": ["P2"],
         "image_id": "sha1", "repo_git": {"commit": "aaa"}, "provider_config": {},
         "room_assets_hash": "h"}
    b = dict(a, model="m2", repo_git={"commit": "bbb"})
    d = Manifest.diff(a, b)
    assert d["model"] == ("m1", "m2")
    assert d["commit"] == ("aaa", "bbb")
    assert "arms" not in d


def test_hash_paths_stable(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    h1 = hash_paths([p])
    h2 = hash_paths([p])
    assert h1 == h2 and len(h1) == 16
