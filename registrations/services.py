"""
Tầng SERVICE cho M4 + M5 - nơi chứa toàn bộ quy tắc nghiệp vụ.

Vì sao tách riêng khỏi view:
  - View chỉ nhận request và trả response, không chứa logic.
  - Service test được bằng unit test mà không cần dựng HTTP request.
  - Cùng một logic dùng lại được cho web, API hay lệnh quản trị.

Đây là phần đáng nói nhất khi bảo vệ đồ án.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog
from events.models import EventStatus, TicketType
from notifications.models import NotificationKind
from notifications.services import notify_on_commit

from .models import (Ticket, TicketStatus, WaitlistEntry, WaitlistStatus,
                     make_booking_ref)
from .vietqr import payment_info, transfer_content

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from accounts.models import User
    from events.models import Event


class BookingError(Exception):
    """Lỗi nghiệp vụ khi đặt vé. View bắt lỗi này và hiện thông báo cho user."""


ACTIVE_STATUSES = (TicketStatus.PENDING, TicketStatus.CONFIRMED,
                   TicketStatus.CHECKED_IN)


def _active_count(user, event) -> int:
    """Số vé còn hiệu lực (đang chiếm chỗ) của user ở một sự kiện."""
    return Ticket.objects.filter(user=user, event=event,
                                 status__in=ACTIVE_STATUSES).count()


def _new_booking_ref() -> str:
    """
    F4.7 - Sinh mã giao dịch. 31^8 tổ hợp nên trùng gần như không thể, nhưng
    vẫn thử lại tối đa 5 lần nếu mã đã có trong các vé đang chờ thanh toán
    (tránh 2 nhóm vé cùng nội dung chuyển khoản).
    """
    ref = make_booking_ref()
    for _ in range(5):
        if not Ticket.objects.filter(booking_ref=ref,
                                     status=TicketStatus.PENDING).exists():
            break
        ref = make_booking_ref()
    return ref


def _money(value) -> str:
    return f"{int(value):,}".replace(",", ".") + "đ"


def _local(dt, fmt="%H:%M %d/%m/%Y") -> str:
    return timezone.localtime(dt).strftime(fmt)


# ---------------------------------------------------------------------------
# F7.1 - THÔNG BÁO THEO NGHIỆP VỤ (luôn chạy SAU KHI commit)
# ---------------------------------------------------------------------------
def _notify_issued(user, event, tickets, kind, title, lead):
    """
    Báo cho người vừa có vé (đặt vé hoặc được lên từ danh sách chờ).
    Vé có phí thì kèm đủ thông tin chuyển khoản trong email.
    """
    first = tickets[0]
    my_tickets_url = reverse("registrations:my_tickets")
    details = [
        ("Sự kiện", event.name),
        ("Thời gian", _local(event.starts_at)),
        ("Địa điểm", event.location),
        ("Loại vé", first.ticket_type.name),
        ("Số vé", str(len(tickets))),
        ("Mã vé", ", ".join(t.code for t in tickets)),
    ]
    note = "Mang mã QR trong mục 'Vé của tôi' tới cửa để check-in."
    if first.status == TicketStatus.PENDING:
        total = sum(t.price for t in tickets)
        details += [
            ("Số tiền", _money(total)),
            ("Nội dung chuyển khoản", transfer_content(first.booking_ref)),
            ("Hạn thanh toán", _local(first.payment_deadline)),
        ]
        bank = payment_info(first.booking_ref, total)
        if bank:
            details += [("Ngân hàng", bank["bank_name"]),
                        ("Số tài khoản", bank["account"]),
                        ("Chủ tài khoản", bank["account_name"])]
        note = ("Ghi đúng nội dung chuyển khoản để BTC đối chiếu. Vé chỉ có hiệu "
                "lực sau khi BTC xác nhận; quá hạn thanh toán vé sẽ tự huỷ.")
    notify_on_commit(
        user, kind, title, lead, url=my_tickets_url, email_template="notice",
        context={"title": title, "message": lead, "details": details,
                 "note": note, "cta_url": my_tickets_url,
                 "cta_label": "Xem vé của tôi"},
    )


def _notify_confirmed(user, event, tickets):
    title = f"Vé đã được xác nhận: {event.name}"
    lead = (f"BTC đã xác nhận thanh toán {len(tickets)} vé của bạn. "
            f"Vé đã có hiệu lực, hãy mang mã QR tới cửa để check-in.")
    my_tickets_url = reverse("registrations:my_tickets")
    notify_on_commit(
        user, NotificationKind.TICKET_CONFIRMED, title, lead,
        url=my_tickets_url, email_template="notice",
        context={"title": title, "message": lead,
                 "details": [("Sự kiện", event.name),
                             ("Thời gian", _local(event.starts_at)),
                             ("Địa điểm", event.location),
                             ("Mã vé", ", ".join(t.code for t in tickets))],
                 "cta_url": my_tickets_url, "cta_label": "Xem vé của tôi"},
    )


# ---------------------------------------------------------------------------
# F4.1 - ĐẶT VÉ
# ---------------------------------------------------------------------------
def _issue_tickets(user, ticket_type, quantity, booking_ref) -> list[Ticket]:
    """
    Trừ sold + tạo vé. Dùng chung cho đặt vé và cấp vé từ danh sách chờ.
    GIẢ ĐỊNH ticket_type ĐÃ bị select_for_update ở nơi gọi.
    """
    ticket_type.sold += quantity
    ticket_type.save(update_fields=["sold"])

    # Vé miễn phí xác nhận luôn, vé có phí phải chờ BTC xác nhận thanh toán
    is_free = ticket_type.is_free
    now = timezone.now()
    # Tạo TỪNG vé thay vì bulk_create: trên MySQL bulk_create không trả về id,
    # vé không có id thì không gắn được vào lượt chờ (WaitlistEntry.ticket).
    # Mỗi lần tối đa MAX_TICKETS_PER_USER_PER_EVENT vé nên không đáng kể.
    return [
        Ticket.objects.create(
            event=ticket_type.event,
            ticket_type=ticket_type,
            user=user,
            price=ticket_type.price,
            booking_ref=booking_ref,
            status=TicketStatus.CONFIRMED if is_free else TicketStatus.PENDING,
            confirmed_at=now if is_free else None,
        )
        for _ in range(quantity)
    ]


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
    owned = _active_count(user, event)
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

    # (5) Trừ chỗ và tạo vé - vẫn trong cùng transaction.
    # Cả lần đặt dùng chung MỘT mã giao dịch (F4.7) để chuyển khoản 1 lần.
    tickets = _issue_tickets(user, ticket_type, quantity, _new_booking_ref())

    # (6) F7.1 - báo cho người đặt, chỉ chạy SAU KHI commit
    if tickets[0].status == TicketStatus.CONFIRMED:
        _notify_issued(user, event, tickets, NotificationKind.TICKET_CONFIRMED,
                       f"Đăng ký thành công: {event.name}",
                       f"Bạn đã đăng ký {len(tickets)} vé cho sự kiện {event.name}.")
    else:
        _notify_issued(user, event, tickets, NotificationKind.TICKET_PENDING,
                       f"Giữ chỗ thành công: {event.name}",
                       f"Bạn đã giữ {len(tickets)} vé cho sự kiện {event.name}. "
                       f"Vui lòng chuyển khoản để BTC xác nhận.")
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

    ticket_type = (TicketType.objects.select_for_update().select_related("event")
                   .get(pk=ticket.ticket_type_id))
    ticket.status = TicketStatus.CANCELLED
    ticket.save(update_fields=["status"])
    # max(0, ...) để phòng dữ liệu lệch, tránh sold âm
    ticket_type.sold = max(ticket_type.sold - 1, 0)
    ticket_type.save(update_fields=["sold"])
    # F4.8 - chỗ vừa trả ra được cấp ngay cho người đầu danh sách chờ
    promote_from_waitlist(ticket_type)
    return ticket


# ---------------------------------------------------------------------------
# F4.4 + F4.7 - XÁC NHẬN THANH TOÁN
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
    _notify_confirmed(ticket.user, ticket.event, [ticket])
    return ticket


@transaction.atomic
def confirm_booking(staff: User, booking_ref: str) -> list[Ticket]:
    """
    F4.7 - Xác nhận cả nhóm vé cùng mã giao dịch (1 lần chuyển khoản).
    Chỉ xác nhận những vé còn Chờ thanh toán; vé đã huỷ trong nhóm bỏ qua.
    """
    booking_ref = (booking_ref or "").strip().upper()
    tickets = list(Ticket.objects.select_for_update()
                   .select_related("user", "event")
                   .filter(booking_ref=booking_ref, status=TicketStatus.PENDING))
    if not tickets:
        raise BookingError("Không có vé nào đang chờ thanh toán với mã giao dịch này.")
    now = timezone.now()
    for t in tickets:
        t.status = TicketStatus.CONFIRMED
        t.confirmed_at = now
    Ticket.objects.bulk_update(tickets, ["status", "confirmed_at"])
    first = tickets[0]
    AuditLog.write(staff, "Xác nhận thanh toán", booking_ref,
                   f"{len(tickets)} vé - {first.user} - {first.event.name}")
    _notify_confirmed(first.user, first.event, tickets)
    return tickets


# Nội dung CK bị ngân hàng chèn thêm tiền tố/hậu tố, có khi bỏ dấu cách:
# "MBVCB.123.KMG 3DUNG4TD.CT tu ..." hoặc "KMG3DUNG4TD". Bảng chữ khớp
# BOOKING_REF_ALPHABET (không có 0, 1, I, L, O).
TRANSFER_REF_RE = re.compile(r"KMG\s*([2-9A-HJKMNP-Z]{8})")


def auto_confirm_transfer(content: str, amount: int,
                          account: str = "") -> tuple[bool, str]:
    """
    Tự xác nhận nhóm vé khi webhook ngân hàng báo có tiền vào.

    Trả (đã xác nhận?, lý do). Chuyển thiếu tiền thì KHÔNG xác nhận mà ghi
    nhật ký để BTC xử lý tay; webhook gọi lại nhiều lần cũng an toàn vì
    confirm_booking chỉ đụng vé còn Chờ thanh toán.
    """
    if settings.BANK_ACCOUNT and account and account != settings.BANK_ACCOUNT:
        return False, "Không phải tài khoản nhận tiền của CLB."
    match = TRANSFER_REF_RE.search((content or "").upper())
    if not match:
        return False, "Nội dung không có mã KMG."
    ref = match.group(1)
    with transaction.atomic():
        total = (Ticket.objects.select_for_update()
                 .filter(booking_ref=ref, status=TicketStatus.PENDING)
                 .aggregate(s=Sum("price"))["s"])
        if total is None:
            return False, f"Mã {ref} không còn vé chờ thanh toán."
        if amount < total:
            AuditLog.write(None, "Chuyển khoản thiếu", ref,
                           f"Nhận {_money(amount)}đ / cần {_money(total)}đ")
            return False, f"Mã {ref} chuyển thiếu tiền."
        try:
            tickets = confirm_booking(None, ref)
        except BookingError as e:
            return False, str(e)
    return True, f"Đã xác nhận {len(tickets)} vé mã {ref}."


def pending_bookings(keyword: str = "") -> list[dict]:
    """
    F4.7 - Vé chờ thanh toán gom theo mã giao dịch, cho trang Xác nhận TT.
    Tìm được theo mã giao dịch (có hoặc không có tiền tố "KMG"), mã vé,
    tên hoặc MSSV người đặt.
    """
    qs = (Ticket.objects.filter(status=TicketStatus.PENDING)
          .select_related("event", "ticket_type", "user")
          .order_by("created_at", "id"))
    keyword = (keyword or "").strip()
    if keyword:
        ref = keyword.upper().removeprefix("KMG").strip()
        refs = (Ticket.objects.filter(status=TicketStatus.PENDING)
                .filter(Q(booking_ref=ref)
                        | Q(code__icontains=keyword)
                        | Q(user__full_name__icontains=keyword)
                        | Q(user__mssv__icontains=keyword))
                .values_list("booking_ref", flat=True))
        qs = qs.filter(booking_ref__in=list(refs))

    groups = {}
    for t in qs:
        g = groups.setdefault(t.booking_ref, {
            "ref": t.booking_ref, "user": t.user, "event": t.event,
            "ticket_type": t.ticket_type, "tickets": [], "total": 0,
            "created_at": t.created_at,
        })
        g["tickets"].append(t)
        g["total"] += t.price
    for g in groups.values():
        first = g["tickets"][0]
        g["deadline"] = first.payment_deadline
        g["is_expired"] = first.is_payment_expired
        g["content"] = transfer_content(g["ref"])
    return list(groups.values())


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

    # Vé của sự kiện khác - lỗi hay gặp khi BTC mở sai trang check-in
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


def checkin_progress_data(event: Event) -> dict:
    """
    F5.4 - Tiến độ check-in, dùng chung cho trang check-in và API polling.
    Một truy vấn aggregate nhóm theo loại vé + 10 lượt check-in gần nhất.
    """
    rows = (event.tickets.exclude(status=TicketStatus.CANCELLED)
            .values("ticket_type__name")
            .annotate(total=Count("id"),
                      done=Count("id", filter=Q(status=TicketStatus.CHECKED_IN)))
            .order_by("ticket_type__name"))
    by_type = [{"name": r["ticket_type__name"], "done": r["done"],
                "total": r["total"]} for r in rows]
    total = sum(r["total"] for r in by_type)
    done = sum(r["done"] for r in by_type)
    recent = (event.tickets.filter(status=TicketStatus.CHECKED_IN)
              .select_related("user").order_by("-checked_in_at")[:10])
    return {
        "total": total,
        "done": done,
        "percent": round(done * 100 / total) if total else 0,
        "by_type": by_type,
        "recent": [{"name": t.user.full_name or t.user.username,
                    "at": _local(t.checked_in_at, "%H:%M")} for t in recent],
    }


# ---------------------------------------------------------------------------
# F4.5 - TỰ HUỶ VÉ QUÁ HẠN THANH TOÁN
# ---------------------------------------------------------------------------
@transaction.atomic
def release_expired_tickets() -> int:
    """
    Huỷ các vé Chờ thanh toán quá hạn và trả lại chỗ.

    Hạn thanh toán = min(lúc đặt + 24h, giờ diễn ra) - xem Ticket.payment_deadline.
    Chỗ trả ra được cấp ngay cho người đầu danh sách chờ (F4.8).
    Một người bị huỷ nhiều vé cùng sự kiện chỉ nhận MỘT thông báo.

    Chạy bằng lệnh: python manage.py release_expired (hoặc run_periodic).
    Trả về số vé đã huỷ.
    """
    limit_time = timezone.now() - timezone.timedelta(
        hours=settings.PAYMENT_DEADLINE_HOURS)
    now = timezone.now()
    expired = (Ticket.objects
               .select_for_update()
               .select_related("user", "event")
               .filter(status=TicketStatus.PENDING)
               .filter(Q(created_at__lt=limit_time) | Q(event__starts_at__lt=now)))

    count = 0
    per_user = defaultdict(list)          # (user, event) -> [vé bị huỷ]
    freed_types = set()
    for ticket in expired:
        ticket_type = TicketType.objects.select_for_update().get(
            pk=ticket.ticket_type_id)
        ticket.status = TicketStatus.CANCELLED
        ticket.save(update_fields=["status"])
        ticket_type.sold = max(ticket_type.sold - 1, 0)
        ticket_type.save(update_fields=["sold"])
        per_user[(ticket.user, ticket.event)].append(ticket)
        freed_types.add(ticket.ticket_type_id)
        count += 1

    # Gom theo loại vé rồi mới đẩy danh sách chờ, mỗi loại 1 lần
    for tt_id in freed_types:
        promote_from_waitlist(TicketType.objects.select_for_update()
                              .select_related("event").get(pk=tt_id))

    for (user, event), tickets in per_user.items():
        title = f"Vé đã tự huỷ: {event.name}"
        lead = (f"{len(tickets)} vé của bạn cho sự kiện {event.name} đã bị huỷ "
                f"vì quá hạn thanh toán. Chỗ đã được nhường cho người khác.")
        notify_on_commit(
            user, NotificationKind.TICKET_EXPIRED, title, lead,
            url=event.get_absolute_url(), email_template="notice",
            context={"title": title, "message": lead,
                     "details": [("Mã vé", ", ".join(t.code for t in tickets))],
                     "cta_url": event.get_absolute_url(),
                     "cta_label": "Xem sự kiện"},
        )
    return count


# ---------------------------------------------------------------------------
# F4.8 - DANH SÁCH CHỜ
# ---------------------------------------------------------------------------
def _waiting_count(user, event) -> int:
    return WaitlistEntry.objects.filter(
        user=user, ticket_type__event=event,
        status=WaitlistStatus.WAITING).count()


@transaction.atomic
def join_waitlist(user: User, ticket_type_id: int) -> WaitlistEntry:
    """
    Vào danh sách chờ của một loại vé đã hết chỗ. Mỗi lượt chờ = 1 vé.

    Mọi join cho cùng loại vé phải xếp hàng chờ khoá dòng TicketType, nên
    kiểm tra "đã chờ chưa" rồi mới tạo là an toàn trên cả MySQL.
    """
    try:
        tt = (TicketType.objects.select_for_update().select_related("event")
              .get(pk=ticket_type_id))
    except TicketType.DoesNotExist:
        raise BookingError("Loại vé không tồn tại.")
    ev = tt.event
    if ev.status != EventStatus.OPEN or timezone.now() > ev.register_deadline:
        raise BookingError("Sự kiện không còn nhận đăng ký.")
    if tt.remaining > 0:
        raise BookingError("Loại vé này vẫn còn chỗ, bạn có thể đặt vé ngay.")
    if WaitlistEntry.objects.filter(ticket_type=tt, user=user,
                                    status=WaitlistStatus.WAITING).exists():
        raise BookingError("Bạn đã ở trong danh sách chờ của loại vé này.")
    owned = _active_count(user, ev)
    waiting = _waiting_count(user, ev)
    if owned + waiting + 1 > settings.MAX_TICKETS_PER_USER_PER_EVENT:
        raise BookingError(
            "Bạn đã đạt giới hạn vé cho sự kiện này (tính cả lượt chờ).")
    return WaitlistEntry.objects.create(ticket_type=tt, user=user)


def leave_waitlist(user: User, entry_id: int) -> WaitlistEntry:
    """Rời danh sách chờ. Chỉ chủ lượt chờ, chỉ khi đang chờ."""
    updated = WaitlistEntry.objects.filter(
        pk=entry_id, user=user, status=WaitlistStatus.WAITING,
    ).update(status=WaitlistStatus.CANCELLED, resolved_at=timezone.now())
    if not updated:
        raise BookingError("Không tìm thấy lượt chờ của bạn.")
    return WaitlistEntry.objects.select_related("ticket_type__event").get(pk=entry_id)


def _resolve(entry, status, note=""):
    entry.status = status
    entry.note = note[:255]
    entry.resolved_at = timezone.now()
    entry.save(update_fields=["status", "note", "resolved_at", "ticket"])


def promote_from_waitlist(ticket_type: TicketType) -> list[WaitlistEntry]:
    """
    GỌI BÊN TRONG transaction, KHI ticket_type ĐÃ bị select_for_update.
    Lặp: còn chỗ và còn người chờ -> cấp vé cho người đầu hàng.

    Tự động cấp, KHÔNG có bước "mời rồi chờ đồng ý": vé có phí được cấp ở
    trạng thái Chờ thanh toán và đi qua đúng luồng thanh toán + tự huỷ quá
    hạn. Không trả tiền thì vé hết hạn -> chỗ lại chuyển cho người kế tiếp.

    Hai người cùng huỷ vé đồng thời không gây cấp trùng: cả hai giao dịch
    đều phải khoá dòng TicketType trước, giao dịch sau đọc được kết quả
    của giao dịch trước.

    TODO: nếu sau này có chức năng tăng quota loại vé, gọi hàm này sau khi tăng.
    """
    ev = ticket_type.event
    if ev.status != EventStatus.OPEN or timezone.now() > ev.register_deadline:
        return []                                   # hết hạn đăng ký: không cấp nữa
    promoted = []
    while ticket_type.remaining > 0:
        entry = (WaitlistEntry.objects.select_for_update()
                 .filter(ticket_type=ticket_type, status=WaitlistStatus.WAITING)
                 .select_related("user").order_by("created_at", "id").first())
        if entry is None:
            break
        u = entry.user
        if u.is_locked:
            _resolve(entry, WaitlistStatus.SKIPPED, "Tài khoản bị khoá")
            continue
        if _active_count(u, ev) + 1 > settings.MAX_TICKETS_PER_USER_PER_EVENT:
            _resolve(entry, WaitlistStatus.SKIPPED, "Đã đủ số vé tối đa")
            continue
        [ticket] = _issue_tickets(u, ticket_type, 1, _new_booking_ref())
        entry.ticket = ticket
        _resolve(entry, WaitlistStatus.PROMOTED)
        promoted.append(entry)
        lead = (f"Đã có chỗ trống cho sự kiện {ev.name} và bạn là người tiếp "
                f"theo trong danh sách chờ. Hệ thống đã cấp 1 vé cho bạn.")
        if ticket.status == TicketStatus.PENDING:
            lead += " Vui lòng chuyển khoản trước hạn để giữ vé."
        _notify_issued(u, ev, [ticket], NotificationKind.WAITLIST_PROMOTED,
                       f"Bạn đã có vé: {ev.name}", lead)
    return promoted


@transaction.atomic
def expire_waitlists() -> int:
    """
    Dọn lượt chờ không còn cơ hội: sự kiện đã xong/huỷ/đóng hoặc quá hạn
    đăng ký. Báo "rất tiếc" cho mỗi người một lần mỗi sự kiện.
    """
    now = timezone.now()
    entries = list(WaitlistEntry.objects.select_for_update()
                   .select_related("user", "ticket_type__event")
                   .filter(status=WaitlistStatus.WAITING)
                   .filter(Q(ticket_type__event__status__in=[
                               EventStatus.DONE, EventStatus.CANCELLED,
                               EventStatus.CLOSED])
                           | Q(ticket_type__event__register_deadline__lt=now)))
    notified = set()
    for e in entries:
        e.status = WaitlistStatus.EXPIRED
        e.resolved_at = now
        ev = e.ticket_type.event
        if (e.user_id, ev.pk) not in notified:
            notified.add((e.user_id, ev.pk))
            notify_on_commit(
                e.user, NotificationKind.WAITLIST_EXPIRED,
                f"Danh sách chờ đã đóng: {ev.name}",
                f"Rất tiếc, đã không có chỗ trống cho bạn ở sự kiện {ev.name}.",
                url=ev.get_absolute_url())
    WaitlistEntry.objects.bulk_update(entries, ["status", "resolved_at"])
    return len(entries)


def event_waitlist(event: Event) -> QuerySet[WaitlistEntry]:
    """Danh sách chờ của sự kiện cho trang BTC."""
    return (WaitlistEntry.objects.filter(ticket_type__event=event)
            .select_related("user", "ticket_type", "ticket")
            .order_by("created_at", "id"))


# ---------------------------------------------------------------------------
# F8.1 - LỊCH SỬ THAM GIA
# ---------------------------------------------------------------------------
def attended_events(user: User):
    """Các sự kiện user đã check-in, mới nhất trước, mỗi sự kiện 1 dòng."""
    from events.models import Event as EventModel
    return (EventModel.objects
            .filter(tickets__user=user, tickets__status=TicketStatus.CHECKED_IN)
            .distinct().order_by("-starts_at"))


def user_stats(user: User) -> dict:
    """Số liệu nhỏ cho trang hồ sơ."""
    agg = Ticket.objects.filter(user=user).aggregate(
        booked=Count("id", filter=Q(status__in=ACTIVE_STATUSES)),
        attended=Count("event", filter=Q(status=TicketStatus.CHECKED_IN),
                       distinct=True),
        spent=Sum("price", filter=Q(status__in=[TicketStatus.CONFIRMED,
                                               TicketStatus.CHECKED_IN])),
    )
    agg["spent"] = agg["spent"] or 0
    return agg


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
