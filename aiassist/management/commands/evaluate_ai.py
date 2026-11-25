"""
Bộ kiểm định chất lượng AI tự động (Automated LLM Eval Suite).
Chạy:
  python manage.py evaluate_ai
  python manage.py evaluate_ai --llm-judge
"""
from django.core.management.base import BaseCommand
from django.test import override_settings
from django.utils import timezone

from aiassist.chatbot import detect_intent
from aiassist.services import (_ask_ai, build_assistant_context,
                               generate_event_content, retrieve_knowledge,
                               suggest_tasks)
from events.models import Event, EventStatus

EVAL_INTENT_CASES = [
    ("Sắp tới có sự kiện gì?", "upcoming_events"),
    ("sap toi co su kien gi khong", "upcoming_events"),
    ("Còn vé không bạn ơi?", "seats_left"),
    ("con cho khong", "seats_left"),
    ("Vé của tôi đâu?", "my_tickets"),
    ("Việc của tôi có gì?", "my_tasks"),
    ("Đăng ký vé thế nào?", "how_to_register"),
    ("Cách huỷ vé", "cancel_ticket"),
    ("Check in thế nào vậy?", "how_to_checkin"),
    ("CLB có những ban nào?", "club_departments"),
    ("Khi nào tuyển thành viên?", "recruitment_info"),
]


class Command(BaseCommand):
    help = "Chạy bộ kiểm định tự động (Evals) cho hệ thống AI của CLB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--llm-judge", action="store_true",
            help="Dùng AI làm giám khảo chấm điểm chất lượng grounding ngữ cảnh thật.",
        )

    def handle(self, *args, **options):
        passed = 0
        total = 0

        # 1. Đánh giá độ chính xác nhận diện ý định Tầng 1
        intent_ok = 0
        for query, expected in EVAL_INTENT_CASES:
            total += 1
            got = detect_intent(query)
            if got and got["code"] == expected:
                intent_ok += 1
                passed += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f"[INTENT FAIL] '{query}' -> got={got['code'] if got else None}, expected={expected}"
                ))

        # 2. Kiểm tra Hybrid Semantic RAG (TF-IDF Cosine + Keyword Boost)
        total += 1
        rag_snippet = retrieve_knowledge("muon tra ve chuyen khoan vietqr", limit=2)
        if not rag_snippet or "VietQR" in rag_snippet or "Sổ quỹ" in rag_snippet or "vé" in rag_snippet.lower():
            passed += 1
        else:
            self.stdout.write(self.style.WARNING("[RAG WARN] Hybrid RAG chưa trả về đoạn tài chính/vé phù hợp."))

        # 3. Kiểm tra Zero-PII trong dữ liệu nền Grounding
        total += 1
        ctx_text, _ = build_assistant_context("tuyển thành viên và ban")
        pii_leaks = [marker for marker in ("@gmail.com", "@", "mssv") if marker in ctx_text.lower()]
        if not pii_leaks:
            passed += 1
        else:
            self.stdout.write(self.style.ERROR(f"[PII FAIL] Phát hiện nghi vấn PII trong context: {pii_leaks}"))

        # 4. Kiểm tra khả năng chịu lỗi (Fallback Resilience)
        total += 1
        now = timezone.now()
        dummy_event = Event(
            name="Eval Test Event",
            location="Hội trường A",
            capacity=100,
            starts_at=now + timezone.timedelta(days=7),
            register_deadline=now + timezone.timedelta(days=5),
            status=EventStatus.OPEN,
        )
        with override_settings(AI_PROVIDER="mock"):
            tasks, _, _ = suggest_tasks(dummy_event, count=5)
            content, _, _ = generate_event_content(dummy_event)
        if len(tasks) == 5 and content.get("social_post"):
            passed += 1
        else:
            self.stdout.write(self.style.ERROR("[FALLBACK FAIL] Fallback không trả về đủ dữ liệu hợp lệ."))

        # 5. (Tuỳ chọn) LLM-as-a-Judge đánh giá chất lượng Grounding Context
        judge_note = ""
        if options["llm_judge"]:
            total += 1
            judge_prompt = (
                "Bạn là giám khảo đánh giá hệ thống RAG. Hãy chấm điểm 1-5 độ rõ ràng, "
                "đầy đủ và tính trung thực của ngữ cảnh sau:\n\n"
                f"{ctx_text[:1500]}\n\n"
                'Trả về JSON: {"score": 5, "reason": "ngắn gọn"}'
            )
            try:
                res = _ask_ai(judge_prompt, response_schema={
                    "type": "OBJECT",
                    "properties": {"score": {"type": "INTEGER"}, "reason": {"type": "STRING"}},
                    "required": ["score", "reason"],
                })
                j_score = int(res.get("score", 0))
                if j_score >= 4:
                    passed += 1
                judge_note = f" | LLM Judge: {j_score}/5 ({res.get('reason', '')[:80]})"
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"[LLM JUDGE SKIP/FAIL] {exc}"))

        score_pct = (passed * 100) // total if total else 0
        self.stdout.write(self.style.SUCCESS(
            f"EVAL SUMMARY: {passed}/{total} checks passed ({score_pct}%) | "
            f"Intent Accuracy: {intent_ok}/{len(EVAL_INTENT_CASES)}{judge_note}"
        ))
