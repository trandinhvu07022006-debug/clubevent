"""Unit and integration tests for multi-provider AI gateway, circuit breaker, budget, local LLM, and live SSE streaming."""
import io
import json
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from aiassist import providers
from aiassist.models import ClubKnowledge, KnowledgeCategory
from aiassist.services import AIError, _ask_ai
from events.models import Event, EventStatus, EventVisibility


class _FakeHTTPResponse:
    def __init__(self, body_bytes: bytes):
        self._buf = io.BytesIO(body_bytes)

    def read(self):
        return self._buf.read()

    def __iter__(self):
        return iter(self._buf)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class CircuitBreakerTests(SimpleTestCase):
    def setUp(self):
        providers.circuit_breaker.reset("gemini")

    @override_settings(
        AI_PROVIDER="gemini",
        AI_API_KEY="test-key",
        AI_CIRCUIT_BREAKER_THRESHOLD=2,
        AI_CIRCUIT_BREAKER_COOLDOWN=60,
    )
    def test_circuit_opens_on_failures_and_short_circuits_requests(self):
        err = urllib.error.URLError("connection refused")
        with patch("aiassist.services.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(AIError):
                _ask_ai("test 1")
            with self.assertRaises(AIError):
                _ask_ai("test 2")

        st = providers.circuit_breaker.state("gemini")
        self.assertEqual(st["state"], "open")
        self.assertFalse(providers.circuit_breaker.allow_request("gemini"))

        with patch("aiassist.services.urllib.request.urlopen") as mock_open:
            with self.assertRaises(AIError):
                _ask_ai("test 3")
        mock_open.assert_not_called()

        providers.circuit_breaker.record_success("gemini")
        self.assertEqual(providers.circuit_breaker.state("gemini")["state"], "closed")


class DailyBudgetTrackerTests(SimpleTestCase):
    @override_settings(
        AI_PROVIDER="local",
        AI_LOCAL_BASE_URL="http://127.0.0.1:11434/v1",
        AI_LOCAL_MODEL="qwen2.5:3b",
        AI_DAILY_CHAR_BUDGET=30,
        AI_MAX_PROMPT_CHARS=20,
    )
    def test_prompt_cap_and_daily_budget_enforced(self):
        with self.assertRaises(AIError):
            _ask_ai("x" * 25)

        fake_body = json.dumps({
            "choices": [{"message": {"content": json.dumps({"ok": True})}}]
        }).encode("utf-8")
        with patch("aiassist.services.urllib.request.urlopen", return_value=_FakeHTTPResponse(fake_body)):
            res = _ask_ai("short prompt")
        self.assertEqual(res, {"ok": True})

        with self.assertRaises(AIError):
            _ask_ai("second call prompt")


class LocalAndFallbackProviderTests(SimpleTestCase):
    def setUp(self):
        providers.circuit_breaker.reset("gemini")
        providers.circuit_breaker.reset("local")

    @override_settings(
        AI_PROVIDER="local",
        AI_API_KEY="",
        AI_LOCAL_BASE_URL="http://127.0.0.1:11434/v1",
        AI_LOCAL_MODEL="qwen2.5:3b",
        AI_DAILY_CHAR_BUDGET=500000,
    )
    def test_local_provider_works_without_api_key(self):
        captured = {}

        def fake_open(req, timeout=40):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse(json.dumps({
                "choices": [{"message": {"content": json.dumps({"answer": "ok", "event_ids": []})}}]
            }).encode("utf-8"))

        with patch("aiassist.services.urllib.request.urlopen", side_effect=fake_open):
            out = _ask_ai("hello local")

        self.assertEqual(out["answer"], "ok")
        self.assertEqual(captured["url"], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "qwen2.5:3b")
        self.assertNotIn("Authorization", captured["headers"])

    @override_settings(
        AI_PROVIDER="gemini",
        AI_FALLBACK_PROVIDER="local",
        AI_API_KEY="gem-key",
        AI_LOCAL_BASE_URL="http://127.0.0.1:11434/v1",
        AI_LOCAL_MODEL="qwen2.5:3b",
        AI_DAILY_CHAR_BUDGET=500000,
    )
    def test_fallback_to_local_when_gemini_unavailable(self):
        calls = []

        def fake_open(req, timeout=40):
            calls.append(req.full_url)
            if "generativelanguage.googleapis.com" in req.full_url:
                raise urllib.error.URLError("timeout")
            return _FakeHTTPResponse(json.dumps({
                "choices": [{"message": {"content": json.dumps({"status": "from_local"})}}]
            }).encode("utf-8"))

        with patch("aiassist.services.urllib.request.urlopen", side_effect=fake_open):
            out = _ask_ai("test fallback")

        self.assertEqual(out["status"], "from_local")
        self.assertTrue(any("127.0.0.1:11434" in u for u in calls))
        health = providers.get_ai_gateway_health()
        self.assertEqual(health["primary_provider"], "gemini")
        self.assertEqual(health["fallback_provider"], "local")


class RealSSEStreamingTests(TransactionTestCase):
    @override_settings(
        AI_PROVIDER="gemini",
        AI_API_KEY="stream-key",
        AI_DAILY_CHAR_BUDGET=500000,
    )
    def test_stream_gemini_tokens_parser(self):
        sse_bytes = (
            b'data: {"candidates":[{"content":{"parts":[{"text":"Ch\\u00e0o "}]}}]}\n\n'
            b'data: {"candidates":[{"content":{"parts":[{"text":"KMG!"}]}}]}\n\n'
        )
        with patch("aiassist.providers.urllib.request.urlopen", return_value=_FakeHTTPResponse(sse_bytes)):
            chunks = list(providers.stream_provider_tokens("hello", model="gemini-3.6-flash", provider="gemini"))
        self.assertEqual(chunks, ["Chào ", "KMG!"])

    @override_settings(
        AI_PROVIDER="local",
        AI_API_KEY="",
        AI_LOCAL_BASE_URL="http://127.0.0.1:11434/v1",
        AI_LOCAL_MODEL="qwen2.5:3b",
        AI_FOUNDATION_AGENT=False,
        AI_DAILY_CHAR_BUDGET=500000,
    )
    def test_chat_stream_api_uses_live_provider_sse_and_attaches_citations(self):
        now = timezone.now()
        ev = Event.objects.create(
            name="Đêm nhạc Acoustic KMA",
            location="Hội trường A",
            capacity=100,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=3),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        ClubKnowledge.objects.create(
            title="Quy định gửi xe hội trường",
            category=KnowledgeCategory.GENERAL,
            keywords="gui xe, bai xe, hoi truong",
            content="Sinh viên gửi xe tại cổng sau nhà A miễn phí.",
            priority=1,
            is_active=True,
        )
        sse_bytes = (
            b'data: {"choices":[{"delta":{"content":"G\\u1eedi xe t\\u1ea1i c\\u1ed5ng sau nh\\u00e0 A cho "}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"\\u0110\\u00eam nh\\u1ea1c Acoustic KMA nh\\u00e9."}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        with patch("aiassist.providers.urllib.request.urlopen", return_value=_FakeHTTPResponse(sse_bytes)):
            resp = self.client.post(
                reverse("aiassist:chat_stream_api"),
                data=json.dumps({"question": "gửi xe ở đâu trước đêm nhạc?"}),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200)
            try:
                raw = b"".join(resp.streaming_content).decode("utf-8")
            finally:
                resp.close()

        events = [
            json.loads(line.removeprefix("data: "))
            for line in raw.strip().split("\n\n")
            if line.startswith("data: ")
        ]
        tokens = [e["token"] for e in events if not e.get("done")]
        final_evt = events[-1]
        self.assertGreaterEqual(len(tokens), 2)
        self.assertTrue(final_evt["done"])
        self.assertEqual(final_evt["source"], "ai")
        self.assertIn("cổng sau nhà A", final_evt["text"])
        self.assertEqual(final_evt["links"][0]["url"], reverse("events:detail", args=[ev.pk]))
        self.assertEqual(final_evt["sources"][0]["title"], "Quy định gửi xe hội trường")
