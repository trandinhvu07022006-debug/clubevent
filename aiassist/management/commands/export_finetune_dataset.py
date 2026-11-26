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

from aiassist.chatbot import PRIVATE_INTENTS
from aiassist.egress import DataClassification
from aiassist.models import (AIInteractionLog, AIPromptProfile, AITaskKey,
                             ClubKnowledge, FeedbackRating, KnowledgeVisibility)
from aiassist.privacy import redact


def build_finetune_records(fmt: str = "gemini", module: str = "all",
                           include_unrated: bool = False,
                           include_internal: bool = False) -> list[dict]:
    """
    Tạo bản ghi fine-tuning sạch (Zero PII).
    Mặc định (`include_internal=False`): CHỈ xuất dữ liệu PUBLIC (log PUBLIC đã che PII,
    ClubKnowledge PUBLIC, Department công khai, Event PUBLIC non-draft); cô lập hoàn toàn
    log cũ chưa phân loại (`classification=INTERNAL`), tasks, postmortem tài chính và proposals.
    """
    pairs: list[tuple[str, str, str]] = []

    if module in ("all", "chatbot"):
        qs = (AIInteractionLog.objects
              .filter(classification=DataClassification.PUBLIC.value)
              .exclude(answer_preview="")
              .exclude(intent__in=PRIVATE_INTENTS))
        qs = qs.exclude(feedback=FeedbackRating.DOWN) if include_unrated else qs.filter(feedback=FeedbackRating.UP)
        for log in qs.order_by("-created_at")[:300]:
            q_clean = redact(log.question).strip()
            a_clean = redact(log.answer_preview).strip()
            if q_clean and a_clean:
                pairs.append((
                    "Bạn là trợ lý hỏi đáp thân thiện của KMG Club.",
                    q_clean,
                    a_clean,
                ))

        # Kho tri thức CLB (chỉ lấy mục PUBLIC đã duyệt -> Q&A training pairs)
        from aiassist.models import ApprovalStatus
        for kb in ClubKnowledge.objects.filter(
            is_active=True, approval_status=ApprovalStatus.APPROVED, visibility=KnowledgeVisibility.PUBLIC
        ).order_by("priority", "id"):
            pairs.append((
                "Bạn là trợ lý hỏi đáp thân thiện của KMG Club. Chỉ trả lời dựa trên thông tin chính thức của CLB.",
                f"Cho mình hỏi về {kb.title.lower()}?",
                redact(kb.content.strip()),
            ))

        # Thông tin các Ban chuyên môn thực tế (ưu tiên organization.Department)
        from organization.models import Department as OrgDepartment
        from organizing.models import Department as LegacyDepartment
        depts = list(OrgDepartment.objects.filter(is_active=True, is_demo=False).order_by("display_order", "id"))
        if not depts:
            depts = list(LegacyDepartment.objects.all().order_by("order", "id"))
        for dept in depts:
            desc = (getattr(dept, "short_description", "") or getattr(dept, "description", "")).strip()
            if desc:
                pairs.append((
                    "Bạn là trợ lý hỏi đáp thân thiện của KMG Club.",
                    f"{dept.name} trong CLB phụ trách những việc gì?",
                    f"{dept.name} phụ trách: {redact(desc)}",
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
                redact(ev.description.strip()),
            ))

    if include_internal and module in ("all", "tasks"):
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
                    "title": redact(t.title)[:200],
                    "department": t.department.name if t.department else "",
                    "priority": t.priority,
                    "note": redact(t.description[:150]) if t.description else "",
                }
                for t in task_list
            ]
            pairs.append((
                "Bạn là chuyên gia điều phối tổ chức sự kiện CLB sinh viên.",
                f"Đề xuất công việc chuẩn bị cho sự kiện '{ev.name}' tại {ev.location} (quy mô {ev.capacity} người).",
                json.dumps({"tasks": out_tasks}, ensure_ascii=False),
            ))

    if include_internal and module in ("all", "postmortem"):
        from events.models import EventVisibility
        from organizing.models import EventPostMortem
        for pm in (EventPostMortem.objects
                   .select_related("event")
                   .filter(event__visibility=EventVisibility.PUBLIC)
                   .exclude(executive_summary="")[:100]):
            stats = pm.stats_snapshot or {}
            inp = (
                f"Lập báo cáo điều hành cho sự kiện '{pm.event.name}': "
                f"check-in {stats.get('attendance_rate', 0)}%, "
                f"đánh giá {stats.get('avg_rating', 0)}/5 sao."
            )
            out = json.dumps({
                "executive_summary": redact(pm.executive_summary),
                "highlights": [redact(str(x)) for x in (pm.highlights or [])],
                "feedback_analysis": redact(pm.feedback_analysis),
                "lessons_learned": [redact(str(x)) for x in (pm.lessons_learned or [])],
                "action_items": [redact(str(x)) for x in (pm.action_items or [])],
            }, ensure_ascii=False)
            pairs.append((
                "Bạn là Cố vấn Điều hành và Quản lý Sự kiện KMG Club.",
                inp,
                out,
            ))

    if include_internal and module in ("all", "proposals"):
        from programs.models import DepartmentProposal, ProposalStatus
        for prop in (DepartmentProposal.objects
                     .select_related("department", "proposer")
                     .filter(status=ProposalStatus.APPROVED)
                     .exclude(summary="")[:100]):
            proposer = getattr(prop, "proposer", None)
            names = tuple(filter(None, (
                getattr(proposer, "full_name", ""),
                getattr(proposer, "display_name", ""),
            )))
            title_clean = redact(prop.title, names)[:160]
            summary_clean = redact(prop.summary, names)[:300]
            obj_clean = redact((prop.objectives or prop.summary), names)[:300]
            pairs.append((
                "Bạn là Cố vấn thẩm định đề xuất hoạt động CLB sinh viên.",
                f"Thẩm định đề xuất '{title_clean}' của {prop.department.name}: {summary_clean}",
                f"Đề xuất '{title_clean}' thuộc {prop.department.name} với mục tiêu: {obj_clean}",
            ))

    if module == "all":
        public_task_keys = {AITaskKey.CHATBOT, AITaskKey.EVENT_MARKETING}
        qs_prof = AIPromptProfile.objects.filter(is_active=True)
        if not include_internal:
            qs_prof = qs_prof.filter(task_key__in=public_task_keys)
        for prof in qs_prof:
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
