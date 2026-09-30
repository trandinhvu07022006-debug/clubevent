"""
F7.2 - Nhắc lịch cho sự kiện diễn ra trong 24 giờ tới.

Chạy tay:  python manage.py send_reminders
Thường chạy qua lệnh tổng run_periodic (mỗi 15 phút).
"""
from django.core.management.base import BaseCommand

from events.services import send_event_reminders


class Command(BaseCommand):
    help = "Gửi nhắc lịch cho người có vé của sự kiện diễn ra trong 24h tới"

    def handle(self, *args, **options):
        count = send_event_reminders()
        self.stdout.write(self.style.SUCCESS(f"Đã nhắc lịch {count} sự kiện."))
