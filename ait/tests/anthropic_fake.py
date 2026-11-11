"""A fake Anthropic API for tests: the real SDK client over an httpx.MockTransport that serves SSE.

Fakes that hand the Provider a ready-made Message skip the SDK's stream accumulator, which is where
real bugs lived (it drops stop_details; a stream that ends early still yields a "final" message).
Everything here goes through the SDK as a live call would, with no network.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

anthropic = pytest.importorskip("anthropic")
httpx = pytest.importorskip("httpx")

from ait.core.provider import Provider  # noqa: E402


def _ev(data: dict[str, Any]) -> bytes:
    return f"event: {data['type']}\ndata: {json.dumps(data)}\n\n".encode()


def message(text: str = "ok", *, stop: str | None = "end_turn", model: str = "claude-opus-5-5",
            thinking: str = "", stop_details: dict | None = None, inp: int = 100, out: int = 50,
            cut: bool = False) -> list[bytes]:
    """The SSE events of one streamed reply. `cut`: the body ends before message_delta (a stream an
    intermediary closed cleanly mid-generation)."""
    evs = [_ev({"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": inp, "output_tokens": 1,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}})]
    i = 0
    if thinking:
        evs += [_ev({"type": "content_block_start", "index": i,
                     "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
                _ev({"type": "content_block_delta", "index": i,
                     "delta": {"type": "thinking_delta", "thinking": thinking}}),
                _ev({"type": "content_block_stop", "index": i})]
        i += 1
    evs += [_ev({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})]
    if text:
        evs += [_ev({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": text}})]
    if cut:
        return evs
    evs += [_ev({"type": "content_block_stop", "index": i}),
            _ev({"type": "message_delta",
                 "delta": {"stop_reason": stop, "stop_sequence": None, "stop_details": stop_details},
                 "usage": {"output_tokens": out}}),
            _ev({"type": "message_stop"})]
    return evs


def api_error(status: int, err_type: str, **details: Any) -> tuple[int, dict]:
    """An HTTP error reply, as the API sends it."""
    err: dict[str, Any] = {"type": err_type, "message": f"{err_type} (fake)"}
    if details:
        err["details"] = details
    return status, {"type": "error", "error": err}


def midstream_error(err_type: str) -> list[bytes]:
    """A stream that starts (HTTP 200) and then carries an `error` event."""
    return message(cut=True)[:1] + [_ev({"type": "error", "error": {"type": err_type, "message": "x"}})]


class FakeAPI:
    """Serves `replies` in order (the last one repeats): a list of SSE events, or (status, body) for
    an HTTP error. `requests` holds every request body the SDK sent."""

    def __init__(self, *replies: Any):
        self.replies = list(replies) or [message()]
        self.requests: list[dict[str, Any]] = []

    def _handle(self, request: Any) -> Any:
        self.requests.append(json.loads(request.content))
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, tuple):
            status, body = reply
            return httpx.Response(status, json=body)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"".join(reply))

    def client(self) -> Any:
        return anthropic.Anthropic(api_key="sk-ant-test", max_retries=0,
                                   http_client=httpx.Client(transport=httpx.MockTransport(self._handle)))

    def install(self, monkeypatch: Any) -> "FakeAPI":
        """Every Provider built from here on calls this fake (rooms build their own Providers)."""
        monkeypatch.setattr(Provider, "_anthropic_client", lambda p: self.client())
        return self
