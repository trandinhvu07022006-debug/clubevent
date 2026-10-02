"""
Tầng SERVICE cho M2 - Sự kiện, cùng các chức năng bám theo sự kiện:
huỷ sự kiện (B1), nhắc lịch (F7.2), file lịch .ics (F7.4), giấy chứng nhận
(F8.2) và ngân sách.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User
from events.models import Event, EventStatus
from notifications.models import NotificationKind
from notifications.services import notify_many
from registrations.models import (Ticket, TicketStatus, WaitlistEntry,
                                  WaitlistStatus)


# ---------------------------------------------------------------------------
# B1 - HUỶ SỰ KIỆN
# ---------------------------------------------------------------------------
@transaction.atomic
def cancel_event(user: User, event: Event):
    """Huỷ sự kiện, huỷ vé, huỷ danh sách chờ và báo cho người bị ảnh hưởng."""
    # 1. LẤY DANH SÁCH NGƯỜI BỊ ẢNH HƯỞNG TRƯỚC - sau .update() là mất thông tin
    active = event.tickets.exclude(status=TicketStatus.CANCELLED)
    affected_user_ids = set(active.values_list("user_id", flat=True))
    # Người có vé có phí đã xác nhận -> nhắc chuyện hoàn tiền
    refund_user_ids = set(active.filter(
        price__gt=0, status__in=[TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN],
    ).values_list("user_id", flat=True))
    waiting = WaitlistEntry.objects.filter(ticket_type__event=event,
                                           status=WaitlistStatus.WAITING)
    waiting_user_ids = set(waiting.values_list("user_id", flat=True))

    # 2. Đổi trạng thái sự kiện (kiểm tra ALLOWED_TRANSITIONS ở view)
    event.status = EventStatus.CANCELLED
    event.save(update_fields=["status"])
    # 3. Huỷ vé hàng loạt
    active.update(status=TicketStatus.CANCELLED)
    # 4. Trả sold về 0 cho mọi loại vé của sự kiện (sự kiện đã huỷ, cho số liệu nhất quán)
    event.ticket_types.update(sold=0)
    # 5. Huỷ mọi lượt chờ còn hiệu lực
    waiting.update(status=WaitlistStatus.CANCELLED, resolved_at=timezone.now())
    # 6. AuditLog
    AuditLog.write(user, "Huỷ sự kiện", event.name,
                   f"{len(affected_user_ids)} người giữ vé")

    # 7. Báo MỖI NGƯỜI MỘT LẦN dù họ giữ 4 vé - chạy sau khi commit
    title = f"Sự kiện bị huỷ: {event.name}"
    base = f"Sự kiện {event.name} đã bị huỷ. Thành thật xin lỗi bạn."
    url = event.get_absolute_url()
    groups = [
        (refund_user_ids, base + " Bạn có vé đã thanh toán, BTC sẽ liên hệ "
                                 "hoàn tiền (hệ thống không tự hoàn tiền)."),
        (affected_user_ids - refund_user_ids, base),
        (waiting_user_ids - affected_user_ids,
         base + " Lượt chờ của bạn cũng đã được huỷ."),
    ]

    def send():
        for ids, message in groups:
            users = list(User.objects.filter(id__in=ids))
            notify_many(users, kind=NotificationKind.EVENT_CANCELLED,
                        title=title, message=message, url=url,
                        email_template="notice",
                        context={"title": title, "message": message,
                                 "cta_url": url, "cta_label": "Xem sự kiện"})

    transaction.on_commit(send)
    return sorted(affected_user_ids)


# ---------------------------------------------------------------------------
# F7.2 - NHẮC LỊCH TRƯỚC 24H
# ---------------------------------------------------------------------------
def send_event_reminders() -> int:
    """
    Nhắc lịch cho sự kiện diễn ra trong 24 giờ tới. Trả về số sự kiện đã nhắc.

    - Cửa sổ "trong 24h tới" thay vì "đúng 24h": lịch chạy trễ vẫn không bỏ sót,
      sự kiện tạo khi chỉ còn 10 giờ vẫn được nhắc 1 lần.
    - Đánh dấu reminder_sent_at TRƯỚC khi gửi, trong cùng transaction có khoá
      dòng: lệnh chạy 2 lần (hoặc 2 máy song song) cũng không gửi trùng.
    - Chỉ nhắc người có vé ĐÃ XÁC NHẬN, không nhắc vé chờ thanh toán.
    """
    now = timezone.now()
    candidates = Event.objects.filter(
        status__in=[EventStatus.OPEN, EventStatus.CLOSED],
        starts_at__gt=now, starts_at__lte=now + timezone.timedelta(hours=24),
        reminder_sent_at__isnull=True,
    ).values_list("pk", flat=True)

    sent = 0
    for pk in list(candidates):
        with transaction.atomic():
            ev = Event.objects.select_for_update().get(pk=pk)
            if ev.reminder_sent_at:
                continue                               # tiến trình khác đã gửi
            ev.reminder_sent_at = now
            ev.save(update_fields=["reminder_sent_at"])
            users = list(User.objects.filter(
                tickets__event=ev, tickets__status=TicketStatus.CONFIRMED,
            ).distinct())
            title = f"Nhắc lịch: {ev.name}"
            when = timezone.localtime(ev.starts_at).strftime("%H:%M %d/%m/%Y")
            message = (f"Sự kiện {ev.name} sẽ diễn ra lúc {when} tại {ev.location}. "
                       f"Nhớ mang mã QR vé để check-in nhé!")
            url = reverse("registrations:my_tickets")
            ctx = {"title": title, "message": message,
                   "details": [("Sự kiện", ev.name), ("Thời gian", when),
                               ("Địa điểm", ev.location)],
                   "cta_url": url, "cta_label": "Mở vé của tôi"}
            transaction.on_commit(
                lambda users=users, title=title, message=message, url=url, ctx=ctx:
                notify_many(users, NotificationKind.EVENT_REMINDER, title, message,
                            url=url, email_template="notice", context=ctx))
            sent += 1
    return sent


# ---------------------------------------------------------------------------
# F7.4 - FILE LỊCH .ICS (RFC 5545), tự sinh không cần thư viện
# ---------------------------------------------------------------------------
def _ics_escape(text: str) -> str:
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_fold(line: str) -> str:
    """
    Gập dòng dài hơn 75 BYTE (không phải ký tự: tiếng Việt có dấu chiếm 2-3
    byte UTF-8). Chèn CRLF + 1 dấu cách, không cắt giữa một ký tự nhiều byte.
    """
    out, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        # Dòng tiếp theo bắt đầu bằng 1 dấu cách nên chỉ còn 74 byte
        limit = 75 if not out else 74
        if size + n > limit:
            out.append(current)
            current, size = "", 0
        current += ch
        size += n
    out.append(current)
    return "\r\n ".join(out)


def _ics_time(dt) -> str:
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def event_ics(event: Event) -> str:
    detail_url = settings.SITE_URL + event.get_absolute_url()
    description = (event.description or "")[:500]
    description = (description + "\n\n" if description else "") + f"Chi tiết: {detail_url}"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//KMG Club//Su kien//VI",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:event-{event.pk}@kmgclub",
        f"DTSTAMP:{_ics_time(timezone.now())}",
        f"DTSTART:{_ics_time(event.starts_at)}",
        f"DTEND:{_ics_time(event.effective_ends_at)}",
        f"SUMMARY:{_ics_escape(event.name)}",
        f"LOCATION:{_ics_escape(event.location)}",
        f"DESCRIPTION:{_ics_escape(description)}",
        f"URL:{detail_url}",
        "STATUS:" + ("CANCELLED" if event.status == EventStatus.CANCELLED
                     else "CONFIRMED"),
        "BEGIN:VALARM",
        "TRIGGER:-PT1H",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_escape('Sắp tới giờ sự kiện')}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


# ---------------------------------------------------------------------------
# F8.2 - GIẤY CHỨNG NHẬN THAM GIA
# ---------------------------------------------------------------------------
# Mã xác thực là chữ ký của Django (HMAC theo SECRET_KEY), không cần bảng mới.
# ĐỔI SECRET_KEY là MỌI chứng nhận đã cấp mất hiệu lực xác thực.
_cert_signer = signing.Signer(salt="kmg-certificate")


def cert_token(ticket: Ticket) -> str:
    return _cert_signer.sign(ticket.code).split(":", 1)[1]   # chỉ lấy phần chữ ký


def verify_cert_token(code: str, token: str) -> bool:
    try:
        _cert_signer.unsign(f"{code}:{token}")
        return True
    except signing.BadSignature:
        return False


def certificate_ticket(user: User, event: Event) -> Ticket | None:
    """
    Điều kiện cấp: sự kiện đã DONE và user có ít nhất 1 vé CHECKED_IN.
    Dùng vé check-in SỚM NHẤT để mã chứng nhận luôn cố định.
    """
    if event.status != EventStatus.DONE:
        return None
    return (Ticket.objects.filter(user=user, event=event,
                                  status=TicketStatus.CHECKED_IN)
            .order_by("checked_in_at", "id").first())


def verify_certificate(code: str, token: str) -> Ticket | None:
    """Trả vé nếu chứng nhận hợp lệ, ngược lại None (không phân biệt lý do)."""
    code = (code or "").upper()
    if not verify_cert_token(code, token):
        return None
    ticket = (Ticket.objects.select_related("user", "event")
              .filter(code=code, status=TicketStatus.CHECKED_IN,
                      event__status=EventStatus.DONE).first())
    return ticket


def mask_mssv(mssv: str) -> str:
    """Trang xác thực công khai: giữ 4 ký tự đầu và 2 cuối, giữa là '*'."""
    if not mssv:
        return ""
    if len(mssv) <= 6:
        return mssv[:2] + "*" * (len(mssv) - 2)
    return mssv[:4] + "*" * (len(mssv) - 6) + mssv[-2:]


# ---------------------------------------------------------------------------
# NGÂN SÁCH SỰ KIỆN
# ---------------------------------------------------------------------------
def budget_summary(event: Event) -> dict:
    """Thu (vé đã xác nhận/check-in) - chi (các khoản chi) = lãi/lỗ."""
    from organizing.models import ExpenseCategory

    income = event.tickets.filter(
        status__in=[TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN],
    ).aggregate(v=Sum("price"))["v"] or 0
    pending_income = event.tickets.filter(
        status=TicketStatus.PENDING).aggregate(v=Sum("price"))["v"] or 0
    rows = (event.expenses.values("category")
            .annotate(total=Sum("amount"), count=Count("id")).order_by("-total"))
    labels = dict(ExpenseCategory.choices)
    by_category = [{"label": labels.get(r["category"], r["category"]),
                    "total": r["total"], "count": r["count"]} for r in rows]
    spent = sum(r["total"] for r in by_category)
    return {
        "income": income,
        "pending_income": pending_income,
        "spent": spent,
        "balance": income - spent,
        "balance_abs": abs(income - spent),
        "budget": event.budget,
        "budget_left": event.budget - spent if event.budget else None,
        # Làm tròn xuống: 99,5% không được hiện thành "100%" khi chưa tiêu hết
        "budget_percent": spent * 100 // event.budget if event.budget else None,
        "by_category": by_category,
    }


# ---------------------------------------------------------------------------
# LỊCH SỰ KIỆN THEO THÁNG
# ---------------------------------------------------------------------------
def events_for_calendar(user, year: int, month: int):
    """Sự kiện có ngày diễn ra trong tháng, ẩn bản nháp với người thường."""
    # Lọc theo KHOẢNG thời gian tính sẵn, không dùng starts_at__year/__month:
    # trên MySQL, lookup theo ngày khi USE_TZ=True cần bảng múi giờ của MySQL
    # (mysql_tzinfo_to_sql); máy chưa nạp thì truy vấn trả rỗng, lịch trống trơn.
    tz = timezone.get_current_timezone()
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    qs = Event.objects.filter(starts_at__gte=start, starts_at__lt=end)
    if not (user.is_authenticated and user.is_staff_btc):
        qs = qs.exclude(status=EventStatus.DRAFT)
    return qs.order_by("starts_at")


def upcoming_for_user(user, limit=3):
    """Sự kiện sắp tới mà user đang giữ vé còn hiệu lực - cho khối 'Sắp tới'."""
    if not user.is_authenticated:
        return []
    return list(Event.objects.filter(
        starts_at__gte=timezone.now(),
        tickets__user=user,
        tickets__status__in=[TicketStatus.CONFIRMED, TicketStatus.PENDING],
    ).exclude(status=EventStatus.CANCELLED).annotate(
        my_count=Count("tickets", filter=Q(tickets__user=user))
    ).distinct().order_by("starts_at")[:limit])
