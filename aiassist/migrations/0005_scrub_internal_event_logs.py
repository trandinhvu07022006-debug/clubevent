"""Dọn answer_preview của hai ý định sự kiện có thể chứa dữ liệu INTERNAL từ log cũ."""
from django.db import migrations


def scrub_internal_event_logs(apps, schema_editor):
    AIInteractionLog = apps.get_model("aiassist", "AIInteractionLog")
    (
        AIInteractionLog.objects.using(schema_editor.connection.alias)
        .filter(intent__in=("upcoming_events", "seats_left"))
        .exclude(answer_preview="")
        .update(answer_preview="")
    )


class Migration(migrations.Migration):

    dependencies = [("aiassist", "0004_telemetry_fields")]

    operations = [
        migrations.RunPython(scrub_internal_event_logs, migrations.RunPython.noop),
    ]
