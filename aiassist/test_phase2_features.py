"""Regression tests for Phase 1/2 hardening: migrations, RAG citations, intents, and lead rate limits."""
import importlib
import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, UserProfile
from aiassist.chatbot import detect_intent
from aiassist.models import AIInteractionLog, ClubKnowledge, KnowledgeCategory
from aiassist.services import retrieve_knowledge_with_sources
from events.models import Event, EventStatus

User = get_user_model()


class IntentAndHybridRetrievalTests(TestCase):
    def setUp(self):
        self.transfer_kb = ClubKnowledge.objects.create(
            title="Quy trình tham gia và check-in sự kiện",
            category=KnowledgeCategory.EVENT,
            keywords="tham gia, check in, ma qr, ve dien tu, chuyen nhuong ve",
            content="Hệ thống hỗ trợ chuyển nhượng vé hợp lệ trước giờ diễn ra.",
            visibility="PUBLIC",
            priority=1,
            is_active=True,
        )
        ClubKnowledge.objects.create(
            title="Đánh giá định kỳ 7 tiêu chí",
            category=KnowledgeCategory.RULE,
            keywords="danh gia, 7 tieu chi",
            content="Đánh giá theo 7 tiêu chí.",
            visibility="PUBLIC",
            priority=2,
            is_active=True,
        )

    def test_blind_intent_regressions_fixed(self):
        self.assertEqual(
            detect_intent("lỡ đăng ký nhầm sự kiện, giờ cancel sao ta")["code"],
            "cancel_ticket",
        )
        self.assertEqual(
            detect_intent("hi bạn, chúc buổi tối vui vẻ nhé")["code"],
            "greeting",
        )

    def test_hybrid_bm25_retrieval_returns_sources_and_blocks_noise(self):
        text, sources = retrieve_knowledge_with_sources("chuyển vé cho bạn khác")
        self.assertIn("chuyển nhượng vé", text)
        self.assertEqual(
            sources,
            [{
                "title": self.transfer_kb.title,
                "category": self.transfer_kb.get_category_display(),
                "visibility": "PUBLIC",
            }],
        )
        noise_text, noise_sources = retrieve_knowledge_with_sources("tỷ giá đô hôm nay")
        self.assertEqual(noise_text, "")
        self.assertEqual(noise_sources, [])


class ChatSourcesStreamTests(TransactionTestCase):
    @override_settings(AI_PROVIDER="mock")
    def test_chat_api_and_stream_include_sources(self):
        kb_title = "Quy trình tham gia và check-in sự kiện"

        def fake_ai(*args, **kwargs):
            return {
                "text": "Bạn có thể chuyển nhượng vé trước giờ diễn ra.",
                "intent": "ai",
                "source": "ai",
                "links": [],
                "sources": [{"title": kb_title, "category": "Sự kiện"}],
                "meta": {"model_name": "mock"},
            }

        with patch("aiassist.chatbot._answer_with_ai", side_effect=fake_ai):
            resp = self.client.post(
                reverse("aiassist:chat_api"),
                data=json.dumps({"question": "chuyển vé cho bạn khác được không"}),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["sources"][0]["title"], kb_title)

            stream_resp = self.client.post(
                reverse("aiassist:chat_stream_api"),
                data=json.dumps({"question": "chuyển vé cho bạn khác được không"}),
                content_type="application/json",
            )
            try:
                raw = b"".join(stream_resp.streaming_content).decode("utf-8")
            finally:
                stream_resp.close()
            done_payload = json.loads(raw.strip().split("\n\n")[-1].removeprefix("data: "))
            self.assertEqual(done_payload["sources"][0]["title"], kb_title)


class ScrubMigrationAndEvalFlagTests(TestCase):
    def test_scrub_internal_event_logs_migration(self):
        mod = importlib.import_module("aiassist.migrations.0005_scrub_internal_event_logs")
        internal_log = AIInteractionLog.objects.create(
            question="Sắp tới có gì?",
            intent="upcoming_events",
            source="rules",
            answer_preview="Sự kiện nội bộ bí mật",
        )
        public_log = AIInteractionLog.objects.create(
            question="Check-in thế nào?",
            intent="how_to_checkin",
            source="rules",
            answer_preview="Mở QR để check-in.",
        )
        mod.scrub_internal_event_logs(apps, SimpleNamespace(connection=connection))
        internal_log.refresh_from_db()
        public_log.refresh_from_db()
        self.assertEqual(internal_log.answer_preview, "")
        self.assertEqual(public_log.answer_preview, "Mở QR để check-in.")

    def test_evaluate_ai_with_migrate_flag_triggers_migrate(self):
        out = StringIO()
        with patch("aiassist.management.commands.evaluate_ai.call_command") as mock_cmd:
            call_command("evaluate_ai", "--with-migrate", stdout=out)
        mock_cmd.assert_called_once_with("migrate", verbosity=0, interactive=False)
        output = out.getvalue()
        self.assertIn("EVAL ĐẠT", output)
        self.assertIn("Ý định [blind]: 50/50 (100%)", output)


class LeadAiRateLimitTests(TestCase):
    def setUp(self):
        self.lead = User.objects.create_user("lead_rl", password="x", role=Role.LEAD)
        now = timezone.now()
        self.event = Event.objects.create(
            name="RL Test Event",
            location="A1",
            capacity=50,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=3),
            status=EventStatus.OPEN,
            created_by=self.lead,
        )
        self.client.force_login(self.lead)

    def test_events_media_ai_rate_limited(self):
        url = reverse("events:media_ai", args=[self.event.pk])
        with (
            patch("core.security.is_rate_limited", return_value=True),
            patch("aiassist.services.generate_event_content") as gen_mock,
        ):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        gen_mock.assert_not_called()

    def test_organizing_ai_suggest_rate_limited(self):
        url = reverse("organizing:ai_suggest", args=[self.event.pk])
        with (
            patch("core.security.is_rate_limited", return_value=True),
            patch("aiassist.services.suggest_tasks") as task_mock,
        ):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        task_mock.assert_not_called()

    def test_feedback_ai_summarize_rate_limited(self):
        url = reverse("feedback:ai_summarize", args=[self.event.pk])
        with (
            patch("core.security.is_rate_limited", return_value=True),
            patch("aiassist.services.summarize_feedback") as sum_mock,
        ):
            resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        sum_mock.assert_not_called()
