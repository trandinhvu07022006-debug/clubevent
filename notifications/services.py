import logging
from django.conf import settings
from django.db import transaction
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from .models import Notification

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
    Notification.objects.create(user=user, kind=kind, title=title[:120],
                                message=message[:255], url=url)
    if email_template and user.email:
        try:
            send_templated_email(email_template, {**(context or {}), "user": user,
                                 "site_url": settings.SITE_URL}, [user.email])
        except Exception:                     # SMTP, timeout, template lỗi...
            logger.exception("Gửi email '%s' cho user %s thất bại",
                             email_template, user.pk)


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
        to=recipients
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
    Notification.objects.bulk_create([
        Notification(user=user, kind=kind, title=title[:120], message=message[:255], url=url)
        for user in users
    ])
    
    if email_template:
        messages = []
        for user in users:
            if not getattr(user, 'email', None):
                continue
            ctx = {**(context or {}), "user": user, "site_url": settings.SITE_URL}
            try:
                subject = render_to_string(f"emails/{email_template}_subject.txt", ctx).strip()
                subject = "".join(subject.splitlines())
                text_body = render_to_string(f"emails/{email_template}.txt", ctx)
                html_body = render_to_string(f"emails/{email_template}.html", ctx)
                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[user.email]
                )
                msg.attach_alternative(html_body, "text/html")
                messages.append(msg)
            except Exception:
                logger.exception("Render email '%s' cho user %s thất bại", email_template, user.pk)
                
        if messages:
            try:
                connection = get_connection()
                connection.send_messages(messages)
            except Exception:
                logger.exception("Gửi %d email '%s' thất bại", len(messages), email_template)
