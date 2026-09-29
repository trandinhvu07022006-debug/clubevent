"""
F4.5 - Huỷ vé chờ thanh toán quá hạn và trả lại chỗ.

Chạy tay:  python manage.py release_expired
Khi deploy thật thì đưa vào cron job, ví dụ chạy mỗi giờ:
    0 * * * * cd /duong/dan/du-an && python manage.py release_expired
"""
from django.core.management.base import BaseCommand

from registrations.services import release_expired_tickets


class Command(BaseCommand):
    help = "Huỷ các vé chờ thanh toán quá hạn và trả lại chỗ"

    def handle(self, *args, **options):
        count = release_expired_tickets()
        if count:
            self.stdout.write(self.style.SUCCESS(
                f"Đã huỷ {count} vé quá hạn thanh toán và trả lại chỗ."))
        else:
            self.stdout.write("Không có vé nào quá hạn.")
