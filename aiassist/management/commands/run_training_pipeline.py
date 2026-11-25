"""
Chạy trọn vẹn quy trình Huấn luyện & Tối ưu AI (LLMOps Pipeline) cho dữ liệu thực tế:
  1. Đồng bộ Kho tri thức RAG & Cấu hình Prompt cho 5 modun (seed_ai_knowledge).
  2. Tự động tổng hợp Báo cáo Post-Mortem cho các sự kiện đã kết thúc chưa có báo cáo.
  3. Chạy bộ kiểm định chất lượng (evaluate_ai) - kiểm tra Intent & Zero-PII.
  4. Xuất tập dữ liệu huấn luyện sạch (JSONL chuẩn Gemini & OpenAI) ra aiassist/datasets/.
  5. (Tuỳ chọn) Gửi job Supervised Fine-Tuning lên Gemini API nếu truyền --submit-gemini.

Chạy:
  python manage.py run_training_pipeline
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from aiassist.management.commands.export_finetune_dataset import build_finetune_records
from aiassist.services import generate_event_postmortem
from events.models import Event, EventStatus
from organizing.models import EventPostMortem


def submit_gemini_tuning_job(records: list[dict], display_name: str = "kmg-clubevent-assistant") -> dict:
    """
    Gửi tập dữ liệu mẫu (text_input -> output) lên Google Gemini Tuning API v1beta.
    Chỉ gọi khi người quản trị chủ động kích hoạt --submit-gemini.
    """
    if not settings.AI_API_KEY:
        raise RuntimeError("Chưa cấu hình AI_API_KEY trong file .env.")

    examples = []
    for row in records[:100]:
        contents = row.get("contents") or []
        if len(contents) < 2:
            continue
        user_txt = contents[0]["parts"][0]["text"][:4000]
        model_txt = contents[1]["parts"][0]["text"][:4000]
        if user_txt and model_txt:
            examples.append({"text_input": user_txt, "output": model_txt})

    if len(examples) < 10:
        raise RuntimeError(f"Cần tối thiểu 10 mẫu để tạo Tuning Job (hiện có {len(examples)} mẫu).")

    base_model = settings.AI_MODEL or "models/gemini-1.5-flash-001-tuning"
    if not base_model.startswith("models/"):
        base_model = f"models/{base_model}"

    payload = json.dumps({
        "display_name": display_name,
        "base_model": base_model,
        "tuning_task": {
            "hyperparameters": {
                "batch_size": 4,
                "learning_rate": 0.001,
                "epoch_count": 3,
            },
            "training_data": {
                "examples": {"examples": examples},
            },
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/tunedModels",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.AI_API_KEY,
        },
    )
    with urllib.request.urlopen(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Command(BaseCommand):
    help = "Thực thi toàn bộ quy trình LLMOps huấn luyện và chuẩn hoá dữ liệu AI cho trang web."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir", default="aiassist/datasets",
            help="Thư mục lưu file JSONL đầu ra.",
        )
        parser.add_argument(
            "--submit-gemini", action="store_true",
            help="Gửi trực tiếp job Supervised Fine-Tuning lên Gemini API.",
        )

    def handle(self, *args, **options):
        out_dir = Path(options["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write("=== BƯỚC 1: Đồng bộ Kho tri thức RAG & 5 Modun Prompt ===")
        call_command("seed_ai_knowledge", stdout=self.stdout)

        self.stdout.write("=== BƯỚC 2: Tổng hợp Báo cáo Post-Mortem cho sự kiện đã kết thúc ===")
        done_events = Event.objects.filter(status=EventStatus.DONE)
        pm_created = 0
        for ev in done_events:
            if EventPostMortem.objects.filter(event=ev).exists():
                continue
            data, stats, md, used_ai, err = generate_event_postmortem(ev)
            EventPostMortem.objects.create(
                event=ev,
                executive_summary=data.get("executive_summary", ""),
                highlights=data.get("highlights", []),
                financial_analysis=data.get("financial_analysis", ""),
                feedback_analysis=data.get("feedback_analysis", ""),
                lessons_learned=data.get("lessons_learned", []),
                action_items=data.get("action_items", []),
                stats_snapshot=stats,
                markdown_content=md,
            )
            pm_created += 1
            mode = "AI" if used_ai else f"Fallback ({err})"
            self.stdout.write(f"  + Đã lập báo cáo cho '{ev.name}' [{mode}]")
        if pm_created == 0:
            self.stdout.write("  + Tất cả sự kiện DONE đều đã có báo cáo.")

        self.stdout.write("=== BƯỚC 3: Chạy Bộ kiểm định Chất lượng (evaluate_ai) ===")
        call_command("evaluate_ai", stdout=self.stdout)

        self.stdout.write("=== BƯỚC 4: Xuất Tập Dữ liệu Huấn luyện (Gemini & OpenAI JSONL) ===")
        gemini_path = out_dir / "kmg_finetune_gemini.jsonl"
        openai_path = out_dir / "kmg_finetune_openai.jsonl"
        call_command("export_finetune_dataset", format="gemini", module="all",
                     include_unrated=True, output=str(gemini_path), stdout=self.stdout)
        call_command("export_finetune_dataset", format="openai", module="all",
                     include_unrated=True, output=str(openai_path), stdout=self.stdout)

        if options["submit_gemini"]:
            self.stdout.write("=== BƯỚC 5: Gửi Gemini Supervised Fine-Tuning Job ===")
            records = build_finetune_records(fmt="gemini", module="all", include_unrated=True)
            try:
                res = submit_gemini_tuning_job(records)
                self.stdout.write(self.style.SUCCESS(
                    f"Đã tạo Tuning Job: {res.get('name', res)}"
                ))
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
                self.stdout.write(self.style.WARNING(
                    f"Không gửi được Tuning Job tới Gemini API: {exc}"
                ))
        else:
            self.stdout.write(
                "=== HOÀN TẤT PIPELINE ===\n"
                f"File sẵn sàng train:\n  - {gemini_path}\n  - {openai_path}"
            )
