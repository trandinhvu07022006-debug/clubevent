import logging
import time

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection, send_mail
from django.db import transaction
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.models import User

from .models import (
    Notification,
    NotificationPreference,
    ScheduledReminder,
)

logger = logging.getLogger(__name__)


def notify(user, kind, title, message, url="", email_template=None, context=None):
    """
    CỬA VÀO DUY NHẤT để báo cho người dùng. Gọi từ bất kỳ service nào.

    - Luôn tạo Notification (trong app).
    - Nếu có email_template và user có email: gửi email.
    - KHÔNG BAO GIỜ ném lỗi ra ngoài: gửi mail lỗi thì ghi log và bỏ qua.
      Đặt vé thành công mà báo lỗi vì SMTP chết là sai.
    - Phải gọi SAU KHI commit (xem notify_on_commit).
    """
    Notification.objects.create(
        user=user, kind=kind, title=title[:120], message=message[:255], url=url
    )
    if email_template and user.email:
        try:
            send_templated_email(
                email_template,
                {**(context or {}), "user": user, "site_url": settings.SITE_URL},
                [user.email],
            )
        except Exception:  # SMTP, timeout, template lỗi...
            logger.exception(
                "Gửi email '%s' cho user %s thất bại", email_template, user.pk
            )


def notify_on_commit(*args, **kwargs):
    """Dùng hàm này bên trong service @transaction.atomic."""
    transaction.on_commit(lambda: notify(*args, **kwargs))


def send_templated_email(template, context, recipients):
    """
    Render 3 file: templates/emails/<template>_subject.txt  (1 dòng)
                   templates/emails/<template>.txt          (bản chữ thuần)
                   templates/emails/<template>.html         (bản HTML)
    Gửi bằng EmailMultiAlternatives (bản chữ + bản HTML).
    """
    subject = render_to_string(f"emails/{template}_subject.txt", context).strip()
    # Loại bỏ các khoảng trắng và dòng mới không mong muốn ở subject
    subject = "".join(subject.splitlines())

    text_body = render_to_string(f"emails/{template}.txt", context)
    html_body = render_to_string(f"emails/{template}.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


def notify_many(users, kind, title, message, url="", email_template=None, context=None):
    """
    Gửi cho nhiều user, tối ưu bằng cách dùng 1 kết nối SMTP chung
    và tạo Notification hàng loạt.
    """
    if not users:
        return

    # Tạo Notification hàng loạt
    Notification.objects.bulk_create(
        [
            Notification(
                user=user, kind=kind, title=title[:120], message=message[:255], url=url
            )
            for user in users
        ]
    )

    if email_template:
        messages = []
        for user in users:
            if not getattr(user, "email", None):
                continue
            ctx = {**(context or {}), "user": user, "site_url": settings.SITE_URL}
            try:
                subject = render_to_string(
                    f"emails/{email_template}_subject.txt", ctx
                ).strip()
                subject = "".join(subject.splitlines())
                text_body = render_to_string(f"emails/{email_template}.txt", ctx)
                html_body = render_to_string(f"emails/{email_template}.html", ctx)
                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[user.email],
                )
                msg.attach_alternative(html_body, "text/html")
                messages.append(msg)
            except Exception:
                logger.exception(
                    "Render email '%s' cho user %s thất bại", email_template, user.pk
                )

        if messages:
            try:
                connection = get_connection()
                connection.send_messages(messages)
            except Exception:
                logger.exception(
                    "Gửi %d email '%s' thất bại", len(messages), email_template
                )


def get_or_create_notification_preference(user) -> NotificationPreference:
    """Trả về (hoặc khởi tạo mặc định) tuỳ chọn nhận thông báo của thành viên."""
    pref, _ = NotificationPreference.objects.get_or_create(user=user)
    return pref


def _should_send_email_for_category(pref: NotificationPreference, category: str | None) -> bool:
    if not category:
        return False
    if category == "important":
        return pref.email_important
    if category == "task_deadline":
        return pref.email_task_deadline
    if category == "event_rsvp":
        return pref.email_event_rsvp
    if category == "training_practice":
        return pref.email_event_rsvp or pref.email_important
    return False


def send_operational_alert(
    user,
    kind: str,
    title: str,
    message: str,
    url: str = "",
    email_category: str | None = None,
) -> bool:
    """
    Gửi thông báo vận hành CLB đa kênh (In-App + Email theo cài đặt NotificationPreference).
    Trả về `True` nếu đã gửi cả Email, `False` nếu chỉ ghi thông báo In-App.
    """
    Notification.objects.create(
        user=user,
        kind=kind,
        title=title[:120],
        message=message[:255],
        url=url[:255],
    )
    if not _wants_operational_email(user, email_category):
        return False
    try:
        return _send_operational_email(user, title, message, url)
    except Exception as exc:
        logger.warning("Operational email failed: user=%s error=%s", user.pk, type(exc).__name__)
        return False


def _wants_operational_email(user, category):
    return bool(
        getattr(user, "email", "") and category
        and _should_send_email_for_category(get_or_create_notification_preference(user), category)
    )


def _send_operational_email(user, title, message, url):
    full_link = f"{getattr(settings, 'SITE_URL', 'http://localhost:8000')}{url}" if url else ""
    body = f"Xin chào {user.public_name},\n\n{title}\n{message}\n"
    if full_link:
        body += f"\nXem chi tiết tại KMG Platform: {full_link}\n"
    body += "\nTrân trọng,\nBan Điều hành CLB KMG"
    return send_mail(
        subject=f"[KMG Club] {title[:90]}", message=body,
        from_email=settings.DEFAULT_FROM_EMAIL, recipient_list=[user.email],
        fail_silently=False,
    ) == 1


def deliver_reminder_email(reminder_id: int) -> bool:
    """Khóa hàng trong lúc gửi để hai scheduler không cùng gửi một email.

    SMTP chỉ có xác nhận tiếp nhận: crash sau khi SMTP nhận nhưng trước commit
    vẫn có thể gây gửi lại email. In-app luôn đúng một bản ghi trong DB.
    """
    with transaction.atomic():
        reminder = ScheduledReminder.objects.select_for_update().filter(pk=reminder_id).first()
        # Tài khoản có thể đã bị xóa giữa lúc lấy danh sách hàng đợi và lúc gửi.
        if reminder is None:
            return False
        if not reminder.email_pending or reminder.sent_email:
            return False
        if reminder.notification_id is None:
            # Thông báo đã bị dọn theo retention; không gửi lại nội dung cũ đã bị xóa.
            reminder.email_pending = False
            reminder.email_last_error = "NOTIFICATION_REMOVED"
            reminder.save(update_fields=["email_pending", "email_last_error"])
            return False
        if not _wants_operational_email(reminder.recipient, reminder.email_category):
            reminder.email_pending = False
            reminder.email_last_error = ""
            reminder.save(update_fields=["email_pending", "email_last_error"])
            return False
        reminder.email_attempts += 1
        reminder.email_last_attempt_at = timezone.now()
        notification = reminder.notification
        try:
            accepted = _send_operational_email(
                reminder.recipient, notification.title, notification.message, notification.url,
            )
            reminder.sent_email = accepted
            reminder.email_pending = not accepted
            reminder.email_last_error = "" if accepted else "PROVIDER_NOT_ACCEPTED"
        except Exception as exc:
            reminder.email_last_error = type(exc).__name__[:80]
        reminder.save(update_fields=[
            "sent_email", "email_pending", "email_attempts", "email_last_attempt_at", "email_last_error",
        ])
        if reminder.email_pending:
            logger.warning("Reminder email remains pending: reminder=%s error=%s",
                           reminder.pk, reminder.email_last_error)
        return reminder.sent_email


def retry_pending_reminder_emails(limit: int = 200, max_seconds: float = 120) -> dict:
    """Đọc hàng đợi bền vững trong ngân sách thời gian, kể cả khi mốc nhắc đã qua.

    Kiểm tra ngân sách trước mỗi email; một lần gọi đang chạy vẫn chịu EMAIL_TIMEOUT.
    Hàng đợi còn lại được giữ nguyên cho chu kỳ sau, không giữ đói email mới.
    """
    if limit <= 0:
        raise ValueError("Số email tối đa cần lớn hơn 0.")
    if max_seconds <= 0:
        raise ValueError("Thời gian gửi lại tối đa cần lớn hơn 0.")
    deadline = time.monotonic() + max_seconds
    reminder_ids = list(ScheduledReminder.objects.filter(
        email_pending=True, sent_email=False,
    ).order_by(F("email_last_attempt_at").asc(nulls_first=True), "sent_at", "pk")
      .values_list("pk", flat=True)[:limit])
    checked = sent = 0
    for pk in reminder_ids:
        if time.monotonic() >= deadline:
            break
        sent += bool(deliver_reminder_email(pk))
        checked += 1
    return {"checked": checked, "sent": sent}


def dispatch_idempotent_reminder(
    *,
    target_type: str,
    target_id: int,
    recipient,
    stage: str,
    kind: str,
    title: str,
    message: str,
    url: str = "",
    email_category: str | None = None,
) -> bool:
    """
    Tạo in-app và hàng đợi email trong cùng transaction, gửi email sau commit.
    Trả về True chỉ khi vừa tạo thông báo in-app mới; email lỗi được retry riêng.
    """
    with transaction.atomic():
        # Khóa một hàng luôn tồn tại trước khi tạo reminder mới: tránh hai worker
        # cùng giữ gap lock trên unique key chưa tồn tại ở MySQL rồi chờ nhau.
        recipient = User.objects.select_for_update().get(pk=recipient.pk)
        reminder, _ = ScheduledReminder.objects.select_for_update().get_or_create(
            target_type=target_type, target_id=target_id, recipient=recipient, stage=stage,
        )
        created = not reminder.sent_in_app
        if created:
            reminder.notification = Notification.objects.create(
                user=recipient, kind=kind, title=title[:120], message=message[:255], url=url[:255],
            )
            reminder.sent_in_app = True
            reminder.email_category = email_category or ""
            reminder.email_pending = _wants_operational_email(recipient, email_category)
            reminder.save(update_fields=["notification", "sent_in_app", "email_category", "email_pending"])
        if created and reminder.email_pending:
            # robust: sự cố hạ tầng sau commit không biến tác vụ đã ghi nhận thành lỗi 500.
            transaction.on_commit(lambda pk=reminder.pk: deliver_reminder_email(pk), robust=True)
        return created
