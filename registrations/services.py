"""
Tầng SERVICE cho M4 + M5 — nơi chứa toàn bộ quy tắc nghiệp vụ.

Vì sao tách riêng khỏi view:
  - View chỉ nhận request và trả response, không chứa logic.
  - Service test được bằng unit test mà không cần dựng HTTP request.
  - Cùng một logic dùng lại được cho web, API hay lệnh quản trị.

Đây là phần đáng nói nhất khi bảo vệ đồ án.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import AuditLog
from events.models import EventStatus, TicketType

from .models import Ticket, TicketStatus

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from accounts.models import User
    from events.models import Event


class BookingError(Exception):
    """Lỗi nghiệp vụ khi đặt vé. View bắt lỗi này và hiện thông báo cho user."""


# ---------------------------------------------------------------------------
# F4.1 - ĐẶT VÉ
# ---------------------------------------------------------------------------
@transaction.atomic
def book_tickets(user: User, ticket_type_id: int, quantity: int) -> list[Ticket]:
    """
    Đặt `quantity` vé loại `ticket_type_id` cho `user`.

    Điểm cốt lõi: hai người cùng bấm đặt chỗ cuối cùng thì chỉ 1 người
    thành công. Nếu viết kiểu đọc rồi ghi thông thường:

        tt = TicketType.objects.get(pk=id)      # A đọc sold=49, B đọc sold=49
        if tt.sold + qty <= tt.quota:           # cả hai đều thấy còn chỗ
            tt.sold += qty; tt.save()           # kết quả: bán 51/50 vé

    thì cả hai đều lọt. Đó là RACE CONDITION (tranh chấp tài nguyên).

    Cách xử lý ở đây gồm 2 lớp:
      1. `select_for_update()` khoá dòng loại vé ở tầng CSDL. Giao dịch thứ
         hai phải CHỜ giao dịch thứ nhất commit rồi mới đọc được, nên nó
         nhìn thấy sold đã cập nhật và bị chặn đúng lúc.
      2. `@transaction.atomic` bảo đảm trừ chỗ và tạo vé là một khối không
         thể tách: lỗi ở giữa thì rollback hết, không có chuyện trừ chỗ mà
         không sinh vé.

    Trả về: danh sách Ticket vừa tạo.
    """
    if quantity < 1:
        raise BookingError("Số lượng vé phải lớn hơn 0.")

    # (1) KHOÁ DÒNG loại vé. Mọi kiểm tra bên dưới đọc dữ liệu đã được khoá.
    try:
        ticket_type = (TicketType.objects
                       .select_for_update()
                       .select_related("event")
                       .get(pk=ticket_type_id))
    except TicketType.DoesNotExist:
        raise BookingError("Loại vé không tồn tại.")

    event = ticket_type.event

    # (2) Kiểm tra trạng thái sự kiện
    if event.status != EventStatus.OPEN:
        raise BookingError("Sự kiện hiện không mở đăng ký.")
    if timezone.now() > event.register_deadline:
        raise BookingError("Đã quá hạn đăng ký sự kiện này.")

    # (3) F4.1 - giới hạn số vé mỗi người mỗi sự kiện
    limit = settings.MAX_TICKETS_PER_USER_PER_EVENT
    owned = Ticket.objects.filter(
        user=user, event=event,
        status__in=[TicketStatus.PENDING, TicketStatus.CONFIRMED,
                    TicketStatus.CHECKED_IN],
    ).count()
    if owned + quantity > limit:
        raise BookingError(
            f"Mỗi người chỉ được đăng ký tối đa {limit} vé cho một sự kiện. "
            f"Bạn đang có {owned} vé, chỉ có thể đặt thêm {max(limit - owned, 0)} vé."
        )

    # (4) Kiểm tra số chỗ còn lại (đọc trên dòng đã khoá nên luôn chính xác)
    if ticket_type.sold + quantity > ticket_type.quota:
        remaining = ticket_type.remaining
        if remaining == 0:
            raise BookingError("Loại vé này đã hết chỗ.")
        raise BookingError(f"Chỉ còn {remaining} chỗ cho loại vé này.")

    # (5) Trừ chỗ và tạo vé — vẫn trong cùng transaction
    ticket_type.sold += quantity
    ticket_type.save(update_fields=["sold"])

    # Vé miễn phí xác nhận luôn, vé có phí phải chờ BTC xác nhận thanh toán
    is_free = ticket_type.is_free
    now = timezone.now()
    tickets = [
        Ticket(
            event=event,
            ticket_type=ticket_type,
            user=user,
            price=ticket_type.price,
            status=TicketStatus.CONFIRMED if is_free else TicketStatus.PENDING,
            confirmed_at=now if is_free else None,
        )
        for _ in range(quantity)
    ]
    Ticket.objects.bulk_create(tickets)
    return tickets


# ---------------------------------------------------------------------------
# F4.3 - HUỶ VÉ
# ---------------------------------------------------------------------------
@transaction.atomic
def cancel_ticket(user: User, ticket_id: int) -> Ticket:
    """Huỷ vé và TRẢ LẠI chỗ. Cũng phải khoá dòng loại vé khi cộng lại sold."""
    try:
        ticket = Ticket.objects.select_related("event", "ticket_type").get(
            pk=ticket_id, user=user)
    except Ticket.DoesNotExist:
        raise BookingError("Không tìm thấy vé của bạn.")

    if not ticket.can_cancel:
        raise BookingError(
            f"Chỉ được huỷ vé trước giờ diễn ra ít nhất "
            f"{settings.CANCEL_BEFORE_HOURS} giờ và khi chưa check-in."
        )

    ticket_type = TicketType.objects.select_for_update().get(pk=ticket.ticket_type_id)
    ticket.status = TicketStatus.CANCELLED
    ticket.save(update_fields=["status"])
    # max(0, ...) để phòng dữ liệu lệch, tránh sold âm
    ticket_type.sold = max(ticket_type.sold - 1, 0)
    ticket_type.save(update_fields=["sold"])
    return ticket


# ---------------------------------------------------------------------------
# F4.4 - XÁC NHẬN THANH TOÁN
# ---------------------------------------------------------------------------
@transaction.atomic
def confirm_payment(staff: User, ticket_id: int) -> Ticket:
    """
    BTC đánh dấu vé đã thanh toán: Chờ thanh toán -> Đã xác nhận.

    Dùng select_for_update() để chặn 2 BTC cùng xác nhận 1 vé đồng thời,
    nhất quán với cách xử lý ở book_tickets() và cancel_ticket().
    """
    try:
        ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise BookingError("Không tìm thấy vé.")

    if ticket.status != TicketStatus.PENDING:
        raise BookingError(
            f"Vé đang ở trạng thái '{ticket.get_status_display()}', "
            f"không cần xác nhận thanh toán."
        )

    ticket.status = TicketStatus.CONFIRMED
    ticket.confirmed_at = timezone.now()
    ticket.save(update_fields=["status", "confirmed_at"])
    AuditLog.write(staff, "Xác nhận thanh toán", ticket.code,
                   f"{ticket.user} - {ticket.event.name}")
    return ticket


# ---------------------------------------------------------------------------
# F5.1 - CHECK-IN
# ---------------------------------------------------------------------------
# Ba kết quả có thể xảy ra, đúng như đặc tả use case UC10
CHECKIN_OK = "OK"
CHECKIN_USED = "USED"
CHECKIN_INVALID = "INVALID"


@transaction.atomic
def check_in(staff: User, code: str,
             event: Event | None = None) -> tuple[str, Ticket | None, str]:
    """
    Quét hoặc nhập mã vé để check-in.

    Trả về tuple (kết quả, vé, thông báo):
      - CHECKIN_OK      : vé hợp lệ, đã chuyển sang Đã check-in
      - CHECKIN_USED    : vé này đã check-in trước đó rồi
      - CHECKIN_INVALID : sai mã, chưa thanh toán, vé đã huỷ, hoặc vé của
                          sự kiện khác

    `select_for_update` ở đây chặn trường hợp 2 máy cùng quét 1 mã trong
    cùng thời điểm, nếu không thì cả hai đều báo hợp lệ.
    """
    code = (code or "").strip().upper()
    if not code:
        return CHECKIN_INVALID, None, "Chưa nhập mã vé."

    try:
        ticket = (Ticket.objects
                  .select_for_update()
                  .select_related("event", "ticket_type", "user")
                  .get(code=code))
    except Ticket.DoesNotExist:
        return CHECKIN_INVALID, None, f"Mã vé {code} không tồn tại."

    # Vé của sự kiện khác — lỗi hay gặp khi BTC mở sai trang check-in
    if event is not None and ticket.event_id != event.id:
        return (CHECKIN_INVALID, ticket,
                f"Vé này thuộc sự kiện '{ticket.event.name}', không phải sự kiện đang check-in.")

    if ticket.status == TicketStatus.CHECKED_IN:
        return (CHECKIN_USED, ticket,
                f"Vé đã được check-in lúc {timezone.localtime(ticket.checked_in_at):%H:%M %d/%m}.")

    if ticket.status == TicketStatus.CANCELLED:
        return CHECKIN_INVALID, ticket, "Vé đã bị huỷ."

    if ticket.status == TicketStatus.PENDING:
        return CHECKIN_INVALID, ticket, "Vé chưa được xác nhận thanh toán."

    # Tới đây vé đang ở Đã xác nhận -> cho vào
    ticket.status = TicketStatus.CHECKED_IN
    ticket.checked_in_at = timezone.now()
    ticket.checked_in_by = staff
    ticket.save(update_fields=["status", "checked_in_at", "checked_in_by"])
    AuditLog.write(staff, "Check-in", ticket.code,
                   f"{ticket.user} - {ticket.event.name}")
    return CHECKIN_OK, ticket, f"Hợp lệ. Mời {ticket.user.full_name} vào."


# ---------------------------------------------------------------------------
# F4.5 - TỰ HUỶ VÉ QUÁ HẠN THANH TOÁN
# ---------------------------------------------------------------------------
@transaction.atomic
def release_expired_tickets() -> int:
    """
    Huỷ các vé Chờ thanh toán quá 24h và trả lại chỗ.

    Chạy bằng lệnh: python manage.py release_expired
    Khi deploy thật thì đặt vào cron job hoặc Celery beat.
    Trả về số vé đã huỷ.
    """
    limit_time = timezone.now() - timezone.timedelta(
        hours=settings.PAYMENT_DEADLINE_HOURS)
    expired = (Ticket.objects
               .select_for_update()
               .filter(status=TicketStatus.PENDING, created_at__lt=limit_time))

    count = 0
    for ticket in expired:
        ticket_type = TicketType.objects.select_for_update().get(
            pk=ticket.ticket_type_id)
        ticket.status = TicketStatus.CANCELLED
        ticket.save(update_fields=["status"])
        ticket_type.sold = max(ticket_type.sold - 1, 0)
        ticket_type.save(update_fields=["sold"])
        count += 1
    return count


# ---------------------------------------------------------------------------
# F4.6 - DANH SÁCH NGƯỜI THAM GIA
# ---------------------------------------------------------------------------
def participants(event: Event, status: str | None = None,
                 keyword: str = "") -> QuerySet[Ticket]:
    """Danh sách vé của một sự kiện, có lọc theo trạng thái và tìm theo tên/MSSV."""
    qs = (Ticket.objects
          .filter(event=event)
          .select_related("user", "ticket_type")
          .order_by("ticket_type__name", "user__full_name"))
    if status:
        qs = qs.filter(status=status)
    if keyword:
        qs = qs.filter(Q(user__full_name__icontains=keyword)
                       | Q(user__mssv__icontains=keyword)
                       | Q(code__icontains=keyword))
    return qs
