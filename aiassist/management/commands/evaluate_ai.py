"""
Bộ kiểm định chất lượng AI tự động (Automated LLM Eval Suite).
Chạy: python manage.py evaluate_ai
"""
from django.core.management.base import BaseCommand
from django.test import override_settings
from django.utils import timezone

from aiassist.chatbot import detect_intent
from aiassist.services import (build_assistant_context, generate_event_content,
                               generate_event_postmortem, suggest_tasks)
from events.models import Event, EventStatus

EVAL_INTENT_CASES = [
    ("Sắp tới có sự kiện gì?", "upcoming_events"),
    ("sap toi co su kien gi khong", "upcoming_events"),
    ("Còn vé không bạn ơi?", "seats_left"),
    ("con cho khong", "seats_left"),
    ("Vé của tôi đâu?", "my_tickets"),
    ("Việc của tôi có gì?", "my_tasks"),
    ("Đăng ký vé thế nào?", "how_to_register"),
    ("Check in thế nào vậy?", "how_to_checkin"),
    ("Cách huỷ vé", "cancel_ticket"),
    ("CLB có những ban nào?", "club_departments"),
    ("Khi nào tuyển thành viên?", "recruitment_info"),
]


class Command(BaseCommand):
    help = "Chạy bộ kiểm định tự động (Evals) cho hệ thống AI của CLB."

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

        # 2. Kiểm tra Zero-PII trong dữ liệu nền Grounding
        total += 1
        ctx_text, _ = build_assistant_context("tuyển thành viên và ban")
        pii_leaks = [marker for marker in ("@gmail.com", "@", "mssv") if marker in ctx_text.lower()]
        if not pii_leaks:
            passed += 1
        else:
            self.stdout.write(self.style.ERROR(f"[PII FAIL] Phát hiện nghi vấn PII trong context: {pii_leaks}"))

        # 3. Kiểm tra khả năng chịu lỗi (Fallback Resilience)
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

        score_pct = (passed * 100) // total if total else 0
        self.stdout.write(self.style.SUCCESS(
            f"EVAL SUMMARY: {passed}/{total} checks passed ({score_pct}%) | "
            f"Intent Accuracy: {intent_ok}/{len(EVAL_INTENT_CASES)}"
        ))
