"""Lệnh định kỳ vận hành CLB KMG (Chỉ thị 3.5): Khoá sổ RSVP, Gửi nhắc việc Idempotent & Quét ngưỡng cảnh báo > 3 lần."""
from django.core.management.base import BaseCommand, CommandError

from notifications.models import ScheduledReminder
from notifications.services import retry_pending_reminder_emails

from operations.services import run_proactive_operations_cycle


class Command(BaseCommand):
    help = "Chạy chu trình vận hành tự động KMG: chốt RSVP quá hạn, gửi nhắc deadline/RSVP (không trùng) và quét cảnh báo > 3 vi phạm."

    def handle(self, *args, **options):
        retried = retry_pending_reminder_emails()
        stats = run_proactive_operations_cycle()
        pending = ScheduledReminder.objects.filter(email_pending=True, sent_email=False).count()
        if pending:
            raise CommandError(
                f"Chu trình vận hành đã chạy; còn {pending} email nhắc việc chờ gửi. "
                "Kiểm tra SMTP/log. Lần chạy sau sẽ thử lại mà không tạo trùng thông báo trên web."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"[KMG Operations] Đã chốt {stats['frozen_events']} sự kiện "
                f"({stats['auto_committed_members']} TV mặc định tham gia), "
                f"gửi {stats['task_reminders_sent']} nhắc việc, "
                f"{stats['rsvp_reminders_sent']} nhắc RSVP, "
                f"{stats.get('training_reminders_sent', 0)} nhắc đào tạo, "
                f"{stats.get('practice_reminders_sent', 0)} nhắc lịch tập, "
                f"kiểm tra {stats['flagged_cases_checked']} hồ sơ cảnh báo; "
                f"gửi lại thành công {retried['sent']} email chờ."
            )
        )
