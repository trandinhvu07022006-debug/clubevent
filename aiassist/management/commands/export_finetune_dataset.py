"""
Xuất tập dữ liệu huấn luyện (Fine-Tuning Dataset) chuẩn JSONL cho Gemini / OpenAI.
Chỉ lấy dữ liệu chất lượng cao (được người dùng bấm 👍 hoặc dữ liệu nghiệp vụ sạch, Zero PII).

Chạy:
  python manage.py export_finetune_dataset --format gemini --output finetune_gemini.jsonl
  python manage.py export_finetune_dataset --format openai --output finetune_openai.jsonl
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from aiassist.models import AIInteractionLog, FeedbackRating


class Command(BaseCommand):
    help = "Xuất dữ liệu huấn luyện Fine-Tuning dạng JSONL (chuẩn Gemini hoặc OpenAI)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format", choices=["gemini", "openai"], default="gemini",
            help="Định dạng JSONL đầu ra (gemini | openai).",
        )
        parser.add_argument(
            "--output", default="finetune_dataset.jsonl",
            help="Đường dẫn file JSONL đầu ra.",
        )
        parser.add_argument(
            "--include-unrated", action="store_true",
            help="Bao gồm cả các mẫu chưa đánh giá (mặc định chỉ lấy mẫu được 👍 hoặc có nội dung chuẩn).",
        )

    def handle(self, *args, **options):
        fmt = options["format"]
        out_path = Path(options["output"])
        include_unrated = options["include_unrated"]

        qs = AIInteractionLog.objects.exclude(answer_preview="")
        if not include_unrated:
            qs = qs.filter(feedback=FeedbackRating.UP)
        else:
            qs = qs.exclude(feedback=FeedbackRating.DOWN)

        records = []
        for log in qs.order_by("-created_at")[:500]:
            if fmt == "openai":
                records.append({
                    "messages": [
                        {"role": "system", "content": "Bạn là trợ lý hỏi đáp thân thiện của KMG Club."},
                        {"role": "user", "content": log.question},
                        {"role": "assistant", "content": log.answer_preview},
                    ]
                })
            else:
                records.append({
                    "contents": [
                        {"role": "user", "parts": [{"text": log.question}]},
                        {"role": "model", "parts": [{"text": log.answer_preview}]},
                    ]
                })

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else ""),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(
            f"Đã xuất {len(records)} mẫu huấn luyện ({fmt}) ra {out_path}"
        ))
