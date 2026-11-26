"""
Bộ kiểm định chất lượng phần AI, mặc định KHÔNG gọi API thật.

Chạy:
  python manage.py evaluate_ai
  python manage.py evaluate_ai --min-intent 0.95
  python manage.py evaluate_ai --llm-judge

Đo trên bộ câu hỏi chuẩn (golden set) trong aiassist/evals/:
  - split "dev"    : dùng để chỉnh luật; không đạt ngưỡng thì lệnh THẤT BẠI.
  - split "holdout": không dùng để chỉnh, cùng người viết với "dev".
  - split "blind"  : câu hỏi độc lập ngoài mẫu huấn luyện.
Lệnh thoát với mã khác 0 khi trượt (`CommandError`), nên dùng được trong script/CI.
"""
import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from aiassist.chatbot import detect_intent
from aiassist.management.commands.seed_ai_knowledge import DEFAULT_KNOWLEDGE
from aiassist.models import ClubKnowledge
from aiassist.privacy import redact
from aiassist.services import (_ask_ai, build_assistant_context,
                               generate_event_content, retrieve_knowledge,
                               suggest_tasks)
from events.models import Event, EventStatus

EVAL_DIR = Path(__file__).resolve().parents[2] / "evals"

# (văn bản vào, chuỗi bắt buộc phải biến mất)
REDACTION_CASES = [
    ("mail của em là an.nv@gmail.com", "an.nv@gmail.com"),
    ("sdt 0912 345 678 nhé", "0912 345 678"),
    ("gọi +84912345678", "+84912345678"),
    ("MSSV AT200101 còn vé không", "AT200101"),
    ("mã vé 3D736DC95DBF bị lỗi", "3D736DC95DBF"),
    ("CCCD 001204012345", "001204012345"),
]


def _load(name):
    return json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))


class Command(BaseCommand):
    help = "Chạy bộ kiểm định chất lượng AI trên golden set."

    def add_arguments(self, parser):
        parser.add_argument("--min-intent", type=float, default=0.9,
                            help="Tỷ lệ đúng tối thiểu của nhận diện ý định (split dev).")
        parser.add_argument("--min-retrieval", type=float, default=0.85,
                            help="Tỷ lệ đúng tối thiểu của truy xuất tri thức (split dev).")
        parser.add_argument("--llm-judge", action="store_true",
                            help="Gọi AI làm giám khảo chấm điểm chất lượng Grounding Context.")
        parser.add_argument("--with-migrate", action="store_true",
                            help="Chạy migrate trên DB kiểm thử trước khi eval (hữu ích với SQLite tạm).")

    def handle(self, *args, **options):
        if options["with_migrate"]:
            call_command("migrate", verbosity=0, interactive=False)
        failures = []
        self._report("Ý định", self._eval_intents(), options["min_intent"], failures)
        self._report("Truy xuất tri thức", self._eval_retrieval(),
                     options["min_retrieval"], failures)

        leaked = [secret for text, secret in REDACTION_CASES if secret in redact(text)]
        self._check("Che PII", not leaked,
                    f"{len(REDACTION_CASES) - len(leaked)}/{len(REDACTION_CASES)}", failures)
        self._check("Fallback khi AI lỗi", self._eval_fallback(), "", failures)

        if options["llm_judge"]:
            ctx_text, _ = build_assistant_context("tuyển thành viên và ban")
            judge_prompt = (
                "Bạn là giám khảo đánh giá hệ thống RAG. Hãy chấm điểm 1-5 độ rõ ràng, "
                "đầy đủ và tính trung thực của ngữ cảnh sau:\n\n"
                f"{ctx_text[:1500]}\n\n"
                'Trả về JSON: {"score": 5, "reason": "ngắn gọn"}'
            )
            try:
                res = _ask_ai(judge_prompt, response_schema={
                    "type": "object",
                    "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}},
                    "required": ["score", "reason"],
                })
                j_score = int(res.get("score", 0))
                self._check("LLM Judge", j_score >= 4,
                            f"{j_score}/5 ({res.get('reason', '')[:80]})", failures)
            except Exception as exc:
                self._check("LLM Judge", False, str(exc), failures)

        if failures:
            raise CommandError("EVAL TRƯỢT: " + ", ".join(failures))
        self.stdout.write(self.style.SUCCESS("EVAL ĐẠT"))

    def _eval_intents(self):
        """Trả về [(split, đúng?, mô tả lỗi)]."""
        rows = []
        for case in _load("golden_intents.json"):
            got = detect_intent(case["q"])
            code = got["code"] if got else None
            rows.append((case["split"], code == case["intent"],
                         f"'{case['q']}' -> {code}, đúng phải là {case['intent']}"))
        return rows

    def _eval_retrieval(self):
        """
        Đo trên đúng bộ tri thức mẫu để kết quả lặp lại được. Mọi thay đổi DB
        nằm trong transaction và được rollback, dữ liệu thật không bị đụng.
        """
        rows = []
        with transaction.atomic():
            ClubKnowledge.objects.update(is_active=False)
            for item in DEFAULT_KNOWLEDGE:
                ClubKnowledge.objects.create(**item)
            for case in _load("golden_retrieval.json"):
                found = retrieve_knowledge(case["q"])
                top = found.split("\n")[0]
                ok = case["title"] in top if case["title"] else not found
                rows.append((case["split"], ok,
                             f"'{case['q']}' -> {top[:60] or '(rỗng)'}"))
            transaction.set_rollback(True)
        return rows

    def _eval_fallback(self):
        now = timezone.now()
        event = Event(name="Eval Test Event", location="Hội trường A", capacity=100,
                      starts_at=now + timezone.timedelta(days=7),
                      register_deadline=now + timezone.timedelta(days=5),
                      status=EventStatus.OPEN)
        with override_settings(AI_PROVIDER="mock"):
            tasks, _, _ = suggest_tasks(event, count=5)
            content, _, _ = generate_event_content(event)
        return len(tasks) == 5 and bool(content.get("social_post"))

    def _report(self, label, rows, minimum, failures):
        if not any(r[0] == "dev" for r in rows):
            failures.append(f"{label}: thiếu split dev")
        for split in ("dev", "holdout", "blind"):
            subset = [r for r in rows if r[0] == split]
            if not subset:
                continue
            correct = sum(r[1] for r in subset)
            ratio = correct / len(subset)
            self.stdout.write(f"{label} [{split}]: {correct}/{len(subset)} ({ratio:.0%})")
            for _, ok, detail in subset:
                if not ok:
                    self.stdout.write(self.style.WARNING(f"  sai: {detail}"))
            if split == "dev" and ratio < minimum:
                failures.append(f"{label} {ratio:.0%} < {minimum:.0%}")

    def _check(self, label, ok, detail, failures):
        self.stdout.write(f"{label}: {'đạt' if ok else 'TRƯỢT'} {detail}".rstrip())
        if not ok:
            failures.append(label)
