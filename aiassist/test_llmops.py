"""Unit test cho quy trình LLMOps: RAG Kho tri thức, Prompt Registry, Feedback Loop, Evals & JSONL."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from organizing.models import Department
from recruitment.models import RecruitmentRound

from .chatbot import answer, detect_intent
from .models import (AIInteractionLog, AIPromptProfile, AITaskKey,
                     ClubKnowledge, FeedbackRating, KnowledgeCategory)
from .services import build_assistant_context, retrieve_knowledge


class LLMOpsPipelineTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(
            name="Ban Truyền thông", slug="truyen-thong",
            description="Phụ trách hình ảnh, bài viết và media cho CLB.",
        )
        now = timezone.now()
        self.round = RecruitmentRound.objects.create(
            name="Tuyển thành viên Học kỳ 1",
            opens_at=now - timezone.timedelta(days=1),
            closes_at=now + timezone.timedelta(days=5),
        )
        self.kb = ClubKnowledge.objects.create(
            title="Chính sách hoàn vé",
            category=KnowledgeCategory.RULE,
            keywords="hoan ve, doi ve, chuyen nhuong",
            content="Vé đã mua có thể chuyển nhượng cho bạn khác trước giờ diễn ra sự kiện.",
            priority=1,
        )

    def test_rag_retrieves_relevant_knowledge_and_live_db_context(self):
        snippet = retrieve_knowledge("chuyển nhượng vé thế nào")
        self.assertIn("Chính sách hoàn vé", snippet)

        ctx, _ = build_assistant_context("tuyển thành viên ban truyền thông")
        self.assertIn("Ban Truyền thông", ctx)
        self.assertIn("Tuyển thành viên Học kỳ 1", ctx)
        self.assertIn("KHO TRI THỨC & FAQ CLB", ctx)

    @patch("aiassist.services._ask_ai")
    def test_prompt_registry_and_few_shot_injected(self, mock_ai):
        AIPromptProfile.objects.create(
            task_key=AITaskKey.CHATBOT,
            brand_voice="Năng động, thân thiện kiểu GenZ.",
            extra_instructions="Luôn kết thúc bằng lời chúc tốt đẹp.",
            few_shot_examples=[{"input": "CLB ở đâu?", "output": "CLB sinh hoạt tại phòng B201 bạn nhé!"}],
            is_active=True,
        )
        mock_ai.return_value = {"answer": "Chào bạn!", "event_ids": []}
        answer("Hỏi ngẫu nhiên về phòng sinh hoạt")
        prompt_sent = mock_ai.call_args[0][0]
        self.assertIn("GIỌNG VĂN THƯƠNG HIỆU CLB:", prompt_sent)
        self.assertIn("Năng động, thân thiện kiểu GenZ.", prompt_sent)
        self.assertIn("VÍ DỤ MẪU CHUẨN (FEW-SHOT):", prompt_sent)
        self.assertIn("CLB sinh hoạt tại phòng B201 bạn nhé!", prompt_sent)

    def test_new_layer1_intents_departments_and_recruitment(self):
        self.assertEqual(detect_intent("CLB có những ban nào?")["code"], "club_departments")
        self.assertEqual(detect_intent("Khi nào tuyển thành viên?")["code"], "recruitment_info")

        res_dept = answer("CLB có những ban nào?")
        self.assertEqual(res_dept["source"], "rules")
        self.assertIn("Ban Truyền thông", res_dept["text"])

        res_rec = answer("Khi nào tuyển thành viên?")
        self.assertEqual(res_rec["source"], "rules")
        self.assertIn("Tuyển thành viên Học kỳ 1", res_rec["text"])

    def test_interaction_log_and_feedback_loop_api(self):
        resp = self.client.post(
            reverse("aiassist:chat_api"),
            data='{"question": "Đăng ký vé thế nào?"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("log_id", data)

        fb_resp = self.client.post(
            reverse("aiassist:chat_feedback_api"),
            data=json.dumps({"log_id": data["log_id"], "rating": "UP", "note": "Rất rõ ràng"}),
            content_type="application/json",
        )
        self.assertEqual(fb_resp.status_code, 200)
        log = AIInteractionLog.objects.get(pk=data["log_id"])
        self.assertEqual(log.feedback, FeedbackRating.UP)
        self.assertEqual(log.feedback_note, "Rất rõ ràng")

    def test_management_commands_seed_eval_and_export_jsonl(self):
        AIInteractionLog.objects.create(
            question="CLB có những ban nào?",
            intent="club_departments",
            source="rules",
            answer_preview="CLB có Ban Truyền thông.",
            feedback=FeedbackRating.UP,
        )
        call_command("seed_ai_knowledge")
        self.assertTrue(ClubKnowledge.objects.filter(title="Giới thiệu chung về KMG Club").exists())

        call_command("evaluate_ai")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "train.jsonl"
            call_command("export_finetune_dataset", format="gemini", output=str(out_file))
            lines = out_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["contents"][0]["parts"][0]["text"], "CLB có những ban nào?")
