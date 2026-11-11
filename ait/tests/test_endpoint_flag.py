"""--endpoint: a non-OpenRouter target is not pinned, and its key never reaches OpenRouter's judge."""
import argparse

import pytest

from ait import __main__ as cli
from ait.core.provider import DEFAULT_ENDPOINT

OTHER = "https://example.invalid/openai/v1/chat/completions"


def _args(**kw):
    base = dict(model="some-model", provider=None, allow_fallbacks=False, max_tokens=1024,
                no_pin=False, endpoint=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_custom_endpoint_skips_the_pin_probe(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("probe_pin must not be called for a non-OpenRouter endpoint")
    monkeypatch.setattr(cli, "probe_pin", boom)
    cfg, usage = cli._config(_args(endpoint=OTHER))
    assert cfg.endpoint == OTHER and cfg.order == () and usage == {}


def test_default_endpoint_is_unchanged_when_flag_absent(monkeypatch):
    monkeypatch.setattr(cli, "probe_pin", lambda cfg, meter=None: cfg)
    cfg, _ = cli._config(_args(no_pin=True))
    assert cfg.endpoint == DEFAULT_ENDPOINT


def test_custom_endpoint_refuses_an_openrouter_second_judge():
    with pytest.raises(SystemExit) as e:
        cli._preflight(_args(endpoint=OTHER, judge2="google/gemini-3.8-flash", no_judge=False,
                             judge_model="sonnet"), judges=True)
    assert "openrouter.ai" in str(e.value)


@pytest.mark.parametrize("kw", [dict(no_judge=True, judge2="google/gemini-3.8-flash"),
                                dict(no_judge=False, judge2="none")])
def test_custom_endpoint_allowed_without_the_second_judge(kw):
    cli._preflight(_args(endpoint=OTHER, judge_model="sonnet", **kw), judges=False)
