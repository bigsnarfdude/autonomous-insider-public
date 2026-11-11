"""Review fixes for the Anthropic backend (2026-10-05, 2026-10-06). Through the real SDK over a fake
transport (anthropic_fake), so the SDK's own stream handling and error classes are exercised."""
import json
import sys
import types

import pytest

import ait.core.provider as P
from ait.core.judge import BlindJudge, JudgeSpec
from ait.core.provider import (ANTHROPIC_MIN_TOKENS, CallResult, Provider, ProviderConfig, key_for,
                               parse_anthropic)
from ait.tests.anthropic_fake import FakeAPI, api_error, message, midstream_error

HI = [{"role": "user", "content": "hi"}]


def _prov(monkeypatch, *replies, model="anthropic/claude-opus-5-5", **cfg):
    api = FakeAPI(*replies).install(monkeypatch)
    return Provider(ProviderConfig(model=model, **cfg), api_key="sk-ant-test"), api


def _no_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)          # import anthropic -> ImportError


# ---- keys never cross backends ---------------------------------------------------------------------
def test_an_anthropic_key_is_never_sent_to_openrouter():
    # Why: on an anthropic/ run, ait11's GLM reviewer was built with the run's key — the sk-ant key —
    # and the OpenRouter path sent it to openrouter.ai as a Bearer token.
    with pytest.raises(RuntimeError, match="refusing to send it"):
        Provider(ProviderConfig(model="z-ai/glm-5.3-flash"), api_key="sk-ant-secret")
    run = types.SimpleNamespace(api_key="sk-ant-secret",
                                config=ProviderConfig(model="anthropic/claude-opus-5-5"))
    assert key_for(run, "z-ai/glm-5.3-flash") is None                   # resolve OpenRouter's own
    assert key_for(run, "anthropic/claude-haiku-4-5") == "sk-ant-secret"
    glm = types.SimpleNamespace(api_key="sk-or-x", config=ProviderConfig(model="z-ai/glm-5.2"))
    assert key_for(glm, "z-ai/glm-5.3-flash") == "sk-or-x"               # same backend: passed on


def test_ait11_reviewer_on_an_anthropic_run_gets_no_anthropic_key(monkeypatch):
    import ait.rooms.ait11 as M
    seen = {}

    class FakeProvider:
        def __init__(self, cfg, api_key=None, meter=None): seen["key"] = api_key
        def chat(self, msgs, *, seed): return CallResult(ok=False, error="x")
    monkeypatch.setattr(M, "Provider", FakeProvider)
    ctx = types.SimpleNamespace(arm="J1", seed=1, provider=types.SimpleNamespace(
        api_key="sk-ant-secret", config=ProviderConfig(model="anthropic/claude-opus-5-5"), meter=None))
    M.Ait11()._review(ctx, {"ledger": [{"turn": 0, "cmd": "ls", "out": ""}], "end": {}})
    assert seen["key"] is None


def test_ait02_refuses_an_anthropic_model_before_starting_its_container(monkeypatch):
    # Why: ait02's harness calls OpenRouter from inside docker with OPENROUTER_API_KEY set to the
    # run's key — on an anthropic/ run, the Anthropic key.
    import ait.rooms.ait02 as M
    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: pytest.fail("container started"))
    ctx = types.SimpleNamespace(arm="missing", seed=1, provider=types.SimpleNamespace(
        api_key="sk-ant-secret", config=ProviderConfig(model="anthropic/claude-opus-5-5")))
    with pytest.raises(RuntimeError, match="OpenRouter"):
        M.Ait02().run_trial(ctx)


# ---- everything an anthropic/ model needs is checked once, at the start ----------------------------
def test_a_missing_sdk_stops_the_provider_from_being_built(monkeypatch):
    # Why: checked per call, a missing SDK turned every trial into a quiet call_failed that a resume
    # then kept (only harness_error is rerun), and the pass exited 0.
    _no_sdk(monkeypatch)
    with pytest.raises(RuntimeError, match="pip install anthropic"):
        Provider(ProviderConfig(model="anthropic/claude-opus-5-5"), api_key="sk-ant-test")


def test_a_broken_sdk_says_why_not_pip_install(monkeypatch):
    # Why: an installed SDK whose own import fails was reported as "pip install anthropic", which
    # pip answers with "already satisfied".
    real_import = __import__

    def fake_import(name, *a, **k):
        if name == "anthropic":
            raise ImportError("No module named 'jiter'", name="jiter")
        return real_import(name, *a, **k)
    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError, match="jiter") as e:
        P.require_anthropic_sdk()
    assert "pip install" not in str(e.value)


def test_gauntlet_resume_checks_the_sdk_before_running_anything(tmp_path, monkeypatch):
    # Why: --resume rebuilt the config without the start-of-run check, so the gap above was open there.
    import ait.__main__ as cli
    from ait.tests.test_gauntlet import FakeRoom
    monkeypatch.setattr(cli, "_rooms", lambda: {"good": FakeRoom})
    monkeypatch.setattr(cli, "Runner", lambda *a, **k: pytest.fail("a room ran"))
    card = tmp_path / "card"
    card.mkdir()
    (card / "state.json").write_text(json.dumps({"stamp": "s", "pin": ["anthropic"], "rooms": {}, "args": {
        "model": "anthropic/claude-opus-5-5", "n": 1, "seed": 0, "max_tokens": 8192, "judge_model": None,
        "judge_samples": 1, "judge2": "none", "no_judge": True, "rooms": ["good"],
        "allow_fallbacks": False, "out": str(tmp_path / "runs")}}))
    _no_sdk(monkeypatch)
    with pytest.raises(SystemExit, match="pip install anthropic"):
        cli.main(["gauntlet", "--resume", str(card)])


def test_an_api_judge_checks_the_sdk_when_built(monkeypatch):
    # Why: `ait judge` / `cot-judge` with an anthropic/ judge never ran the check; each row retried
    # the failure 3 times with 4 s sleeps and was filed _unparsed.
    _no_sdk(monkeypatch)
    spec = JudgeSpec(name="t", rubric="r", keys=["v"], enums={"v": {"a"}}, render=lambda r, s: "")
    with pytest.raises(RuntimeError, match="pip install anthropic"):
        BlindJudge(spec, model="anthropic/claude-opus-5-5")


@pytest.mark.parametrize("model", ["anthropic/claude-sonnet-4-5", "anthropic/claude-opus-4-5"])
def test_a_model_whose_request_surface_is_unknown_is_refused(model):
    # Why: Sonnet 4.5 / Opus 4.5 take no adaptive thinking; sending it 400s every call, and every trial
    # ends call_failed. Refused up front instead, naming the table to extend.
    with pytest.raises(RuntimeError, match="ANTHROPIC_MODELS"):
        Provider(ProviderConfig(model=model), api_key="sk-ant-test")


def test_a_budget_over_the_models_output_limit_is_refused():
    # Haiku 4.5 takes at most 64000 output tokens: --max-tokens 128000 would 400 on every call
    with pytest.raises(RuntimeError, match="64000"):
        Provider(ProviderConfig(model="anthropic/claude-haiku-4-5", max_tokens=128000), api_key="sk-ant-test")


def test_environment_credentials_cannot_redirect_or_ride_along(monkeypatch):
    # Why: the SDK reads ANTHROPIC_BASE_URL even when given api_key (calls silently go to another
    # host while the record says "anthropic-api"), and ANTHROPIC_AUTH_TOKEN adds a second credential.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example")
    p = Provider(ProviderConfig(model="anthropic/claude-opus-5-5"), api_key="sk-ant-test")
    assert str(p._anthropic_client().base_url).rstrip("/") == P.ANTHROPIC_BASE_URL
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    with pytest.raises(RuntimeError, match="ANTHROPIC_AUTH_TOKEN"):
        Provider(ProviderConfig(model="anthropic/claude-opus-5-5"), api_key="sk-ant-test")


def test_a_client_that_cannot_be_built_is_not_retried(monkeypatch):
    # Why: a constructor error (an httpx/pydantic mismatch) was retried 8 times with ~205 s of backoff.
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda **k: (_ for _ in ()).throw(TypeError("proxies")))
    slept = []
    res = Provider(ProviderConfig(model="anthropic/claude-opus-5-5"), api_key="sk-ant-test") \
        .chat(HI, seed=1, sleep=slept.append)
    assert not res.ok and res.attempts == 1 and slept == [] and "proxies" in res.error


# ---- what a reply means ----------------------------------------------------------------------------
def test_a_capped_reply_is_reported_as_length(monkeypatch):
    # Why: Anthropic says "max_tokens" where OpenRouter says "length", and the rooms' truncation guards
    # test for "length": an ait03 leader that thought through its budget was scored as a decision.
    p, _ = _prov(monkeypatch, message("", stop="max_tokens"))
    assert p.chat(HI, seed=1).finish_reason == "length"
    p, _ = _prov(monkeypatch, message("", stop="refusal"))
    assert p.chat(HI, seed=1).finish_reason == "refusal"                  # a refusal is not a truncation


def test_ait03_counts_a_capped_anthropic_turn_as_truncated(monkeypatch):
    # the room's own loop, fed by a real Provider: an empty capped turn is a cut-off, not a decision
    import ait.rooms.ait03 as M
    p, _ = _prov(monkeypatch, message("", stop="max_tokens"))

    class FakeBox:
        def root_exec(self, cmd):
            if cmd.startswith("stat"):
                return types.SimpleNamespace(returncode=0, stdout="1|444|1000|1|4|0|0|Jan  1  1970|Jan  1  1970")
            return types.SimpleNamespace(returncode=0, stdout="deadbeef  x")
    ctx = types.SimpleNamespace(seed=1, provider=p)
    truncated = M.Ait03()._turnset(FakeBox(), ctx, "agent1", "sys", "task", 1, False)[3]
    assert truncated == 1


def test_a_stream_cut_short_is_retried_not_returned_as_an_answer(monkeypatch):
    # Why: a body that ended cleanly mid-generation came back ok=True with half a reply, which a room
    # parses as the model's action (a truncated CMD: line).
    p, api = _prov(monkeypatch, message("CMD: rm -r /work/da", cut=True), message("DONE"), tries=3)
    res = p.chat(HI, seed=1, sleep=lambda s: None)
    assert res.ok and res.content == "DONE" and len(api.requests) == 2


@pytest.mark.parametrize("reply,retried", [
    (api_error(402, "billing_error"), False),                                     # out of credit
    (api_error(429, "rate_limit_error", error_code="enforced_spend_limit_reached"), False),
    (midstream_error("invalid_request_error"), False),                             # arrives as a 200
    (api_error(429, "rate_limit_error"), True),
    (midstream_error("overloaded_error"), True),
])
def test_retry_is_decided_by_the_error_type(monkeypatch, reply, retried):
    # Why: classified by HTTP status alone, an exhausted credit balance or spend cap was retried 8
    # times (~205 s per call, hours across a gauntlet), and a mid-stream error carried status 200.
    p, api = _prov(monkeypatch, reply, tries=3)
    res = p.chat(HI, seed=1, sleep=lambda s: None)
    assert not res.ok and len(api.requests) == (3 if retried else 1)


# ---- budgets, and what the record says was sent ----------------------------------------------------
def test_max_tokens_has_room_for_thinking(monkeypatch):
    # Why: thinking counts against max_tokens; at the run's 8192 a long think ends at the cap with no
    # answer (the GLM n=60 truncation). Streamed, so a high floor costs nothing unless used.
    p, api = _prov(monkeypatch, max_tokens=8192)
    res = p.chat(HI, seed=1)
    assert api.requests[0]["max_tokens"] == ANTHROPIC_MIN_TOKENS >= 32000
    assert res.request["max_tokens"] == ANTHROPIC_MIN_TOKENS          # the record says what was sent
    p, api = _prov(monkeypatch, max_tokens=64000)
    p.chat(HI, seed=1)
    assert api.requests[0]["max_tokens"] == 64000                       # never lowered


def test_haiku_thinking_budget_follows_the_requested_effort(monkeypatch):
    # Why: Haiku takes no effort (400), and the effort was dropped for a fixed max_tokens//2, so runs
    # tagged effort=low and effort=high sent byte-identical requests.
    sent = {}
    for effort in ("low", "high"):
        p, api = _prov(monkeypatch, message(model="claude-haiku-4-5-20251001"),
                       model="anthropic/claude-haiku-4-5", reasoning_effort=effort)
        res = p.chat(HI, seed=1)
        kw = api.requests[0]
        assert kw["thinking"]["type"] == "enabled" and "output_config" not in kw
        assert 1024 <= kw["thinking"]["budget_tokens"] < kw["max_tokens"]
        assert res.request["thinking_budget"] == kw["thinking"]["budget_tokens"]
        assert res.request["reasoning_effort"] == effort and res.request["effort_sent"] is False
        sent[effort] = kw["thinking"]["budget_tokens"]
    assert sent["low"] < sent["high"]
    with pytest.raises(RuntimeError, match="reasoning_effort"):
        Provider(ProviderConfig(model="anthropic/claude-haiku-4-5", reasoning_effort="extreme"),
                 api_key="sk-ant-test")


def test_adaptive_models_send_the_effort(monkeypatch):
    p, api = _prov(monkeypatch, reasoning_effort="low")
    res = p.chat(HI, seed=1)
    assert api.requests[0]["thinking"]["type"] == "adaptive"
    assert api.requests[0]["output_config"] == {"effort": "low"} and res.request["effort_sent"] is True


def test_a_dated_snapshot_is_priced(monkeypatch):
    # Why: the API echoes the snapshot id (claude-haiku-4-5-20251001), and the price lookup was by
    # exact name, so a whole Haiku run cost "$0.00" with no warning.
    p, _ = _prov(monkeypatch, message(model="claude-haiku-4-5-20251001", inp=1_000_000, out=1_000_000),
                 model="anthropic/claude-haiku-4-5")
    usage = p.chat(HI, seed=1).usage
    assert usage["priced"] is True and usage["cost"] == pytest.approx(6.0)     # $1 in + $5 out
    assert P.anthropic_model("claude-haiku-4-5-2025") is None                 # not a date: no match


@pytest.mark.parametrize("details", [{"type": "refusal", "category": "cyber"},
                                     types.SimpleNamespace(type="refusal", category="cyber")])
def test_refusal_category_read_from_a_dict_or_an_object(details):
    # an SDK that predates stop_details keeps it as a plain dict; getattr() on a dict gave None
    msg = types.SimpleNamespace(content=[], stop_reason="refusal", model="claude-opus-5-5", id="m",
                                usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
    assert parse_anthropic(msg, details)[2]["refusal_category"] == "cyber"


def test_ait11_records_the_budget_its_calls_sent(monkeypatch):
    # Why: ait11 recorded its own max(run, 24576) per agent while the provider sent 32000 underneath,
    # so the only per-trial record of the subject's budget was wrong.
    import ait.rooms.ait11 as M
    FakeAPI(message("DONE")).install(monkeypatch)

    class FakeBox:
        def root_exec(self, cmd):
            if cmd.startswith("stat"):
                return types.SimpleNamespace(returncode=0, stdout="1|444|1000|1|4|0|0|Jan  1  1970|Jan  1  1970")
            return types.SimpleNamespace(returncode=0, stdout="deadbeef  x")
        def exec(self, *a, **k): return types.SimpleNamespace(out="", exit=0)
    ctx = types.SimpleNamespace(arm="J1", seed=1, provider=types.SimpleNamespace(
        api_key="sk-ant-test", meter=None,
        config=ProviderConfig(model="anthropic/claude-opus-5-5", order=("anthropic",), max_tokens=8192)))
    out = M.Ait11()._run_agent(FakeBox(), ctx, "agent1", "run0")
    assert out["subject_max_tokens"] == 32000 and out["calls"][0]["max_tokens"] == 32000


# ---- the judge -------------------------------------------------------------------------------------
def _spec():
    return JudgeSpec(name="t", rubric="label it", keys=["v"], enums={"v": {"a", "b"}},
                     render=lambda row, stats: "row")


def test_api_judge_tag_carries_its_budget():
    # Why: the judge's budget doubled (16000 -> 32000) under an unchanged tag, so a judge file begun
    # before resumed after, mixing rows judged at two budgets.
    assert BlindJudge(_spec(), model="anthropic/claude-opus-5-5").tag.endswith("(max_tokens 32000)")
    assert BlindJudge(_spec(), model="anthropic/claude-opus-5-5", max_tokens=64000).tag \
        != BlindJudge(_spec(), model="anthropic/claude-opus-5-5").tag


def test_api_judge_does_not_retry_what_the_provider_gave_up_on(monkeypatch):
    # Why: the provider's 8 tries ran inside the judge's 3, ~11 min per sample in an outage
    calls = []
    monkeypatch.setattr(Provider, "chat", lambda self, m, *, seed, **kw:
                        calls.append(1) or CallResult(ok=False, error="APIConnectionError: down"))
    monkeypatch.setattr("ait.core.judge.time.sleep", lambda s: pytest.fail("slept"))
    out = BlindJudge(_spec(), model="anthropic/claude-opus-5-5")._one_sample("p")
    assert "_unparsed" in out and len(calls) == 1
