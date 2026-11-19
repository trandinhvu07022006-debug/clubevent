from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]

    operations = [
        migrations.AddIndex(
            model_name="financialtransaction",
            index=models.Index(fields=['status', 'transaction_date', 'id'], name="fin_status_date_id_idx"),
        ),
    ]
