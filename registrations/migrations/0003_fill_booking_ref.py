"""
F4.7 - Điền mã giao dịch cho vé cũ.

Mỗi vé cũ thành một giao dịch riêng (booking_ref = 8 ký tự đầu của mã vé),
để không vé nào có mã giao dịch rỗng.
"""
from django.db import migrations


def fill_booking_ref(apps, schema_editor):
    Ticket = apps.get_model("registrations", "Ticket")
    tickets = list(Ticket.objects.filter(booking_ref=""))
    for t in tickets:
        t.booking_ref = t.code[:8]
    Ticket.objects.bulk_update(tickets, ["booking_ref"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("registrations", "0002_ticket_booking_ref_waitlistentry"),
    ]

    operations = [
        migrations.RunPython(fill_booking_ref, migrations.RunPython.noop),
    ]
