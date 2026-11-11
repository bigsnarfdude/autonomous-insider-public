"""`anthropic/<id>` models: the Provider routes them to the Anthropic API, and the records stay
comparable with the OpenRouter path. No network: the SDK client is replaced with a fake."""
from pathlib import Path

import pytest

import ait.core.provider as P
from ait.core.judge import BlindJudge, JudgeSpec
from ait.core.provider import (CallResult, Provider, ProviderConfig, parse_anthropic, probe_pin,
                               to_anthropic_messages)
from ait.tests.anthropic_fake import FakeAPI, api_error, message


def _msg(text="ok", stop="end_turn", model="claude-opus-5-5", thinking="", inp=100, out=50):
    """A final Message as the SDK builds it from a stream (for parse_anthropic on its own)."""
    return FakeAPI(message(text, stop=stop, model=model, thinking=thinking, inp=inp, out=out)) \
        .client().messages.stream(model=model, max_tokens=10, messages=[]).__enter__().get_final_message()


def _provider(monkeypatch, *replies, **cfg):
    api = FakeAPI(*replies).install(monkeypatch)
    return Provider(ProviderConfig(model="anthropic/claude-opus-5-5", **cfg), api_key="sk-ant-test"), api


def test_routes_to_anthropic_and_sends_no_sampling_params(monkeypatch):
    # current Claude models 400 on temperature/top_p; sending them would make every call fail
    p, api = _provider(monkeypatch)
    res = p.chat([{"role": "user", "content": "hi"}], seed=7)
    assert res.ok and res.content == "ok" and res.served_provider == "anthropic"
    kw = api.requests[0]
    assert kw["model"] == "claude-opus-5-5"
    for k in ("temperature", "top_p", "seed"):
        assert k not in kw
    assert kw["thinking"]["type"] == "adaptive"
    assert kw["output_config"]["effort"] == "high"
    # the record says the seed was NOT sent, so nobody reads it as reproducible
    assert res.request["seed"] == 7 and res.request["seed_sent"] is False


def test_no_server_side_fallback(monkeypatch):
    # a fallback would let a different model answer mid-run: the backend-drift confound the pin
    # exists to stop. The request must not ask for one.
    p, api = _provider(monkeypatch)
    p.chat([{"role": "user", "content": "hi"}], seed=1)
    assert "fallbacks" not in api.requests[0] and "betas" not in api.requests[0]


def test_refusal_is_data_not_an_error(monkeypatch):
    # a decline is the model's behaviour; it must reach the room as an outcome, with its category.
    # Through the SDK's real stream: its accumulator drops stop_details from the final message, so
    # a fake that hands over a finished Message passed while every real refusal came back None
    p, _ = _provider(monkeypatch, message("", stop="refusal",
                                          stop_details={"type": "refusal", "category": "cyber"}))
    res = p.chat([{"role": "user", "content": "x"}], seed=1)
    assert res.ok and res.finish_reason == "refusal" and res.refusal_category == "cyber"


def test_bad_request_is_not_retried(monkeypatch):
    # the same 400 comes back every time; 8 tries would only burn time and credits
    p, api = _provider(monkeypatch, api_error(400, "invalid_request_error"), tries=8)
    res = p.chat([{"role": "user", "content": "x"}], seed=1, sleep=lambda s: None)
    assert not res.ok and res.error.startswith("NoRetry") and len(api.requests) == 1


def test_transient_error_is_retried(monkeypatch):
    p, api = _provider(monkeypatch, api_error(529, "overloaded_error"), tries=3)
    res = p.chat([{"role": "user", "content": "x"}], seed=1, sleep=lambda s: None)
    assert not res.ok and len(api.requests) == 3


def test_message_conversion():
    sys, msgs, dropped = to_anthropic_messages([
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": ""},          # a prior empty reply: the API rejects it
        {"role": "user", "content": "q2"},
    ])
    assert sys == "rules" and dropped == 1
    assert msgs == [{"role": "user", "content": "q1"}, {"role": "user", "content": "q2"}]


def test_cost_from_tokens_and_reasoning_is_summary(monkeypatch):
    text, reasoning, meta = parse_anthropic(_msg(thinking="plan", inp=1_000_000, out=1_000_000))
    assert reasoning == "plan"
    assert meta["usage"]["cost"] == pytest.approx(24.0)      # $4 in + $20 out per MTok
    p, _ = _provider(monkeypatch, message(thinking="plan"))
    res = p.chat([{"role": "user", "content": "x"}], seed=1)
    assert res.reasoning == "plan" and res.request["reasoning_kind"] == "summary"   # never raw CoT


def test_unknown_model_price_is_flagged_not_guessed():
    _, _, meta = parse_anthropic(_msg(model="claude-new-9"))
    assert meta["usage"]["cost"] == 0.0 and meta["usage"]["priced"] is False


def test_probe_pin_makes_no_call_for_anthropic(monkeypatch):
    monkeypatch.setattr(Provider, "chat", lambda *a, **k: pytest.fail("probe made a call"))
    cfg = probe_pin(ProviderConfig(model="anthropic/claude-opus-5-5"))
    assert cfg.order == ("anthropic",) and cfg.allow_fallbacks is False


def test_key_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(P.Path, "home", lambda: tmp_path)
    with pytest.raises(RuntimeError):
        Provider(ProviderConfig(model="anthropic/claude-opus-5-5"))
    (tmp_path / "anthropic.key").write_text("sk-ant-file\n")
    # a room hands the run's OpenRouter key through; for an Anthropic model it must not be used
    p = Provider(ProviderConfig(model="anthropic/claude-opus-5-5"), api_key="sk-or-openrouter")
    assert p.api_key == "sk-ant-file"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    assert Provider(ProviderConfig(model="anthropic/claude-opus-5-5")).api_key == "sk-ant-env"


def test_openrouter_path_unchanged():
    p = Provider(ProviderConfig(model="z-ai/glm-5.2"), api_key="sk-or-x")
    assert not p.anthropic and p.api_key == "sk-or-x"


# ---- the judge -------------------------------------------------------------------------------------
def _spec():
    return JudgeSpec(name="t", rubric="label it", keys=["v"], enums={"v": {"a", "b"}},
                     render=lambda row, stats: "row")


def test_api_judge_tag_never_mixes_with_claude_p():
    # judge files resume by tag: an API-judged file must never be continued by `claude -p`
    api = BlindJudge(_spec(), model="anthropic/claude-opus-5-5")
    cli = BlindJudge(_spec(), model="opus")
    assert "via anthropic api" in api.tag and api.tag != cli.tag


def test_api_judge_refusal_is_a_decline(monkeypatch):
    def fake_chat(self, messages, *, seed, **kw):
        assert messages[0]["role"] == "system"          # same system prompt as the claude -p judge
        return CallResult(ok=True, finish_reason="refusal", refusal_category="cyber")
    monkeypatch.setattr(Provider, "chat", fake_chat)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    bj = BlindJudge(_spec(), model="anthropic/claude-opus-5-5")
    out = bj._one_sample("prompt")
    assert out.get("_declined") is True


def test_api_judge_parses_a_verdict(monkeypatch):
    monkeypatch.setattr(Provider, "chat",
                        lambda self, m, *, seed, **kw: CallResult(ok=True, content='{"v": "a"}'))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert BlindJudge(_spec(), model="anthropic/claude-opus-5-5")._one_sample("p") == {"v": "a"}


def test_cot_judge_routes_bare_claude_names_to_claude_p():
    # a bare model name must reach the isolated `claude -p` judge, never OpenRouter (which 404s on it)
    src = (Path(__file__).resolve().parents[1] / "__main__.py").read_text()
    assert 'backend = "openrouter" if "/" in a.model else "claude"' in src
    assert BlindJudge(_spec(), model="claude-opus-4-8", backend="claude").tag.endswith("via claude -p (isolated)")
