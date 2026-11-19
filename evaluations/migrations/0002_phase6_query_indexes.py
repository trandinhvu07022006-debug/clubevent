from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("evaluations", "0001_initial")]

    operations = [
        migrations.AddIndex(
            model_name="memberevaluation",
            index=models.Index(fields=['cycle', 'department', 'status'], name="eval_cycle_dept_status_idx"),
        ),
        migrations.AddIndex(
            model_name="memberevaluation",
            index=models.Index(fields=['member', 'status'], name="eval_member_status_idx"),
        ),
    ]
