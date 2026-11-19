from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]

    operations = [
        migrations.AddIndex(
            model_name="eventattendance",
            index=models.Index(fields=['user', 'checkin_status'], name="att_user_checkin_idx"),
        ),
    ]
