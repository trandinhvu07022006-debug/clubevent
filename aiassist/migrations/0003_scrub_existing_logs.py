"""Dọn dữ liệu cá nhân đã lỡ lưu trong nhật ký AI trước khi có bộ che PII."""
from django.db import migrations

from aiassist.privacy import redact

PRIVATE_INTENTS = ("my_tickets", "my_tasks", "greeting")


def scrub_logs(apps, schema_editor):
    AIInteractionLog = apps.get_model("aiassist", "AIInteractionLog")
    logs = AIInteractionLog.objects.using(schema_editor.connection.alias)
    for log in logs.all().iterator():
        log.question = redact(log.question)[:500]
        log.feedback_note = redact(log.feedback_note)[:255]
        log.answer_preview = ("" if log.intent in PRIVATE_INTENTS
                              else redact(log.answer_preview))
        log.save(update_fields=["question", "feedback_note", "answer_preview"])


class Migration(migrations.Migration):

    dependencies = [("aiassist", "0002_alter_aipromptprofile_task_key")]

    # Không đảo ngược được (dữ liệu đã che thì mất), nên chiều ngược để trống.
    operations = [migrations.RunPython(scrub_logs, migrations.RunPython.noop)]
