"""
Multi-provider AI Gateway: Circuit Breaker, Daily Char Budget, OpenAI/Local LLM adapter & SSE streaming.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Iterator

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

LOCAL_PROVIDERS = frozenset({"local", "ollama"})
SUPPORTED_PROVIDERS = frozenset({"gemini", "openai", "local", "ollama", "mock"})


class CircuitOpenError(Exception):
    """Raised when provider circuit breaker is open during cooldown."""


class BudgetExceededError(Exception):
    """Raised when prompt cap or daily AI character budget is exceeded."""


class CircuitBreaker:
    """Thread- & cache-backed circuit breaker per AI provider."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @staticmethod
    def _key(provider: str) -> str:
        return f"kmg:ai:cb:{provider}"

    def state(self, provider: str) -> dict:
        data = cache.get(self._key(provider)) or {"failures": 0, "open_until": 0.0}
        now = time.time()
        open_until = float(data.get("open_until", 0.0) or 0.0)
        failures = int(data.get("failures", 0) or 0)
        if open_until > now:
            status = "open"
        elif open_until > 0:
            status = "half_open"
        else:
            status = "closed"
        return {
            "provider": provider,
            "state": status,
            "failures": failures,
            "retry_after": max(int(open_until - now), 0),
        }

    def allow_request(self, provider: str) -> bool:
        data = cache.get(self._key(provider))
        if not data:
            return True
        return time.time() >= float(data.get("open_until", 0.0) or 0.0)

    def record_success(self, provider: str) -> None:
        with self._lock:
            cache.delete(self._key(provider))

    def record_failure(
        self,
        provider: str,
        threshold: int | None = None,
        cooldown: int | None = None,
    ) -> dict:
        thresh = max(int(threshold or getattr(settings, "AI_CIRCUIT_BREAKER_THRESHOLD", 5)), 1)
        cd = max(int(cooldown or getattr(settings, "AI_CIRCUIT_BREAKER_COOLDOWN", 60)), 5)
        with self._lock:
            cur = cache.get(self._key(provider)) or {"failures": 0, "open_until": 0.0}
            failures = int(cur.get("failures", 0) or 0) + 1
            open_until = float(cur.get("open_until", 0.0) or 0.0)
            if failures >= thresh:
                open_until = time.time() + cd
            payload = {"failures": failures, "open_until": open_until}
            cache.set(self._key(provider), payload, timeout=max(cd * 4, 300))
            return self.state(provider)

    def reset(self, provider: str) -> None:
        self.record_success(provider)


class DailyBudgetTracker:
    """Tracks per-day character usage across all AI calls to protect student quotas."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @staticmethod
    def _key() -> str:
        return f"kmg:ai:budget:{timezone.localdate().isoformat()}"

    def check_and_reserve(self, prompt_chars: int) -> None:
        max_prompt = int(getattr(settings, "AI_MAX_PROMPT_CHARS", 32000) or 32000)
        if prompt_chars > max_prompt:
            raise BudgetExceededError(
                f"Ngữ cảnh yêu cầu quá dài ({prompt_chars}/{max_prompt} ký tự)."
            )
        daily_cap = int(getattr(settings, "AI_DAILY_CHAR_BUDGET", 500000) or 0)
        if daily_cap <= 0:
            return
        with self._lock:
            usage = cache.get(self._key()) or {"chars": 0, "calls": 0}
            used = int(usage.get("chars", 0) or 0)
            if used + prompt_chars > daily_cap:
                raise BudgetExceededError(
                    "Đã đạt giới hạn ngân sách ký tự AI trong ngày."
                )
            usage["chars"] = used + prompt_chars
            usage["calls"] = int(usage.get("calls", 0) or 0) + 1
            cache.set(self._key(), usage, timeout=86400)

    def record_output(self, output_chars: int) -> None:
        if output_chars <= 0:
            return
        with self._lock:
            usage = cache.get(self._key()) or {"chars": 0, "calls": 0}
            usage["chars"] = int(usage.get("chars", 0) or 0) + output_chars
            cache.set(self._key(), usage, timeout=86400)

    def get_usage(self) -> dict:
        usage = cache.get(self._key()) or {"chars": 0, "calls": 0}
        daily_cap = int(getattr(settings, "AI_DAILY_CHAR_BUDGET", 500000) or 0)
        return {
            "chars_used": int(usage.get("chars", 0) or 0),
            "calls": int(usage.get("calls", 0) or 0),
            "daily_cap": daily_cap,
        }


circuit_breaker = CircuitBreaker()
budget_tracker = DailyBudgetTracker()


def is_local_provider(provider: str | None) -> bool:
    return (provider or "").strip().lower() in LOCAL_PROVIDERS


def provider_has_credentials(provider: str | None) -> bool:
    norm = (provider or "").strip().lower()
    if norm in LOCAL_PROVIDERS:
        return bool(getattr(settings, "AI_LOCAL_BASE_URL", "").strip())
    if norm in ("gemini", "openai"):
        return bool(getattr(settings, "AI_API_KEY", "").strip())
    return False


def resolve_model_for_provider(provider: str, model: str | None = None) -> str:
    if is_local_provider(provider):
        return getattr(settings, "AI_LOCAL_MODEL", "") or model or settings.AI_MODEL
    return model or settings.AI_MODEL


def is_live_streaming_ready() -> bool:
    provider = (getattr(settings, "AI_PROVIDER", "mock") or "mock").strip().lower()
    if provider == "mock" or getattr(settings, "AI_FOUNDATION_AGENT", False):
        return False
    return provider_has_credentials(provider) and circuit_breaker.allow_request(provider)


def call_openai_compatible(
    prompt: str,
    model: str,
    *,
    base_url: str,
    api_key: str = "",
    temperature: float = 0.4,
    json_mode: bool = True,
    timeout: int | None = None,
    urlopen_fn: Callable | None = None,
) -> str:
    """Call OpenAI or an OpenAI-compatible Local LLM endpoint (Ollama/vLLM/LM Studio)."""
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url.rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    req_timeout = timeout or getattr(settings, "AI_TIMEOUT_SECONDS", 40)
    open_fn = urlopen_fn or urllib.request.urlopen
    with open_fn(req, timeout=req_timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _iter_sse_json_lines(resp) -> Iterator[dict]:
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def stream_gemini_tokens(
    prompt: str,
    model: str,
    *,
    urlopen_fn: Callable | None = None,
) -> Iterator[str]:
    """Yield text deltas directly from Gemini streamGenerateContent SSE endpoint."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:streamGenerateContent?alt=sse"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4},
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.AI_API_KEY,
        },
    )
    open_fn = urlopen_fn or urllib.request.urlopen
    with open_fn(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
        for chunk in _iter_sse_json_lines(resp):
            candidates = chunk.get("candidates") or []
            if not candidates:
                continue
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for part in parts:
                text = part.get("text")
                if text:
                    yield text


def stream_openai_tokens(
    prompt: str,
    model: str,
    *,
    base_url: str,
    api_key: str = "",
    urlopen_fn: Callable | None = None,
) -> Iterator[str]:
    """Yield text deltas from OpenAI or Local/Ollama OpenAI-compatible SSE stream."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    open_fn = urlopen_fn or urllib.request.urlopen
    with open_fn(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
        for chunk in _iter_sse_json_lines(resp):
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = (choices[0].get("delta") or {}).get("content")
            if delta:
                yield delta


def stream_provider_tokens(
    prompt: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    urlopen_fn: Callable | None = None,
) -> Iterator[str]:
    """Stream text deltas through circuit breaker and budget tracker."""
    active_provider = (provider or settings.AI_PROVIDER or "mock").strip().lower()
    if active_provider == "mock":
        raise CircuitOpenError("Mock provider does not stream external tokens.")
    if not provider_has_credentials(active_provider):
        raise CircuitOpenError(f"Thiếu cấu hình kết nối cho provider {active_provider}.")
    if not circuit_breaker.allow_request(active_provider):
        raise CircuitOpenError(f"Circuit breaker đang mở cho {active_provider}.")

    budget_tracker.check_and_reserve(len(prompt))
    resolved_model = resolve_model_for_provider(active_provider, model)
    emitted = 0
    try:
        if active_provider == "gemini":
            gen = stream_gemini_tokens(prompt, resolved_model, urlopen_fn=urlopen_fn)
        elif active_provider == "openai":
            gen = stream_openai_tokens(
                prompt,
                resolved_model,
                base_url="https://api.openai.com/v1",
                api_key=settings.AI_API_KEY,
                urlopen_fn=urlopen_fn,
            )
        elif is_local_provider(active_provider):
            gen = stream_openai_tokens(
                prompt,
                resolved_model,
                base_url=settings.AI_LOCAL_BASE_URL,
                api_key=settings.AI_API_KEY,
                urlopen_fn=urlopen_fn,
            )
        else:
            raise CircuitOpenError(f"Provider không hỗ trợ streaming: {active_provider}")

        for delta in gen:
            emitted += len(delta)
            yield delta
    except Exception:
        circuit_breaker.record_failure(active_provider)
        raise
    else:
        circuit_breaker.record_success(active_provider)
        budget_tracker.record_output(emitted)


def get_ai_gateway_health() -> dict:
    primary = (getattr(settings, "AI_PROVIDER", "mock") or "mock").strip().lower()
    fallback = (getattr(settings, "AI_FALLBACK_PROVIDER", "") or "").strip().lower()
    tracked = [primary]
    if fallback and fallback not in tracked:
        tracked.append(fallback)
    return {
        "primary_provider": primary,
        "fallback_provider": fallback or None,
        "local_base_url": getattr(settings, "AI_LOCAL_BASE_URL", ""),
        "local_model": getattr(settings, "AI_LOCAL_MODEL", ""),
        "circuits": {p: circuit_breaker.state(p) for p in tracked},
        "budget": budget_tracker.get_usage(),
    }
