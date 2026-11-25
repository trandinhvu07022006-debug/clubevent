"""
Xuất tập dữ liệu huấn luyện (Fine-Tuning Dataset) chuẩn JSONL cho Gemini / OpenAI
từ toàn bộ dữ liệu sạch (Zero PII) của trang web:
  - AIInteractionLog (tương tác Chatbot được đánh giá 👍)
  - ClubKnowledge (Kho tri thức RAG) & Department (Các Ban chuyên môn)
  - AIPromptProfile (Các ví dụ Few-Shot chuẩn của 5 modun)
  - Event & Task (Truyền thông sự kiện & Phân rã công việc)
  - EventPostMortem (Báo cáo tổng kết sự kiện)

Chạy:
  python manage.py export_finetune_dataset --format gemini --module all --output aiassist/datasets/kmg_finetune_gemini.jsonl
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from aiassist.models import (AIInteractionLog, AIPromptProfile, ClubKnowledge,
                             FeedbackRating)


def build_finetune_records(fmt: str = "gemini", module: str = "all",
                           include_unrated: bool = False) -> list[dict]:
    """Tạo danh sách bản ghi huấn luyện sạch (Zero PII) theo định dạng Gemini hoặc OpenAI."""
    pairs: list[tuple[str, str, str]] = []

    if module in ("all", "chatbot"):
        qs = AIInteractionLog.objects.exclude(answer_preview="")
        qs = qs.exclude(feedback=FeedbackRating.DOWN) if include_unrated else qs.filter(feedback=FeedbackRating.UP)
        for log in qs.order_by("-created_at")[:300]:
            pairs.append((
                "Bạn là trợ lý hỏi đáp thân thiện của KMG Club.",
                log.question,
                log.answer_preview,
            ))

        # Kho tri thức CLB (RAG -> Q&A training pairs)
        for kb in ClubKnowledge.objects.filter(is_active=True).order_by("priority", "id"):
            pairs.append((
                "Bạn là trợ lý hỏi đáp thân thiện của KMG Club. Chỉ trả lời dựa trên thông tin chính thức của CLB.",
                f"Cho mình hỏi về {kb.title.lower()}?",
                kb.content.strip(),
            ))

        # Thông tin các Ban chuyên môn thực tế
        from organizing.models import Department
        for dept in Department.objects.all().order_by("order", "id"):
            if dept.description:
                pairs.append((
                    "Bạn là trợ lý hỏi đáp thân thiện của KMG Club.",
                    f"{dept.name} trong CLB phụ trách những việc gì?",
                    f"{dept.name} phụ trách: {dept.description.strip()}",
                ))

    if module in ("all", "marketing"):
        from events.models import Event, EventStatus, EventVisibility
        events = (Event.objects
                  .filter(visibility=EventVisibility.PUBLIC)
                  .exclude(status=EventStatus.DRAFT)
                  .exclude(description="")[:100])
        for ev in events:
            pairs.append((
                "Bạn là chuyên viên truyền thông sự kiện của KMG Club.",
                f"Viết mô tả hấp dẫn cho sự kiện '{ev.name}' tại {ev.location} (sức chứa {ev.capacity}).",
                ev.description.strip(),
            ))

    if module in ("all", "tasks"):
        from events.models import Event, EventStatus, EventVisibility
        events_with_tasks = (Event.objects
                             .filter(visibility=EventVisibility.PUBLIC)
                             .exclude(status=EventStatus.DRAFT)
                             .prefetch_related("tasks__department")[:50])
        for ev in events_with_tasks:
            task_list = list(ev.tasks.all()[:10])
            if not task_list:
                continue
            out_tasks = [
                {
                    "title": t.title,
                    "department": t.department.name if t.department else "",
                    "priority": t.priority,
                    "note": t.description[:150] if t.description else "",
                }
                for t in task_list
            ]
            pairs.append((
                "Bạn là chuyên gia điều phối tổ chức sự kiện CLB sinh viên.",
                f"Đề xuất công việc chuẩn bị cho sự kiện '{ev.name}' tại {ev.location} (quy mô {ev.capacity} người).",
                json.dumps({"tasks": out_tasks}, ensure_ascii=False),
            ))

    if module in ("all", "postmortem"):
        from organizing.models import EventPostMortem
        for pm in EventPostMortem.objects.select_related("event").exclude(executive_summary="")[:100]:
            stats = pm.stats_snapshot or {}
            inp = (
                f"Lập báo cáo điều hành cho sự kiện '{pm.event.name}': "
                f"check-in {stats.get('attendance_rate', 0)}%, "
                f"cân đối {stats.get('balance', 0)}đ, "
                f"đánh giá {stats.get('avg_rating', 0)}/5 sao."
            )
            out = json.dumps({
                "executive_summary": pm.executive_summary,
                "highlights": pm.highlights,
                "financial_analysis": pm.financial_analysis,
                "feedback_analysis": pm.feedback_analysis,
                "lessons_learned": pm.lessons_learned,
                "action_items": pm.action_items,
            }, ensure_ascii=False)
            pairs.append((
                "Bạn là Cố vấn Điều hành và Quản lý Sự kiện KMG Club.",
                inp,
                out,
            ))

    if module in ("all", "proposals"):
        from programs.models import DepartmentProposal
        for prop in DepartmentProposal.objects.select_related("department").exclude(summary="")[:100]:
            pairs.append((
                "Bạn là Cố vấn thẩm định đề xuất hoạt động CLB sinh viên.",
                f"Thẩm định đề xuất '{prop.title}' của {prop.department.name}: {prop.summary[:300]}",
                f"Đề xuất '{prop.title}' thuộc {prop.department.name} với mục tiêu: {(prop.objectives or prop.summary)[:300]}",
            ))

    if module == "all":
        for prof in AIPromptProfile.objects.filter(is_active=True):
            for ex in (prof.few_shot_examples or []):
                if not isinstance(ex, dict):
                    continue
                inp = str(ex.get("input", "")).strip()
                out = str(ex.get("output", "")).strip()
                if inp and out:
                    pairs.append((
                        f"Tác vụ {prof.get_task_key_display()}. {prof.brand_voice}".strip(),
                        inp,
                        out,
                    ))

    records = []
    for sys_prompt, user_text, model_text in pairs:
        if fmt == "openai":
            records.append({
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": model_text},
                ]
            })
        else:
            records.append({
                "contents": [
                    {"role": "user", "parts": [{"text": f"{sys_prompt}\n\n{user_text}"}]},
                    {"role": "model", "parts": [{"text": model_text}]},
                ]
            })
    return records


class Command(BaseCommand):
    help = "Xuất dữ liệu huấn luyện Fine-Tuning dạng JSONL (chuẩn Gemini hoặc OpenAI)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format", choices=["gemini", "openai"], default="gemini",
            help="Định dạng JSONL đầu ra (gemini | openai).",
        )
        parser.add_argument(
            "--module", choices=["all", "chatbot", "marketing", "tasks", "postmortem", "proposals"], default="all",
            help="Chọn modun xuất dữ liệu.",
        )
        parser.add_argument(
            "--output", default="aiassist/datasets/kmg_finetune_gemini.jsonl",
            help="Đường dẫn file JSONL đầu ra.",
        )
        parser.add_argument(
            "--include-unrated", action="store_true",
            help="Bao gồm cả các mẫu chatbot chưa đánh giá.",
        )

    def handle(self, *args, **options):
        fmt = options["format"]
        module = options["module"]
        out_path = Path(options["output"])
        records = build_finetune_records(
            fmt=fmt, module=module, include_unrated=options["include_unrated"],
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else ""),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(
            f"Đã xuất {len(records)} mẫu huấn luyện ({fmt}/{module}) ra {out_path}"
        ))
