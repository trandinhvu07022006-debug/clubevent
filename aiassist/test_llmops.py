"""Unit test cho quy trình LLMOps: RAG Kho tri thức, Prompt Registry, Feedback Loop, Evals & JSONL."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, EventVisibility
from organizing.models import Department, EventPostMortem
from recruitment.models import RecruitmentRound

from .chatbot import answer, detect_intent
from .models import (AIInteractionLog, AIPromptProfile, AITaskKey,
                     ClubKnowledge, FeedbackRating, KnowledgeCategory)
from .services import (analyze_club_operations, build_assistant_context,
                       retrieve_knowledge, review_proposal_with_ai,
                       summarize_social_feed)


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
        # Tri thức không liên quan thì không được đưa vào ngữ cảnh
        self.assertNotIn("KHO TRI THỨC & FAQ CLB", ctx)

        ctx_kb, _ = build_assistant_context("chuyển nhượng vé thế nào")
        self.assertIn("KHO TRI THỨC & FAQ CLB", ctx_kb)

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
        self.assertIn("feedback_token", data)

        fb_resp = self.client.post(
            reverse("aiassist:chat_feedback_api"),
            data=json.dumps({"token": data["feedback_token"], "rating": "UP",
                             "note": "Rất rõ ràng"}),
            content_type="application/json",
        )
        self.assertEqual(fb_resp.status_code, 200)
        log = AIInteractionLog.objects.get()
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
            self.assertTrue(len(lines) >= 10)
            row = json.loads(lines[0])
            self.assertIn("CLB có những ban nào?", row["contents"][0]["parts"][0]["text"])

            eval_file = Path(tmpdir) / "eval.jsonl"
            call_command("export_eval_dataset", output=str(eval_file))
            eval_lines = eval_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(eval_lines), 1)
            eval_row = json.loads(eval_lines[0])
            self.assertEqual(eval_row["question"], "CLB có những ban nào?")
            self.assertEqual(eval_row["rating"], "UP")

    def test_seed_populates_all_5_ai_modules(self):
        call_command("seed_ai_knowledge")
        self.assertEqual(AIPromptProfile.objects.count(), len(AITaskKey.values))
        self.assertTrue(ClubKnowledge.objects.count() >= 5)

    def test_ai_studio_permissions_and_actions(self):
        guest = User.objects.create_user(username="g_studio", password="x", mssv="GS1", role=Role.GUEST)
        lead = User.objects.create_user(username="l_studio", password="x", mssv="LS1", role=Role.LEAD)

        studio_url = reverse("aiassist:studio")
        self.client.force_login(guest)
        self.assertEqual(self.client.get(studio_url).status_code, 403)

        self.client.force_login(lead)
        resp = self.client.get(studio_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Trung tâm Đánh giá")

        eval_exp = self.client.get(reverse("aiassist:studio_eval_export") + "?only_down=1")
        self.assertEqual(eval_exp.status_code, 200)
        self.assertIn("application/jsonl", eval_exp["Content-Type"])

        # Thêm tri thức từ UI Studio
        self.client.post(studio_url, {
            "action": "add_kb",
            "title": "Lịch tập định kỳ",
            "category": KnowledgeCategory.GENERAL,
            "keywords": "lich tap, phong nhac",
            "content": "CLB tập định kỳ tối thứ 4 hàng tuần.",
            "priority": 2,
        })
        self.assertTrue(ClubKnowledge.objects.filter(title="Lịch tập định kỳ").exists())

        # Lưu profile modun suggest_tasks từ UI Studio
        self.client.post(studio_url, {
            "action": "save_profile",
            "task_key": AITaskKey.SUGGEST_TASKS,
            "brand_voice": "Chuyên nghiệp và sát thực tế.",
            "extra_instructions": "Ưu tiên phân việc rõ người nhận.",
            "few_shot_json": '[{"input": "Show 100 khách", "output": "Chuẩn bị 2 mic không dây"}]',
            "is_active": "on",
        })
        prof = AIPromptProfile.objects.get(task_key=AITaskKey.SUGGEST_TASKS)
        self.assertEqual(prof.brand_voice, "Chuyên nghiệp và sát thực tế.")
        self.assertEqual(len(prof.few_shot_examples), 1)

        # Chạy Eval Suite & Run Pipeline từ UI
        eval_resp = self.client.post(reverse("aiassist:studio_eval"))
        self.assertEqual(eval_resp.status_code, 302)

        with tempfile.TemporaryDirectory() as tmpdir:
            call_command("run_training_pipeline", output_dir=tmpdir)
            self.assertTrue((Path(tmpdir) / "kmg_finetune_gemini.jsonl").exists())
            self.assertTrue((Path(tmpdir) / "kmg_finetune_openai.jsonl").exists())

        # Xuất JSONL đa modun (OpenAI + Marketing + PostMortem)
        now = timezone.now()
        ev = Event.objects.create(
            name="Acoustic Đêm Hè", location="Sân khấu B", capacity=120,
            description="Đêm nhạc mùa hè rực rỡ.",
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4),
            status=EventStatus.OPEN, visibility=EventVisibility.PUBLIC,
        )
        EventPostMortem.objects.create(
            event=ev,
            executive_summary="Sự kiện thành công tốt đẹp.",
            highlights=["Đông khán giả"],
            financial_analysis="Thặng dư nhẹ.",
            feedback_analysis="4.8/5 sao.",
            lessons_learned=["Cần thêm ghế"],
            action_items=["Mở bán vé sớm hơn"],
            stats_snapshot={"attendance_rate": 90, "balance": 200000, "avg_rating": 4.8},
        )
        exp_resp = self.client.get(reverse("aiassist:studio_export") + "?format=openai&module=all")
        self.assertEqual(exp_resp.status_code, 200)
        self.assertIn("application/jsonl", exp_resp["Content-Type"])
        exported_lines = [json.loads(line) for line in exp_resp.content.decode("utf-8").strip().splitlines()]
        self.assertTrue(len(exported_lines) >= 2)
        self.assertIn("messages", exported_lines[0])

    @patch("aiassist.services._ask_ai")
    def test_kmg_module_ai_services_and_hybrid_rag(self, mock_ai):
        # 1. Hybrid TF-IDF RAG chấm điểm chính xác mục phù hợp nhất
        ClubKnowledge.objects.create(
            title="Tin nhắn mã hóa AES",
            category=KnowledgeCategory.GENERAL,
            keywords="nhan tin, ma hoa",
            content="Tin nhắn trong không gian nội bộ được bảo vệ bằng mã hóa AES-256-GCM.",
            priority=10,
        )
        rag_res = retrieve_knowledge("bảo mật mã hóa tin nhắn AES", limit=1)
        self.assertIn("Tin nhắn mã hóa AES", rag_res)

        # 2. Thẩm định đề xuất (Zero PII + AI & Fallback)
        from types import SimpleNamespace
        dummy_prop = SimpleNamespace(
            department=self.dept,
            title="Workshop Nhiếp ảnh Đêm nhạc",
            summary="Hướng dẫn chụp ảnh sân khấu thiếu sáng cho thành viên mới.",
            objectives="Nâng cao tay nghề media cho 20 thành viên.",
            estimated_budget=300000,
            proposed_location="Phòng B202",
            get_proposal_type_display=lambda: "Đào tạo",
        )
        mock_ai.return_value = {
            "score": 9,
            "strengths": ["Thiết thực", "Chi phí thấp"],
            "risks": ["Thiếu máy ảnh thực hành"],
            "recommendation": "Nên duyệt triển khai sớm.",
        }
        rev, used_ai, _ = review_proposal_with_ai(dummy_prop)
        self.assertTrue(used_ai)
        self.assertEqual(rev["score"], 9)

        # 3. Phân tích KPI vận hành
        mock_ai.return_value = {
            "summary": "Vận hành tốt.",
            "bottlenecks": ["RSVP chậm"],
            "action_plan": ["Nhắc lịch trước 24h"],
        }
        insight, used_ai2, _ = analyze_club_operations({"task_rate": 85}, scope_label="Toàn CLB")
        self.assertTrue(used_ai2)
        self.assertEqual(insight["summary"], "Vận hành tốt.")

        # 4. Tóm tắt bảng tin nội bộ
        mock_ai.return_value = {
            "headline": "Tập band sôi nổi",
            "highlights": ["Chuẩn bị Acoustic #6"],
            "mood": "Hào hứng",
        }
        digest, used_ai3, _ = summarize_social_feed(["Tối nay 19h tập band tại phòng nhạc nhé mọi người!"])
        self.assertTrue(used_ai3)
        self.assertEqual(digest["mood"], "Hào hứng")

    @patch("aiassist.management.commands.evaluate_ai._ask_ai")
    def test_evaluate_ai_with_llm_judge(self, mock_judge):
        mock_judge.return_value = {"score": 5, "reason": "Đầy đủ và chính xác."}
        call_command("seed_ai_knowledge")
        call_command("evaluate_ai", llm_judge=True)
        self.assertTrue(mock_judge.called)
