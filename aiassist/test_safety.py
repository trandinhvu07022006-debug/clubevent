"""
Test cho đợt vá an toàn và chất lượng của phần AI:
  P0: không lộ dữ liệu cá nhân, không đánh giá hộ.
  P1: không nhầm "các bạn" với "các Ban", không đưa tri thức lạc đề, eval biết trượt.
  P2: gửi schema, ghi telemetry, kiểm tra Few-Shot.
"""
import importlib
import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Event, EventStatus, TicketType
from feedback.models import Feedback
from registrations.models import Ticket, TicketStatus

from . import schemas
from .chatbot import detect_intent
from .models import (AIInteractionLog, AIPromptProfile, AITaskKey,
                     ClubKnowledge, FeedbackRating)
from .privacy import redact
from .services import (_ask_ai, ask_assistant, retrieve_knowledge,
                       review_proposal_with_ai, summarize_feedback,
                       summarize_social_feed)
from .views import FEEDBACK_SALT


class RedactTests(SimpleTestCase):
    def test_masks_known_patterns(self):
        for secret in ["an.nv@gmail.com", "0912345678", "0912 345 678", "+84912345678",
                       "AT200101", "3D736DC95DBF", "001204012345"]:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, redact(f"thông tin: {secret} nhé"))

    def test_keeps_ordinary_text(self):
        text = "Đêm nhạc 19:00 ngày 20/12/2026, vé 50.000đ, phòng B201, còn 3/10 chỗ"
        self.assertEqual(redact(text), text)

    def test_masks_known_full_name_only(self):
        out = redact("Em là Nguyễn Văn An, anh cho em hỏi", names=("Nguyễn Văn An", "An"))
        self.assertEqual(out, "Em là [họ tên], anh cho em hỏi")


class PrivacyFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="an", email="an@example.com", password="x",
            full_name="Nguyễn Văn An")
        now = timezone.now()
        self.event = Event.objects.create(
            name="Đêm nhạc", location="B201", capacity=50, status=EventStatus.OPEN,
            starts_at=now + timezone.timedelta(days=7),
            register_deadline=now + timezone.timedelta(days=5))
        ticket_type = TicketType.objects.create(
            event=self.event, name="Thường", price=0, quota=50)
        self.ticket = Ticket.objects.create(
            user=self.user, event=self.event, ticket_type=ticket_type,
            status=TicketStatus.CONFIRMED)
        self.client.force_login(self.user)

    def ask(self, question, endpoint="chat_api"):
        response = self.client.post(
            reverse(f"aiassist:{endpoint}"), data=json.dumps({"question": question}),
            content_type="application/json")
        if endpoint == "chat_api":
            return response.json()
        body = b"".join(response.streaming_content).decode("utf-8")
        return json.loads(body.strip().split("\n\n")[-1].removeprefix("data: "))

    def test_ticket_code_never_reaches_ai(self):
        """Hỏi vé rồi hỏi câu lạ: mã vé không được nằm trong prompt."""
        for endpoint in ("chat_api", "chat_stream_api"):
            with self.subTest(endpoint=endpoint):
                shown = self.ask("Vé của tôi thế nào?", endpoint)
                self.assertIn(self.ticket.code, shown["text"])   # chủ vé vẫn thấy
                with patch("aiassist.services._ask_ai",
                           return_value={"answer": "ok", "event_ids": []}) as mock_ai:
                    self.ask("Gửi xe ở đâu?", endpoint)
                prompt = mock_ai.call_args.args[0]
                self.assertNotIn(self.ticket.code, prompt)
                self.assertNotIn("Vé của tôi thế nào", prompt)

    @patch("aiassist.services._ask_ai", return_value={"answer": "ok", "event_ids": []})
    def test_typed_pii_and_old_history_are_masked_before_ai(self, mock_ai):
        old_history = [{"role": "assistant", "text": f"mã {self.ticket.code}"}]
        ask_assistant("sdt em 0912345678, em là Nguyễn Văn An", history=old_history,
                      names=("Nguyễn Văn An",))
        prompt = mock_ai.call_args.args[0]
        for secret in (self.ticket.code, "0912345678", "Nguyễn Văn An"):
            self.assertNotIn(secret, prompt)

    def test_log_keeps_no_personal_answer_and_masks_question(self):
        self.ask("Vé của tôi thế nào?")
        self.ask("xin chào")
        self.ask("Em là Nguyễn Văn An, MSSV AT200101, còn vé không?")
        mine, hello, seats = AIInteractionLog.objects.order_by("pk")
        self.assertEqual(mine.answer_preview, "")
        self.assertEqual(hello.answer_preview, "")
        self.assertEqual(seats.question, "Em là [họ tên], MSSV [mssv], còn vé không?")
        self.assertIsNotNone(seats.latency_ms)

    @patch("aiassist.services._ask_ai",
           return_value={"positive": "a", "negative": "b", "suggestion": "c"})
    def test_feedback_content_is_masked(self, mock_ai):
        Feedback.objects.create(
            event=self.event, user=self.user, rating=4,
            content="Hay. Liên hệ em 0912345678 - Nguyễn Văn An")
        summarize_feedback(self.event)
        prompt = mock_ai.call_args.args[0]
        self.assertNotIn("0912345678", prompt)
        self.assertNotIn("Nguyễn Văn An", prompt)

    def test_migration_scrubs_old_rows(self):
        old = AIInteractionLog.objects.create(
            question="sdt 0912345678", intent="my_tickets",
            answer_preview=f"mã {self.ticket.code}")
        migration = importlib.import_module("aiassist.migrations.0003_scrub_existing_logs")

        class Editor:   # hàm chỉ cần schema_editor.connection.alias
            pass
        Editor.connection = connection
        migration.scrub_logs(apps, Editor)
        old.refresh_from_db()
        self.assertEqual(old.question, "sdt [sđt]")
        self.assertEqual(old.answer_preview, "")


class FeedbackSecurityTests(TestCase):
    def setUp(self):
        self.log = AIInteractionLog.objects.create(question="q", answer_preview="a")

    def rate(self, payload, client=None):
        return (client or self.client).post(
            reverse("aiassist:chat_feedback_api"), data=json.dumps(payload),
            content_type="application/json")

    def token(self):
        return signing.dumps(self.log.pk, salt=FEEDBACK_SALT)

    def test_raw_id_is_rejected(self):
        self.assertEqual(self.rate({"log_id": self.log.pk, "rating": "DOWN"}).status_code, 403)
        self.assertEqual(self.rate({"token": str(self.log.pk), "rating": "DOWN"}).status_code, 403)
        self.log.refresh_from_db()
        self.assertEqual(self.log.feedback, FeedbackRating.NONE)

    def test_token_works_only_once(self):
        token = self.token()
        self.assertEqual(self.rate({"token": token, "rating": "UP"}).status_code, 200)
        self.assertEqual(self.rate({"token": token, "rating": "DOWN"}, Client()).status_code, 409)
        self.log.refresh_from_db()
        self.assertEqual(self.log.feedback, FeedbackRating.UP)

    def test_expired_token_is_rejected(self):
        with patch("django.core.signing.time.time", return_value=0):
            token = self.token()
        self.assertEqual(self.rate({"token": token, "rating": "UP"}).status_code, 403)


class MatchingTests(TestCase):
    def test_people_ban_is_not_department(self):
        cases = {
            "Các bạn ơi còn vé không?": "seats_left",
            "cac ban oi con ve khong": "seats_left",
            "Các bạn ơi mình muốn huỷ vé": "cancel_ticket",
            "CLB có những ban nào?": "club_departments",
            "Các ban chuyên môn của CLB": "club_departments",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(detect_intent(question)["code"], expected)
        self.assertIsNone(detect_intent("Bạn nào biết gửi xe ở đâu?"))

    def test_decomposed_unicode_is_handled(self):
        """macOS có thể gửi chữ dạng tách dấu (NFD)."""
        import unicodedata
        question = unicodedata.normalize("NFD", "Các bạn ơi còn vé không?")
        self.assertEqual(detect_intent(question)["code"], "seats_left")

    def test_retrieval_returns_nothing_for_off_topic(self):
        ClubKnowledge.objects.create(
            title="Nội quy quỹ", keywords="quy, dong phi",
            content="Thành viên đóng quỹ theo tháng.",
            visibility="PUBLIC")
        for question in ("thời tiết Tokyo hôm nay", "xyz qqq", "hi"):
            with self.subTest(question=question):
                self.assertEqual(retrieve_knowledge(question), "")
        self.assertIn("Nội quy quỹ", retrieve_knowledge("đóng phí quỹ thế nào"))


class EvalCommandTests(TestCase):
    def test_passes_and_leaves_database_untouched(self):
        kept = ClubKnowledge.objects.create(title="Thật", content="x")
        call_command("evaluate_ai", stdout=io.StringIO())
        self.assertEqual(list(ClubKnowledge.objects.all()), [kept])
        kept.refresh_from_db()
        self.assertTrue(kept.is_active)

    def test_fails_when_intents_break(self):
        with patch("aiassist.management.commands.evaluate_ai.detect_intent",
                   return_value=None):
            with self.assertRaises(CommandError):
                call_command("evaluate_ai", stdout=io.StringIO())


@override_settings(AI_PROVIDER="gemini", AI_API_KEY="test-key")
class StructuredOutputTests(TestCase):
    def sent_config(self, **kwargs):
        reply = {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}
        with patch("aiassist.services.urllib.request.urlopen",
                   return_value=io.BytesIO(json.dumps(reply).encode())) as mock_open:
            _ask_ai("x", **kwargs)
        return json.loads(mock_open.call_args.args[0].data)["generationConfig"]

    def test_schema_is_sent_in_response_format(self):
        config = self.sent_config(response_schema=schemas.ASSISTANT)
        self.assertEqual(config["responseFormat"]["text"]["schema"], schemas.ASSISTANT)
        self.assertNotIn("responseMimeType", config)

    def test_without_schema_keeps_json_mode(self):
        config = self.sent_config()
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertNotIn("responseFormat", config)

    def test_rejected_schema_falls_back_once(self):
        bad = urllib.error.HTTPError("https://ai.test", 400, "bad", {}, None)
        with patch("aiassist.services._call_gemini",
                   side_effect=[bad, '{"ok": true}']) as mock_call:
            self.assertEqual(_ask_ai("x", response_schema=schemas.ASSISTANT), {"ok": True})
        self.assertEqual(mock_call.call_count, 2)
        self.assertNotIn("response_schema", mock_call.call_args.kwargs)

    def test_assistant_sends_its_schema(self):
        with patch("aiassist.services._ask_ai",
                   return_value={"answer": "ok", "event_ids": []}) as mock_ai:
            ask_assistant("gửi xe ở đâu")
        self.assertEqual(mock_ai.call_args.kwargs["response_schema"], schemas.ASSISTANT)

    @patch("aiassist.services._ask_ai", return_value={"answer": "ok", "event_ids": []})
    def test_log_records_model_and_prompt_version(self, mock_ai):
        def ask():
            data = self.client.post(
                reverse("aiassist:chat_api"), data='{"question": "gửi xe ở đâu"}',
                content_type="application/json").json()
            self.assertNotIn("meta", data)      # không lộ thông tin nội bộ
            return AIInteractionLog.objects.order_by("-pk").first()

        first = ask()
        AIPromptProfile.objects.create(task_key=AITaskKey.CHATBOT, brand_voice="Vui vẻ")
        second = ask()
        self.assertTrue(first.model_name)
        self.assertEqual(len(first.prompt_version), 12)
        self.assertNotEqual(first.prompt_version, second.prompt_version)


class PromptProfileValidationTests(TestCase):
    def profile(self, examples):
        return AIPromptProfile(task_key=AITaskKey.CHATBOT, few_shot_examples=examples)

    def test_rejects_bad_examples(self):
        good = {"input": "a", "output": "b"}
        for bad in ({"input": "a"}, [{"input": "a"}], ["chuỗi"],
                    [{"input": " ", "output": "b"}], [good] * 4):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.profile(bad).full_clean()

    def test_accepts_good_and_empty(self):
        self.profile([{"input": "a", "output": "b"}]).full_clean()
        empty = self.profile(None)
        empty.full_clean()
        self.assertEqual(empty.few_shot_examples, [])


class PlatformAIPrivacyTests(SimpleTestCase):
    """Chữ người dùng tự gõ ở Đề xuất và Bảng tin cũng phải được che."""
    databases = {"default"}   # get_prompt_addendum đọc cấu hình trong DB
    SECRETS = ("0912345678", "an.nv@gmail.com", "Nguyễn Văn An")
    TEXT = "Liên hệ Nguyễn Văn An, 0912345678, an.nv@gmail.com"

    def assert_clean(self, mock_ai):
        prompt = mock_ai.call_args.args[0]
        for secret in self.SECRETS:
            self.assertNotIn(secret, prompt)

    @patch("aiassist.services._ask_ai", return_value={})
    def test_proposal_review(self, mock_ai):
        proposal = SimpleNamespace(
            department=SimpleNamespace(name="Ban Truyền thông"),
            proposer=SimpleNamespace(full_name="Nguyễn Văn An"),
            title="Workshop", summary=self.TEXT, objectives=self.TEXT,
            estimated_budget=0, proposed_location="B201",
            get_proposal_type_display=lambda: "Đào tạo")
        review_proposal_with_ai(proposal)
        self.assert_clean(mock_ai)

    @patch("aiassist.services._ask_ai", return_value={})
    def test_social_digest(self, mock_ai):
        summarize_social_feed([self.TEXT], names=("Nguyễn Văn An",))
        self.assert_clean(mock_ai)


class ExportFinetuneIsolationTests(TestCase):
    def test_export_excludes_internal_events_unapproved_proposals_and_pii(self):
        from aiassist.management.commands.export_finetune_dataset import build_finetune_records
        from events.models import EventVisibility
        from organizing.models import EventPostMortem
        from organization.models import Department
        from programs.models import DepartmentProposal, ProposalStatus

        user = User.objects.create_user(
            username="exp_user", password="x", full_name="Trần Thị Minh", email="minh@kmg.vn"
        )
        dept = Department.objects.create(name="Ban Kỹ thuật", code="KY_THUAT", slug="ky-thuat")
        now = timezone.now()

        internal_ev = Event.objects.create(
            name="Họp nội bộ mật",
            location="Phòng B302",
            starts_at=now - timezone.timedelta(days=2),
            register_deadline=now - timezone.timedelta(days=3),
            status=EventStatus.DONE,
            visibility=EventVisibility.INTERNAL,
        )
        EventPostMortem.objects.create(
            event=internal_ev,
            executive_summary="Báo cáo nội bộ tuyệt mật 0912345678",
        )

        public_ev = Event.objects.create(
            name="Đêm nhạc công khai",
            location="Sảnh A",
            starts_at=now - timezone.timedelta(days=1),
            register_deadline=now - timezone.timedelta(days=2),
            status=EventStatus.DONE,
            visibility=EventVisibility.PUBLIC,
        )
        EventPostMortem.objects.create(
            event=public_ev,
            executive_summary="Tổng kết thành công, liên hệ 0987654321",
        )

        DepartmentProposal.objects.create(
            code="DX-DRAFT-1",
            title="Đề xuất nháp bí mật",
            department=dept,
            proposer=user,
            summary="Kế hoạch chưa duyệt",
            status=ProposalStatus.DRAFT,
        )
        DepartmentProposal.objects.create(
            code="DX-APP-1",
            title="Workshop công khai",
            department=dept,
            proposer=user,
            summary="Phụ trách Trần Thị Minh sđt 0912345678",
            objectives="Đào tạo thành viên mới",
            status=ProposalStatus.APPROVED,
        )
        AIInteractionLog.objects.create(
            question="Sắp tới có sự kiện gì?",
            intent="upcoming_events",
            source="rules",
            answer_preview="INTERNAL-EVENT-SECRET",
            feedback=FeedbackRating.UP,
        )

        records = build_finetune_records(fmt="openai", module="all", include_unrated=False)
        blob = json.dumps(records, ensure_ascii=False)
        self.assertNotIn("Họp nội bộ mật", blob)
        self.assertNotIn("Báo cáo nội bộ tuyệt mật", blob)
        self.assertNotIn("Đề xuất nháp bí mật", blob)
        self.assertNotIn("INTERNAL-EVENT-SECRET", blob)
        self.assertNotIn("0912345678", blob)
        self.assertNotIn("0987654321", blob)
        self.assertNotIn("Trần Thị Minh", blob)
        self.assertIn("Workshop công khai", blob)
