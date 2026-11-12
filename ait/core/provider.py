"""Shared model-provider client for every AIT room.

The whole point of this module is the reproducibility that no room had before it:
every call sends a **seed** and an explicit **provider pin**, and every result records
what actually served it — model, provider, finish_reason, usage, response id, and the
exact request params. A failed call is never a silent empty string; it comes back as
`CallResult(ok=False, ...)` so the caller can record `end_reason="call_failed"` instead
of confusing an outage with the model choosing to stop.

Stdlib only (urllib), matching the rooms it replaces. OpenAI-compatible chat endpoints
(OpenRouter by default). A model named `anthropic/<id>` (e.g. `anthropic/claude-opus-5-5`) goes to
the Anthropic API instead, through the official SDK, imported only when such a model is used.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# A process-wide cap on concurrent provider HTTP calls — the shared rate budget when many rooms run in
# parallel (ait gauntlet --room-concurrency). Bounds total load on the pinned backend so parallel rooms
# don't 429-storm the account. None = uncapped (a single `ait run`); set via set_inflight_limit().
_INFLIGHT: "threading.Semaphore | None" = None


def set_inflight_limit(n: int | None) -> None:
    global _INFLIGHT
    _INFLIGHT = threading.Semaphore(n) if n and n > 0 else None


@contextmanager
def _inflight_slot():
    sema = _INFLIGHT            # snapshot: a reconfigure mid-flight can't desync acquire/release
    if sema is None:
        yield
        return
    sema.acquire()
    try:
        yield
    finally:
        sema.release()

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class ProviderConfig:
    """How to reach the model, and how to pin it so runs are comparable.

    `pin` is the OpenRouter `provider` routing block. Defaulting `allow_fallbacks`
    to False is deliberate: a rerun that silently lands on a different backend is the
    confound the rooms kept hitting (provider drift confounded with arm). Set an
    explicit `order` to pin one backend, or pass allow_fallbacks=True to opt out.
    """

    model: str
    endpoint: str = DEFAULT_ENDPOINT
    temperature: float = 0.7
    top_p: float = 0.80
    max_tokens: int = 8192
    # provider pinning
    order: tuple[str, ...] = ()          # e.g. ("fireworks", "together")
    allow_fallbacks: bool = False
    # retry policy (shared: the widest of the rooms' loops)
    tries: int = 8
    backoff_cap: float = 45.0
    jitter: float = 3.0
    call_timeout: float = 300.0          # per-attempt urlopen timeout, seconds
    # optional reasoning-effort passthrough (ignored by providers that don't take it)
    reasoning_effort: str | None = None

    def provider_block(self) -> dict[str, Any] | None:
        block: dict[str, Any] = {"allow_fallbacks": self.allow_fallbacks}
        if self.order:
            block["order"] = list(self.order)
        # a pin with no order and fallbacks on carries no information; omit it
        if not self.order and self.allow_fallbacks:
            return None
        return block


@dataclass
class CallResult:
    """Everything a reproducible record needs about one model call."""

    ok: bool
    content: str = ""
    reasoning: str = ""
    finish_reason: str | None = None
    served_model: str | None = None      # what the provider says it ran
    served_provider: str | None = None   # which backend served it
    response_id: str | None = None
    usage: dict[str, Any] | None = None
    attempts: int = 0
    latency_s: float = 0.0
    error: str | None = None
    refusal_category: str | None = None  # Anthropic path: why a model declined (stop_details)
    # the exact params we sent, so a record is self-describing
    request: dict[str, Any] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


def resolve_api_key(keyfile: str | os.PathLike[str] | None = None) -> str:
    """Env var wins over keyfile, matching the rooms' precedence."""
    env = os.environ.get("OPENROUTER_API_KEY")
    if env:
        return env.strip()
    path = Path(keyfile) if keyfile else Path.home() / "openrouter.key"
    if path.exists():
        return path.read_text().strip()
    raise RuntimeError(
        f"no API key: set OPENROUTER_API_KEY or provide a keyfile (looked at {path})"
    )


ANTHROPIC_PREFIX = "anthropic/"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"


@dataclass(frozen=True)
class AnthropicModel:
    """What a request to one model may carry. `price` is USD per million tokens (input, output),
    first-party rates: the API returns tokens, not dollars, so the Meter's cost is computed here
    (thinking bills as output and is in output_tokens). `thinking` is "adaptive" (adaptive thinking
    + output_config.effort) or "budget" (a fixed budget_tokens below max_tokens, no effort)."""

    price: tuple[float, float]
    max_output: int
    thinking: str


# A model that isn't listed is refused when the Provider is built, not guessed at: a guessed thinking
# mode 400s every call (Sonnet 4.5 and Opus 4.5 take no adaptive thinking), and a guessed price is $0.
ANTHROPIC_MODELS = {
    "claude-opus-5-5": AnthropicModel((4.0, 20.0), 128_000, "adaptive"),
    "claude-sonnet-5-5": AnthropicModel((2.0, 10.0), 128_000, "adaptive"),
    "claude-fable-5-1": AnthropicModel((10.0, 50.0), 128_000, "adaptive"),
    "claude-opus-4-8": AnthropicModel((5.0, 25.0), 128_000, "adaptive"),
    "claude-haiku-4-5": AnthropicModel((1.0, 5.0), 64_000, "budget"),
}

# Thinking counts against max_tokens: at a run's 8192 a long think ends at the cap with no answer (the
# GLM n=60 truncation). The call is streamed, so a high floor costs nothing unless it is used.
ANTHROPIC_MIN_TOKENS = 32000
# budget-thinking models take no `effort`, so the requested effort picks the thinking budget instead
# ("high", the default, is the 16000 these calls always used). Capped below max_tokens at call time.
_EFFORT_BUDGET = {"low": 4096, "medium": 8192, "high": 16000, "xhigh": 24000, "max": 31000}
# API error types the same request will hit again. Classified by type, not HTTP status: an error event
# mid-stream arrives with the stream's 200, and an out-of-credit 402 isn't in any 4xx shortlist.
_NO_RETRY_TYPES = {"invalid_request_error", "authentication_error", "permission_error",
                   "not_found_error", "request_too_large", "billing_error"}
_NO_RETRY_STATUS = {400, 401, 402, 403, 404, 413}       # when the error carries no body to read
# a 429 that waiting won't clear: the account's monthly spend limit
_NO_RETRY_CODES = {"enforced_spend_limit_reached"}


def is_anthropic(model: str) -> bool:
    return model.startswith(ANTHROPIC_PREFIX)


def anthropic_model(model_id: str) -> AnthropicModel | None:
    """Look up an API model id: an alias (`claude-haiku-4-5`) or its dated snapshot
    (`claude-haiku-4-5-20251001`, which is also what the API echoes back as `model`)."""
    if model_id in ANTHROPIC_MODELS:
        return ANTHROPIC_MODELS[model_id]
    base, _, date = model_id.rpartition("-")
    return ANTHROPIC_MODELS.get(base) if date.isdigit() and len(date) == 8 else None


def sent_max_tokens(model: str, max_tokens: int) -> int:
    """The max_tokens a call to `model` actually sends for a requested budget. Anything that
    records or exports a budget asks here instead of re-deriving the provider's policy."""
    return max(max_tokens, ANTHROPIC_MIN_TOKENS) if is_anthropic(model) else max_tokens


def key_for(provider: Any, model: str) -> str | None:
    """A run provider's key, for another Provider calling `model`: passed on only when both use the
    same backend. None lets that Provider resolve its own (OPENROUTER_API_KEY / ~/openrouter.key)."""
    return provider.api_key if is_anthropic(model) == is_anthropic(provider.config.model) else None


def require_anthropic_sdk() -> None:
    """Fail at the start of a run, not on every call: `anthropic/` models need the official SDK."""
    try:
        import anthropic  # noqa: F401
    except ImportError as e:
        if e.name == "anthropic":
            raise RuntimeError("anthropic/ models need the anthropic SDK: pip install anthropic") from e
        # installed, but its own import fails: pip would say "already satisfied", so give the cause
        raise RuntimeError(f"the anthropic SDK is installed but fails to import: {e}") from e


def check_anthropic(model: str, max_tokens: int) -> AnthropicModel:
    """Everything an `anthropic/` model needs before its first call, checked once, loudly: the SDK, a
    model whose request surface is known, a budget within its output limit, and no environment
    credential that would ride along with the run's key."""
    require_anthropic_sdk()
    model_id = model[len(ANTHROPIC_PREFIX):]
    spec = anthropic_model(model_id)
    if spec is None:
        raise RuntimeError(f"unknown Anthropic model {model_id!r}: add it to ANTHROPIC_MODELS in "
                           f"ait/core/provider.py with its price, output limit and thinking mode")
    sent = sent_max_tokens(model, max_tokens)
    if sent > spec.max_output:
        raise RuntimeError(f"{model_id} takes at most {spec.max_output} output tokens; "
                           f"this call would send max_tokens={sent}")
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        # the SDK reads it from the environment even when api_key is given and sends both headers,
        # which the API rejects (401) — or bills whatever account the token belongs to
        raise RuntimeError("ANTHROPIC_AUTH_TOKEN is set; unset it for this run (the run's key comes "
                           "from ANTHROPIC_API_KEY or ~/anthropic.key)")
    return spec


def resolve_anthropic_key(keyfile: str | os.PathLike[str] | None = None) -> str:
    """ANTHROPIC_API_KEY wins over ~/anthropic.key. Explicit on purpose: these runs bill a specific
    credit balance, so the SDK's fallback to whatever `ant auth` profile is active is not used."""
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env.strip()
    path = Path(keyfile) if keyfile else Path.home() / "anthropic.key"
    if path.exists():
        return path.read_text().strip()
    raise RuntimeError(
        f"no Anthropic key: set ANTHROPIC_API_KEY or create {path} (chmod 600)"
    )


class NoRetry(Exception):
    """A failure the same request will hit again (bad request, auth, unknown model): stop retrying."""


class Meter:
    """What a run's model calls cost: calls, tokens, and the USD OpenRouter reports per call.
    Thread-safe; one per run, shared by everything that calls a model for that run's trials."""

    def __init__(self, start: dict[str, Any] | None = None):
        import threading
        self._lock = threading.Lock()
        self.totals = {"calls": 0, "failed_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                       "cost_usd": 0.0, **(start or {})}

    def add(self, usage: dict[str, Any] | None, ok: bool = True) -> None:
        u = usage or {}
        with self._lock:
            self.totals["calls"] += 1
            self.totals["failed_calls"] += 0 if ok else 1
            self.totals["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
            self.totals["completion_tokens"] += int(u.get("completion_tokens") or 0)
            self.totals["cost_usd"] = round(self.totals["cost_usd"] + float(u.get("cost") or 0.0), 6)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.totals)


class Provider:
    """A thin, deterministic-as-possible OpenAI-compatible chat client.

    `seed` is required at call time and combined per-trial by the runner, so the same
    (config, messages, seed) is as reproducible as the backend allows — and the seed we
    used is recorded either way.
    """

    def __init__(self, config: ProviderConfig, api_key: str | None = None, meter: Meter | None = None):
        self.config = config
        self.anthropic = is_anthropic(config.model)
        if self.anthropic:
            self._spec = check_anthropic(config.model, config.max_tokens)
            effort = config.reasoning_effort or "high"
            if self._spec.thinking == "budget" and effort not in _EFFORT_BUDGET:
                raise RuntimeError(f"reasoning_effort {effort!r} for {config.model}: expected one of "
                                   f"{sorted(_EFFORT_BUDGET, key=_EFFORT_BUDGET.get)}")
            # rooms pass the run's key through (ctx.provider.api_key); for an Anthropic model that is
            # the Anthropic key only if it looks like one, otherwise resolve it here
            self._api_key = api_key if (api_key or "").startswith("sk-ant-") else resolve_anthropic_key()
        else:
            if (api_key or "").startswith("sk-ant-"):
                # an Anthropic run's key handed to an OpenRouter model (a room's GLM reviewer): it
                # would go to openrouter.ai as a Bearer token. Pass keys on with key_for().
                raise RuntimeError(f"an Anthropic API key was passed for {config.model}, which is "
                                   f"called through {config.endpoint}; refusing to send it there")
            self._api_key = api_key or resolve_api_key()
        self.meter = meter or Meter()
        self._client = None

    @property
    def api_key(self) -> str:
        """For a room whose harness makes its calls from inside its own container (ait02): it
        must use the same key the run was started with, not re-resolve one."""
        return self._api_key

    def chat(self, messages: list[dict[str, str]], *, seed: int,
             sleep=time.sleep, rng: random.Random | None = None) -> CallResult:
        if self.anthropic:
            return self._chat_anthropic(messages, seed=seed, sleep=sleep, rng=rng)
        cfg = self.config
        rng = rng or random.Random(seed)
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
            "temperature": cfg.temperature,
            "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens,
            "seed": seed,
            # ask OpenRouter for the call's cost explicitly (it returns it today without this, but the
            # card's cost line shouldn't depend on a default)
            "usage": {"include": True},
        }
        pin = cfg.provider_block()
        if pin is not None:
            body["provider"] = pin
        if cfg.reasoning_effort:
            body["reasoning"] = {"effort": cfg.reasoning_effort}

        request_meta = {
            "model": cfg.model, "endpoint": cfg.endpoint,
            "temperature": cfg.temperature, "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens, "seed": seed,
            "provider_pin": pin, "reasoning_effort": cfg.reasoning_effort,
        }
        started = time.monotonic()
        last_err = "unknown"
        for attempt in range(1, cfg.tries + 1):
            try:
                with _inflight_slot():      # hold a global slot only for the HTTP call, not the backoff
                    content, reasoning, meta = self._post(body)
                self.meter.add(meta.get("usage"))
                return CallResult(
                    ok=True, content=content, reasoning=reasoning,
                    finish_reason=meta.get("finish_reason"),
                    served_model=meta.get("model"),
                    served_provider=meta.get("provider"),
                    response_id=meta.get("id"),
                    usage=meta.get("usage"),
                    attempts=attempt,
                    latency_s=round(time.monotonic() - started, 3),
                    request=request_meta,
                )
            except NoRetry as e:
                last_err, attempt_made = f"NoRetry: {e}", attempt
                break
            except Exception as e:  # noqa: BLE001 - report, don't crash the room
                last_err, attempt_made = f"{type(e).__name__}: {e}", attempt
                if attempt < cfg.tries:
                    sleep(min(2 * 2 ** attempt, cfg.backoff_cap) + rng.uniform(0, cfg.jitter))
        self.meter.add(None, ok=False)
        return CallResult(
            ok=False, attempts=attempt_made,
            latency_s=round(time.monotonic() - started, 3),
            error=last_err, request=request_meta,
        )

    # -- Anthropic API ---------------------------------------------------------
    # Differences from the OpenRouter path, all recorded in `request` so a record says what was sent:
    # - no temperature / top_p / seed: current Claude models reject sampling params (400), so the
    #   seed is bookkeeping only and a call is not reproducible from it;
    # - thinking is always on: adaptive with `effort` on most models, a fixed budget picked by the
    #   requested effort on budget-thinking ones (Haiku 4.5). `reasoning` holds the API's thinking
    #   *summaries* (`reasoning_kind: "summary"`), never raw CoT, so don't compare it with GLM's;
    # - no server-side fallbacks: a refusal must stay this model's refusal, not a silent answer from
    #   another model mid-run (the backend-drift confound the pin exists to stop). A refusal comes
    #   back ok=True with finish_reason "refusal" and its category, as data.
    def _chat_anthropic(self, messages: list[dict[str, str]], *, seed: int,
                        sleep=time.sleep, rng: random.Random | None = None) -> CallResult:
        cfg = self.config
        rng = rng or random.Random(seed)
        kw, request_meta = self._anthropic_request(messages, seed)
        started = time.monotonic()
        last_err = "unknown"
        for attempt in range(1, cfg.tries + 1):
            try:
                with _inflight_slot():
                    content, reasoning, meta = self._post_anthropic(kw)
                self.meter.add(meta.get("usage"))
                return CallResult(
                    ok=True, content=content, reasoning=reasoning,
                    finish_reason=meta.get("finish_reason"),
                    served_model=meta.get("model"), served_provider="anthropic",
                    refusal_category=meta.get("refusal_category"),
                    response_id=meta.get("id"), usage=meta.get("usage"),
                    attempts=attempt, latency_s=round(time.monotonic() - started, 3),
                    request=request_meta,
                )
            except NoRetry as e:
                last_err = f"NoRetry: {e}"
                break
            except Exception as e:  # noqa: BLE001 - report, don't crash the room
                last_err = f"{type(e).__name__}: {e}"
                if attempt < cfg.tries:
                    sleep(min(2 * 2 ** attempt, cfg.backoff_cap) + rng.uniform(0, cfg.jitter))
        self.meter.add(None, ok=False)
        return CallResult(ok=False, attempts=attempt, latency_s=round(time.monotonic() - started, 3),
                          error=last_err, request=request_meta)

    def _anthropic_request(self, messages: list[dict[str, str]],
                           seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
        """(the SDK call's kwargs, the record of them)."""
        cfg = self.config
        model = cfg.model[len(ANTHROPIC_PREFIX):]
        effort = cfg.reasoning_effort or "high"
        max_tokens = sent_max_tokens(cfg.model, cfg.max_tokens)     # never lowered, only raised
        system, msgs, dropped = to_anthropic_messages(messages)
        kw: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": msgs}
        budget = None
        if self._spec.thinking == "budget":
            # no adaptive thinking and no effort (both 400): the effort picks a budget below max_tokens
            budget = min(_EFFORT_BUDGET[effort], max_tokens - 1)
            kw["thinking"] = {"type": "enabled", "budget_tokens": budget}
        else:
            kw["thinking"] = {"type": "adaptive", "display": "summarized"}
            # SDK 0.75 predates output_config; it goes on the wire as-is
            kw["extra_body"] = {"output_config": {"effort": effort}}
        if system:
            kw["system"] = system
        request_meta = {
            "model": cfg.model, "endpoint": "anthropic-api", "temperature": None, "top_p": None,
            "max_tokens": max_tokens, "seed": seed, "seed_sent": False,
            "provider_pin": {"order": ["anthropic"], "allow_fallbacks": False},
            # the effort asked for in both modes; on a budget model it is not sent, the budget is
            "reasoning_effort": effort, "effort_sent": budget is None, "reasoning_kind": "summary",
            "thinking": self._spec.thinking, "thinking_budget": budget,
            "dropped_empty_assistant_turns": dropped,
        }
        return kw, request_meta

    def _anthropic_client(self):
        if self._client is None:
            import anthropic        # checked in __init__ (check_anthropic)
            try:
                # the retry loop above owns retries (same policy as every room), so the SDK's are off.
                # base_url is pinned: the SDK would otherwise follow ANTHROPIC_BASE_URL, and the record
                # says "anthropic-api" for every call
                self._client = anthropic.Anthropic(api_key=self._api_key, base_url=ANTHROPIC_BASE_URL,
                                                   max_retries=0, timeout=self.config.call_timeout)
            except Exception as e:  # noqa: BLE001 - a client that can't be built won't be on retry 2
                raise NoRetry(f"could not build the anthropic client: {type(e).__name__}: {e}") from e
        return self._client

    def _post_anthropic(self, kw: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        client = self._anthropic_client()
        stop_details = None
        try:
            # streamed so a large max_tokens can't hit the HTTP timeout. The events are read only for
            # stop_details: SDK 0.75's accumulator drops it from the final message
            with client.messages.stream(**kw) as stream:
                for event in stream:
                    if getattr(event, "type", None) == "message_delta":
                        stop_details = getattr(event.delta, "stop_details", None) or stop_details
                msg = stream.get_final_message()
        except Exception as e:  # noqa: BLE001 - classified from the error body, no SDK import needed
            if _no_retry(e):
                raise NoRetry(f"{type(e).__name__}: {getattr(e, 'message', e)}") from e
            raise
        if msg.stop_reason is None:
            # the body ended cleanly before message_delta: a cut-off stream, not the model's answer
            raise RuntimeError("stream ended before the message finished (no stop_reason)")
        return parse_anthropic(msg, stop_details)

    def _post(self, body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self.config.endpoint, data=data,
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.call_timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            # bad request, auth, billing, forbidden, unknown model: the same call fails the same way
            if e.code in (400, 401, 402, 403, 404):
                raise NoRetry(f"HTTP {e.code}: {e.reason}") from e
            raise
        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        choice = payload["choices"][0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        meta = {
            "finish_reason": choice.get("finish_reason"),
            "model": payload.get("model"),
            "provider": payload.get("provider"),
            "id": payload.get("id"),
            "usage": payload.get("usage"),
        }
        return content, reasoning, meta


def to_anthropic_messages(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]], int]:
    """OpenAI-style chat -> (system, messages, n_dropped). Leading system turns become `system`; a
    later one stays a mid-conversation system message (Opus 5.5 / Sonnet 5.5 take those). An empty
    assistant turn (a prior refusal or empty reply) is dropped: the API rejects empty text, and
    adjacent user turns are merged by the API, so the transcript the model sees is unchanged."""
    system_parts: list[str] = []
    out: list[dict[str, str]] = []
    dropped = 0
    for m in messages:
        role, content = m.get("role"), m.get("content") or ""
        if role == "system" and not out:
            system_parts.append(content)
        elif role == "assistant" and not content.strip():
            dropped += 1
        else:
            out.append({"role": role, "content": content})
    return "\n\n".join(p for p in system_parts if p), out, dropped


# Anthropic stop reasons that mean "cut off at the budget", reported as OpenRouter's "length" so the
# rooms' truncation guards (ait03's empty-leader rule, ait05's void rule) see a capped Claude turn too
_LENGTH_STOPS = {"max_tokens", "model_context_window_exceeded"}


def parse_anthropic(msg: Any, stop_details: Any = None) -> tuple[str, str, dict[str, Any]]:
    """An SDK Message -> (content, reasoning, meta), in the same shape `_parse` gives the OpenRouter
    path: `finish_reason` in its vocabulary ("length" for a capped reply; "refusal" stays as is),
    `usage` mapped to the Meter's keys and a computed `cost`. `stop_details` is the stream's own
    (the final message may not carry it)."""
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    reasoning = "\n".join(getattr(b, "thinking", "") or "" for b in msg.content
                          if getattr(b, "type", None) == "thinking")
    u = msg.usage
    inp = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) \
        + (getattr(u, "cache_read_input_tokens", 0) or 0)
    out = u.output_tokens or 0
    spec = anthropic_model(msg.model or "")
    pin, pout = spec.price if spec else (0.0, 0.0)
    usage = {"prompt_tokens": inp, "completion_tokens": out,
             "cost": round((inp * pin + out * pout) / 1e6, 6), "priced": spec is not None}
    finish = "length" if msg.stop_reason in _LENGTH_STOPS else msg.stop_reason
    meta = {"finish_reason": finish, "model": msg.model, "id": msg.id, "usage": usage}
    details = getattr(msg, "stop_details", None) or stop_details
    if msg.stop_reason == "refusal" and details is not None:
        # an SDK that predates stop_details keeps it as a plain dict
        meta["refusal_category"] = (details.get("category") if isinstance(details, dict)
                                    else getattr(details, "category", None))
    return text, reasoning, meta


def _no_retry(e: Exception) -> bool:
    """Will the same request fail the same way? Read from the API's error body (type, and a 429's
    error_code), which mid-stream errors carry too; the HTTP status only when there is no body."""
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict) and err.get("type"):
        details = err.get("details") if isinstance(err.get("details"), dict) else {}
        return err["type"] in _NO_RETRY_TYPES or details.get("error_code") in _NO_RETRY_CODES
    return getattr(e, "status_code", None) in _NO_RETRY_STATUS


def probe_pin(config: ProviderConfig, api_key: str | None = None,
              meter: Meter | None = None) -> ProviderConfig:
    """Pin a run to one backend when no pin was given.

    One short call asks OpenRouter to serve the model however it likes; the backend that answers
    becomes the pin for the whole run, with fallbacks off. Without this, a default run let OpenRouter
    route every call independently, so two passes (or two arms) could be served by different builds of
    "the same" model. An explicit `order` is left as is. A failed probe raises: running unpinned
    silently is the thing this exists to stop.
    """
    if config.order:
        return config
    from dataclasses import replace
    if is_anthropic(config.model):   # first-party: one backend, nothing to probe
        return replace(config, order=("anthropic",), allow_fallbacks=False)
    probe = replace(config, max_tokens=50, tries=3)
    res = Provider(probe, api_key=api_key, meter=meter).chat(
        [{"role": "user", "content": "Reply with the single word OK."}], seed=0)
    if not res.ok or not res.served_provider:
        raise RuntimeError(f"provider pin probe failed for {config.model}: "
                           f"{res.error or 'no provider reported'} (pass --provider, or --no-pin)")
    return replace(config, order=(res.served_provider,), allow_fallbacks=False)

