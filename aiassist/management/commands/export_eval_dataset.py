"""
Xuất nhật ký đã được đánh giá ra JSONL, dùng để rà lỗi và bổ sung golden set.

Đây KHÔNG phải dữ liệu fine-tune: không kèm dữ liệu nền (grounding) và chứa
thông tin thay đổi theo thời gian (số vé, lịch).

Chạy:
  python manage.py export_eval_dataset --output eval_dataset.jsonl
  python manage.py export_eval_dataset --only-down
"""
from pathlib import Path

from django.core.management.base import BaseCommand

from aiassist.eval_data import to_jsonl
from aiassist.models import AIInteractionLog, FeedbackRating


class Command(BaseCommand):
    help = "Xuất nhật ký AI đã đánh giá ra JSONL để đánh giá chất lượng."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="eval_dataset.jsonl",
                            help="Đường dẫn file JSONL đầu ra.")
        parser.add_argument("--only-down", action="store_true",
                            help="Chỉ lấy các câu bị 👎 (cần xem trước tiên).")
        parser.add_argument("--limit", type=int, default=500,
                            help="Số dòng tối đa, mới nhất trước.")

    def handle(self, *args, **options):
        ratings = [FeedbackRating.DOWN]
        if not options["only_down"]:
            ratings.append(FeedbackRating.UP)
        logs = list(AIInteractionLog.objects.filter(feedback__in=ratings)
                    .order_by("-created_at")[:max(options["limit"], 0)])
        out_path = Path(options["output"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(to_jsonl(logs), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Đã xuất {len(logs)} dòng ra {out_path}"))
