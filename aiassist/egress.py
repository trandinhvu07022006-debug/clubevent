"""
Centralized AI Data Egress Policy & Classification Enforcement (AUD-003).

Invariants enforced (fail-closed):
1. All LLM calls carry an explicit `DataClassification`:
   - `PUBLIC`: strictly public events/FAQs/announcements with PII redacted.
   - `INTERNAL`: internal club data (events, KB, tasks, proposals, KPIs, social feed).
   - `CONFIDENTIAL`: governance/BCN-only knowledge or sensitive financial records.
   - `PRIVATE_PII`: recruitment screening, personal queries, or unredacted user text.
2. External Cloud LLM providers (`gemini`, `openai`, or non-loopback endpoints)
   may ONLY receive `PUBLIC` payloads. `INTERNAL`, `CONFIDENTIAL`, and `PRIVATE_PII`
   are unconditionally blocked from leaving to Cloud providers.
3. Local LLMs (`local`, `ollama` pointing to loopback/trusted local host) may process
   non-public classifications, and MUST NEVER fall back to a Cloud provider when
   classification != `PUBLIC`.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from django.conf import settings

from .privacy import redact


class DataClassification(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    PRIVATE_PII = "PRIVATE_PII"

    @property
    def label(self) -> str:
        return {
            DataClassification.PUBLIC: "Công khai",
            DataClassification.INTERNAL: "Nội bộ CLB",
            DataClassification.CONFIDENTIAL: "Mật / Quản trị",
            DataClassification.PRIVATE_PII: "Dữ liệu cá nhân",
        }[self]


CLASSIFICATION_CHOICES = tuple((c.value, c.label) for c in DataClassification)

_RANK: dict[str, int] = {
    DataClassification.PUBLIC.value: 0,
    DataClassification.INTERNAL.value: 1,
    DataClassification.CONFIDENTIAL.value: 2,
    DataClassification.PRIVATE_PII.value: 3,
}

LOCAL_PROVIDER_NAMES = frozenset({"local", "ollama"})
CLOUD_PROVIDER_NAMES = frozenset({"gemini", "openai"})


class EgressPolicyError(Exception):
    """Raised when an AI provider call violates data classification egress rules."""


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    classification: str
    primary_provider: str
    fallback_provider: str
    reason: str = ""


def normalize_classification(value: str | DataClassification | None) -> str:
    """Normalize a classification value, failing closed to INTERNAL if unknown."""
    if isinstance(value, DataClassification):
        return value.value
    raw = str(value or "").strip().upper()
    if raw in _RANK:
        return raw
    return DataClassification.INTERNAL.value


def max_classification(*levels: str | DataClassification | None) -> str:
    """Return the strictest (highest) classification among given levels."""
    best = DataClassification.PUBLIC.value
    best_rank = 0
    for lvl in levels:
        if lvl is None or lvl == "":
            continue
        norm = normalize_classification(lvl)
        rank = _RANK.get(norm, 1)
        if rank > best_rank:
            best = norm
            best_rank = rank
    return best


def is_local_trusted_endpoint(base_url: str) -> bool:
    """
    Verify that a configured `local` LLM endpoint actually resolves to loopback
    (unless `AI_ALLOW_PRIVATE_LOCAL_HOST=True` explicitly permits private LAN).
    """
    raw = (base_url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback:
            return True
        if getattr(settings, "AI_ALLOW_PRIVATE_LOCAL_HOST", False) and ip.is_private:
            return True
    except ValueError:
        return False
    return False


def is_cloud_provider(provider: str | None, local_base_url: str = "") -> bool:
    """Return True if sending data to `provider` constitutes external egress."""
    norm = (provider or "").strip().lower()
    if not norm or norm == "mock":
        return False
    if norm in LOCAL_PROVIDER_NAMES:
        url = local_base_url or getattr(settings, "AI_LOCAL_BASE_URL", "")
        return not is_local_trusted_endpoint(url)
    return True


def evaluate_egress(
    *,
    classification: str | DataClassification | None,
    primary_provider: str | None,
    fallback_provider: str | None = "",
    local_base_url: str = "",
) -> EgressDecision:
    """
    Evaluate whether an LLM request may proceed under `classification`.

    Cloud providers (`gemini`, `openai`, or non-local endpoints) may ONLY receive
    `PUBLIC` data. Any configured cloud fallback is stripped whenever data is
    non-public (`INTERNAL`, `CONFIDENTIAL`, `PRIVATE_PII`).
    """
    cls_norm = normalize_classification(classification)
    primary = (primary_provider or "mock").strip().lower()
    fallback = (fallback_provider or "").strip().lower()
    if fallback == primary:
        fallback = ""

    if primary == "mock":
        return EgressDecision(
            allowed=True,
            classification=cls_norm,
            primary_provider="mock",
            fallback_provider="",
        )

    if cls_norm == DataClassification.PUBLIC.value:
        return EgressDecision(
            allowed=True,
            classification=cls_norm,
            primary_provider=primary,
            fallback_provider=fallback,
        )

    # Non-public classifications MUST NEVER leave trusted local execution.
    if is_cloud_provider(primary, local_base_url=local_base_url):
        return EgressDecision(
            allowed=False,
            classification=cls_norm,
            primary_provider=primary,
            fallback_provider="",
            reason=(
                f"Chính sách bảo mật AI chặn gửi dữ liệu phân loại {cls_norm} "
                f"ra nhà cung cấp đám mây ({primary}). Chỉ cho phép Local LLM tin cậy."
            ),
        )

    safe_fallback = ""
    if fallback and not is_cloud_provider(fallback, local_base_url=local_base_url):
        safe_fallback = fallback

    return EgressDecision(
        allowed=True,
        classification=cls_norm,
        primary_provider=primary,
        fallback_provider=safe_fallback,
    )


def assert_egress_safe(
    *,
    classification: str | DataClassification | None,
    provider: str | None,
    local_base_url: str = "",
) -> None:
    """Defense-in-depth assertion run immediately before opening any provider connection."""
    decision = evaluate_egress(
        classification=classification,
        primary_provider=provider,
        fallback_provider="",
        local_base_url=local_base_url,
    )
    if not decision.allowed:
        raise EgressPolicyError(decision.reason)


def scrub_egress_secrets(text: str, extra_secrets: tuple[str, ...] = ()) -> str:
    """
    Strip accidental runtime configuration secrets (API keys, Flask/Django keys)
    before prompting an external or local LLM.
    """
    cleaned = redact(text or "")
    candidates = [
        getattr(settings, "SECRET_KEY", ""),
        getattr(settings, "CERT_SIGNING_KEY", ""),
        getattr(settings, "CHAT_MASTER_KEK", ""),
        getattr(settings, "AI_API_KEY", ""),
        getattr(settings, "SEPAY_API_KEY", ""),
        os.environ.get("DB_PASSWORD", ""),
        *extra_secrets,
    ]
    for secret in candidates:
        s = str(secret or "").strip()
        if len(s) >= 8 and s in cleaned:
            cleaned = cleaned.replace(s, "[SECRET-REDACTED]")
    return cleaned


def contains_runtime_secret(text: str, canary_values: tuple[str, ...] = ()) -> bool:
    """Check whether any active application secret or explicit canary appears in text."""
    body = text or ""
    candidates = [
        getattr(settings, "AI_API_KEY", ""),
        getattr(settings, "SECRET_KEY", ""),
        getattr(settings, "CERT_SIGNING_KEY", ""),
        getattr(settings, "CHAT_MASTER_KEK", ""),
        *canary_values,
    ]
    for secret in candidates:
        s = str(secret or "").strip()
        if len(s) >= 8 and not s.startswith(("dev-only", "test-only")) and s in body:
            return True
    for canary in canary_values:
        if canary and canary in body:
            return True
    return False


def content_sha256(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()
