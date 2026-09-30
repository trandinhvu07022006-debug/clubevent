"""
Lệnh định kỳ TỔNG — chạy mỗi 15 phút.

Tuần tự: huỷ vé quá hạn thanh toán -> dọn danh sách chờ hết hạn -> nhắc lịch
-> xoá thông báo đã đọc quá 90 ngày. Mỗi bước bọc try/except riêng, một bước
lỗi không chặn bước sau.

Linux/host:  */15 * * * * cd /app && python manage.py run_periodic
Windows:     Task Scheduler, lặp lại mỗi 15 phút (xem docs/huong-dan-deploy.md)
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.services import send_event_reminders
from notifications.models import Notification
from registrations.services import expire_waitlists, release_expired_tickets

logger = logging.getLogger(__name__)


def purge_old_notifications(days=90):
    limit = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = Notification.objects.filter(is_read=True,
                                             created_at__lt=limit).delete()
    return deleted


STEPS = [
    ("Huỷ vé quá hạn thanh toán", release_expired_tickets, "vé"),
    ("Dọn danh sách chờ hết hạn", expire_waitlists, "lượt chờ"),
    ("Nhắc lịch trước 24h", send_event_reminders, "sự kiện"),
    ("Xoá thông báo cũ đã đọc", purge_old_notifications, "thông báo"),
]


class Command(BaseCommand):
    help = "Chạy mọi tác vụ định kỳ (khuyến nghị mỗi 15 phút)"

    def handle(self, *args, **options):
        failed = 0
        for label, func, unit in STEPS:
            try:
                count = func()
            except Exception:
                failed += 1
                logger.exception("run_periodic: bước '%s' lỗi", label)
                self.stderr.write(self.style.ERROR(f"- {label}: LỖI (xem logs/app.log)"))
                continue
            self.stdout.write(f"- {label}: {count} {unit}")
        if failed:
            self.stderr.write(self.style.WARNING(f"Xong, {failed} bước lỗi."))
        else:
            self.stdout.write(self.style.SUCCESS("Xong, mọi bước chạy tốt."))
