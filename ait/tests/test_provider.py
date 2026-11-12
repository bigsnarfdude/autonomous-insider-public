"""Provider concurrency: the process-wide in-flight cap (the shared rate budget for parallel rooms)."""
import threading
import time

from ait.core import provider
from ait.core.provider import Meter, Provider, ProviderConfig


def _counting_post(live, lock, hold=0.03):
    def fake(self, body):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(hold)
        with lock:
            live["now"] -= 1
        return ("ok", "", {"usage": None})
    return fake


def _hammer(n_threads):
    p = Provider(ProviderConfig(model="m", tries=1), api_key="k", meter=Meter())
    ts = [threading.Thread(target=lambda i=i: p.chat([{"role": "user", "content": "x"}], seed=i))
          for i in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def test_inflight_limit_bounds_concurrent_calls(monkeypatch):
    live = {"now": 0, "peak": 0}
    monkeypatch.setattr(Provider, "_post", _counting_post(live, threading.Lock()))
    provider.set_inflight_limit(2)
    try:
        _hammer(8)
    finally:
        provider.set_inflight_limit(None)
    assert live["peak"] <= 2 and live["peak"] >= 1     # never more than the cap in flight at once


def test_no_limit_lets_calls_overlap_past_the_cap(monkeypatch):
    # the contrast: without the cap, 8 threads DO overlap beyond 2 — so it's the semaphore doing the
    # bounding above, not thread scheduling that happened to serialize.
    live = {"now": 0, "peak": 0}
    monkeypatch.setattr(Provider, "_post", _counting_post(live, threading.Lock()))
    provider.set_inflight_limit(None)
    _hammer(8)
    assert live["peak"] > 2


# ---- review 2026-11-12 ---------------------------------------------------------------------------

def test_auth_and_billing_errors_are_not_retried(monkeypatch):
    # Why: a 401 or 402 took all the tries with backoff, minutes per call, for an error the same
    # request will hit again. The Anthropic path already stopped; this one did not.
    from ait.core.provider import NoRetry
    calls = {"n": 0}

    def post(self, body):
        calls["n"] += 1
        raise NoRetry("HTTP 401: Unauthorized")
    monkeypatch.setattr(Provider, "_post", post)
    p = Provider(ProviderConfig(model="m", tries=8), api_key="k", meter=Meter())
    r = p.chat([{"role": "user", "content": "x"}], seed=1, sleep=lambda s: None)
    assert not r.ok and calls["n"] == 1 and r.attempts == 1 and "401" in r.error


def test_a_server_error_is_still_retried(monkeypatch):
    calls = {"n": 0}

    def post(self, body):
        calls["n"] += 1
        raise RuntimeError("HTTP 503")
    monkeypatch.setattr(Provider, "_post", post)
    p = Provider(ProviderConfig(model="m", tries=3), api_key="k", meter=Meter())
    r = p.chat([{"role": "user", "content": "x"}], seed=1, sleep=lambda s: None)
    assert not r.ok and calls["n"] == 3 and r.attempts == 3
