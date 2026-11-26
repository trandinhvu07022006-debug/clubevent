"""
Tầng SERVICE cho M4 + M5 - nơi chứa toàn bộ quy tắc nghiệp vụ.

Vì sao tách riêng khỏi view:
  - View chỉ nhận request và trả response, không chứa logic.
  - Service test được bằng unit test mà không cần dựng HTTP request.
  - Cùng một logic dùng lại được cho web, API hay lệnh quản trị.

Đây là phần đáng nói nhất khi bảo vệ đồ án.
"""
from __future__ import annotations

import random
import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User as UserModel, canonical_email
from events.models import (EventStatus, EventVisibility, TicketType,
                           can_view_internal_events)
from notifications.models import NotificationKind
from notifications.services import notify_on_commit

from .models import (Ticket, TicketStatus, TicketTransfer, WaitlistEntry,
                     WaitlistStatus, make_booking_ref, make_ticket_code)
from .vietqr import payment_info, transfer_content

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from accounts.models import User
    from events.models import Event


class BookingError(Exception):
    """Lỗi nghiệp vụ khi đặt vé. View bắt lỗi này và hiện thông báo cho user."""


class EmailNotVerified(BookingError):
    """F1.7 - Khách chưa xác minh email. View bắt riêng để chuyển sang trang nhập mã."""


_MYSQL_RETRYABLE_ERRNOS = frozenset({1205, 1213})  # lock wait timeout / deadlock


def _is_retryable_lock_error(exc: OperationalError) -> bool:
    errno = exc.args[0] if exc.args else None
    if errno in _MYSQL_RETRYABLE_ERRNOS:
        return True
    msg = str(exc).lower()
    return "deadlock" in msg or "lock wait timeout" in msg or "database is locked" in msg


def _run_atomic_with_retry(fn, *, max_attempts: int = 4):
    """
    Thực thi block `@transaction.atomic` kèm bounded retry khi xảy ra tranh chấp
    khóa dòng / deadlock thoáng qua (MySQL 1213/1205 hoặc SQLite busy).
    """
    for attempt in range(max_attempts):
        try:
            with transaction.atomic():
                return fn()
        except OperationalError as exc:
            if not _is_retryable_lock_error(exc) or attempt >= max_attempts - 1:
                raise
            delay = min(0.015 * (2 ** attempt) + random.uniform(0.0, 0.02), 0.2)
            time.sleep(delay)


def _lock_users(*user_ids: int) -> None:
    """Thứ tự khóa toàn cục mức 1: khóa các bản ghi User theo `pk` tăng dần."""
    ordered_ids = sorted({uid for uid in user_ids if uid})
    if not ordered_ids:
        return
    list(UserModel.objects.select_for_update().filter(pk__in=ordered_ids).order_by("pk").only("pk"))


def _lock_ticket_types(*ticket_type_ids: int) -> dict[int, TicketType]:
    """Thứ tự khóa toàn cục mức 2: khóa các TicketType theo `pk` tăng dần."""
    ordered_ids = sorted({tid for tid in ticket_type_ids if tid})
    if not ordered_ids:
        return {}
    locked = list(
        TicketType.objects.select_for_update()
        .select_related("event")
        .filter(pk__in=ordered_ids)
        .order_by("pk")
    )
    return {tt.pk: tt for tt in locked}


def _require_verified(user) -> None:
    """
    F1.7 - Chống gom vé bằng nhiều tài khoản ảo: Khách phải xác minh email
    (OTP) mới được đặt vé hoặc vào danh sách chờ.
    """
    if user.needs_email_verification:
        raise EmailNotVerified("Vui lòng xác minh email bằng mã OTP trước khi đặt vé.")


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


def book_tickets(user: User, ticket_type_id: int, quantity: int,
                 event_id: int | None = None) -> list[Ticket]:
    """
    Đặt `quantity` vé loại `ticket_type_id` cho `user` (thứ tự khóa chuẩn User -> TicketType -> Ticket).
    """
    if quantity < 1:
        raise BookingError("Số lượng vé phải lớn hơn 0.")
    if getattr(user, "is_locked", False):
        raise BookingError("Tài khoản của bạn đang bị khoá.")
    _require_verified(user)

    def _op():
        _lock_users(user.pk)
        locked_types = _lock_ticket_types(ticket_type_id)
        ticket_type = locked_types.get(ticket_type_id)
        if ticket_type is None:
            raise BookingError("Loại vé không tồn tại.")

        event = ticket_type.event
        if event_id is not None and ticket_type.event_id != event_id:
            raise BookingError("Loại vé không thuộc sự kiện này.")
        if event.visibility == EventVisibility.INTERNAL and not can_view_internal_events(user):
            raise BookingError("Sự kiện nội bộ chỉ dành cho thành viên CLB.")

        if event.status != EventStatus.OPEN:
            raise BookingError("Sự kiện hiện không mở đăng ký.")
        if timezone.now() > event.register_deadline:
            raise BookingError("Đã quá hạn đăng ký sự kiện này.")

        limit = settings.MAX_TICKETS_PER_USER_PER_EVENT
        owned = _active_count(user, event)
        if owned + quantity > limit:
            raise BookingError(
                f"Mỗi người chỉ được đăng ký tối đa {limit} vé cho một sự kiện. "
                f"Bạn đang có {owned} vé, chỉ có thể đặt thêm {max(limit - owned, 0)} vé."
            )

        if ticket_type.sold + quantity > ticket_type.quota:
            remaining = ticket_type.remaining
            if remaining == 0:
                raise BookingError("Loại vé này đã hết chỗ.")
            raise BookingError(f"Chỉ còn {remaining} chỗ cho loại vé này.")

        tickets = _issue_tickets(user, ticket_type, quantity, _new_booking_ref())

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

    return _run_atomic_with_retry(_op)


# ---------------------------------------------------------------------------
# F4.3 - HUỶ VÉ
# ---------------------------------------------------------------------------
def cancel_ticket(user: User, ticket_id: int) -> Ticket:
    """Huỷ vé và TRẢ LẠI chỗ theo thứ tự khóa User -> TicketType -> Ticket."""
    def _op():
        meta = (
            Ticket.objects.filter(pk=ticket_id, user=user)
            .values("user_id", "ticket_type_id")
            .first()
        )
        if meta is None:
            raise BookingError("Không tìm thấy vé của bạn.")

        _lock_users(meta["user_id"])
        locked_types = _lock_ticket_types(meta["ticket_type_id"])
        try:
            ticket = (
                Ticket.objects.select_for_update()
                .select_related("event", "ticket_type")
                .get(pk=ticket_id, user=user)
            )
        except Ticket.DoesNotExist:
            raise BookingError("Không tìm thấy vé của bạn.")

        if not ticket.can_cancel:
            raise BookingError(
                f"Chỉ được huỷ vé trước giờ diễn ra ít nhất "
                f"{settings.CANCEL_BEFORE_HOURS} giờ và khi chưa check-in."
            )

        ticket_type = locked_types.get(ticket.ticket_type_id) or (
            TicketType.objects.select_for_update().select_related("event")
            .get(pk=ticket.ticket_type_id)
        )
        ticket.status = TicketStatus.CANCELLED
        ticket.save(update_fields=["status"])
        ticket_type.sold = max(ticket_type.sold - 1, 0)
        ticket_type.save(update_fields=["sold"])
        promote_from_waitlist(ticket_type)
        return ticket

    return _run_atomic_with_retry(_op)


# ---------------------------------------------------------------------------
# F4.4 + F4.7 - XÁC NHẬN THANH TOÁN
# ---------------------------------------------------------------------------
def confirm_payment(staff: User, ticket_id: int) -> Ticket:
    """
    BTC đánh dấu vé đã thanh toán: Chờ thanh toán -> Đã xác nhận (thứ tự khóa chuẩn).
    """
    def _op():
        meta = (
            Ticket.objects.filter(pk=ticket_id)
            .values("user_id", "ticket_type_id")
            .first()
        )
        if meta is None:
            raise BookingError("Không tìm thấy vé.")

        _lock_users(meta["user_id"])
        _lock_ticket_types(meta["ticket_type_id"])
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

    return _run_atomic_with_retry(_op)


def confirm_booking(staff: User, booking_ref: str) -> list[Ticket]:
    """
    F4.7 - Xác nhận cả nhóm vé cùng mã giao dịch theo thứ tự User -> TicketType -> Ticket.
    """
    booking_ref = (booking_ref or "").strip().upper()

    def _op():
        meta_rows = list(
            Ticket.objects.filter(booking_ref=booking_ref, status=TicketStatus.PENDING)
            .values("pk", "user_id", "ticket_type_id")
        )
        if not meta_rows:
            raise BookingError("Không có vé nào đang chờ thanh toán với mã giao dịch này.")
        _lock_users(*(r["user_id"] for r in meta_rows))
        _lock_ticket_types(*(r["ticket_type_id"] for r in meta_rows))
        tickets = list(
            Ticket.objects.select_for_update()
            .select_related("user", "event")
            .filter(pk__in=sorted(r["pk"] for r in meta_rows), status=TicketStatus.PENDING)
            .order_by("pk")
        )
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

    return _run_atomic_with_retry(_op)


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
    if settings.BANK_ACCOUNT and (account or "").strip() != settings.BANK_ACCOUNT:
        return False, "Không phải tài khoản nhận tiền của CLB."
    match = TRANSFER_REF_RE.search((content or "").upper())
    if not match:
        return False, "Nội dung không có mã KMG."
    ref = match.group(1)
    def _op():
        meta_rows = list(
            Ticket.objects.filter(booking_ref=ref, status=TicketStatus.PENDING)
            .values("pk", "user_id", "ticket_type_id", "price")
        )
        if not meta_rows:
            return False, f"Mã {ref} không còn vé chờ thanh toán."
        _lock_users(*(r["user_id"] for r in meta_rows))
        _lock_ticket_types(*(r["ticket_type_id"] for r in meta_rows))
        total = (
            Ticket.objects.select_for_update()
            .filter(booking_ref=ref, status=TicketStatus.PENDING)
            .order_by("pk")
            .aggregate(s=Sum("price"))["s"]
        )
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

    return _run_atomic_with_retry(_op)


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
# F5.5 - Vé hợp lệ nhưng sự kiện yêu cầu đối chiếu giấy tờ: CHƯA cho vào,
# chờ BTC xem thẻ SV / CCCD rồi bấm xác nhận (gọi lại với id_confirmed=True)
CHECKIN_VERIFY = "VERIFY"


@transaction.atomic
def check_in(staff: User, code: str, event: Event | None = None,
             id_confirmed: bool = False) -> tuple[str, Ticket | None, str]:
    """
    Quét hoặc nhập mã vé để check-in.

    Trả về tuple (kết quả, vé, thông báo):
      - CHECKIN_OK      : vé hợp lệ, đã chuyển sang Đã check-in
      - CHECKIN_USED    : vé này đã check-in trước đó rồi
      - CHECKIN_INVALID : sai mã, chưa thanh toán, vé đã huỷ, hoặc vé của
                          sự kiện khác
      - CHECKIN_VERIFY  : sự kiện bật vé ghi danh, vé hợp lệ nhưng BTC phải
                          đối chiếu giấy tờ rồi gọi lại với id_confirmed=True

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
        # F4.10 - mã cũ của vé đã chuyển nhượng: báo rõ để BTC biết đây có
        # thể là vé mua lại qua ảnh QR
        if TicketTransfer.objects.filter(old_code=code).exists():
            return (CHECKIN_INVALID, None,
                    f"Mã {code} đã hết hiệu lực vì vé đã được chuyển nhượng "
                    f"cho người khác. Người giữ vé mới có mã khác.")
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

    # F5.5 - vé ghi danh: dừng lại cho BTC đối chiếu giấy tờ trước
    if ticket.event.require_id_check and not id_confirmed:
        return (CHECKIN_VERIFY, ticket,
                "Đối chiếu thẻ sinh viên / CCCD với tên trên vé trước khi cho vào.")

    # Tới đây vé đang ở Đã xác nhận -> cho vào
    ticket.status = TicketStatus.CHECKED_IN
    ticket.checked_in_at = timezone.now()
    ticket.checked_in_by = staff
    ticket.save(update_fields=["status", "checked_in_at", "checked_in_by"])
    AuditLog.write(staff, "Check-in", ticket.code,
                   f"{ticket.user} - {ticket.event.name}"
                   + (" - đã đối chiếu giấy tờ" if id_confirmed else ""))
    return CHECKIN_OK, ticket, f"Hợp lệ. Mời {ticket.user.full_name} vào."


def reject_id_check(staff: User, code: str, event: Event) -> tuple[str, str]:
    """
    F5.5 - Giấy tờ không khớp tên trên vé: không cho vào, ghi nhật ký để
    truy vết (vé có thể bị mua lại / tài khoản ảo). Vé giữ nguyên trạng thái,
    chủ vé thật vẫn vào được nếu tới sau với đúng giấy tờ.
    """
    ticket = (Ticket.objects.select_related("user")
              .filter(code=(code or "").strip().upper(), event=event).first())
    if ticket is None:
        return CHECKIN_INVALID, "Không tìm thấy vé."
    AuditLog.write(staff, "Từ chối check-in", ticket.code,
                   f"Giấy tờ không khớp {ticket.user} - {event.name}")
    name = ticket.user.full_name or ticket.user.username
    return CHECKIN_INVALID, f"Đã từ chối: giấy tờ không khớp tên {name}."


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
# F4.10 - CHUYỂN NHƯỢNG VÉ
# ---------------------------------------------------------------------------
def transfer_block_reason(ticket: Ticket) -> str:
    """Lý do vé KHÔNG chuyển được ("" = chuyển được). Dùng cả cho giao diện."""
    if ticket.user.needs_email_verification:
        return "Bạn cần xác minh email trước khi chuyển nhượng vé."
    if ticket.status != TicketStatus.CONFIRMED:
        return "Chỉ chuyển được vé đã xác nhận và chưa check-in."
    limit = ticket.event.starts_at - timezone.timedelta(
        hours=settings.TRANSFER_BEFORE_HOURS)
    if timezone.now() >= limit:
        return (f"Chỉ chuyển được vé trước giờ diễn ra ít nhất "
                f"{settings.TRANSFER_BEFORE_HOURS} giờ.")
    if ticket.transfers.count() >= settings.MAX_TRANSFERS_PER_TICKET:
        return "Vé này đã được chuyển nhượng, không chuyển tiếp được nữa."
    return ""


def _find_recipient(identifier: str):
    """Người nhận theo tên đăng nhập hoặc email (so theo dạng chuẩn)."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    if "@" in identifier:
        found = UserModel.objects.filter(
            email_canonical=canonical_email(identifier)).first()
        if found:
            return found
    return UserModel.objects.filter(username__iexact=identifier).first()


def transfer_ticket(user: User, ticket_id: int, recipient: str) -> Ticket:
    """
    Chủ vé chuyển 1 vé cho tài khoản khác theo thứ tự khóa chuẩn:
    User (pk tăng dần) -> TicketType -> Ticket -> WaitlistEntry.
    """
    def _op():
        pre_meta = (
            Ticket.objects.filter(pk=ticket_id, user=user)
            .values("user_id", "ticket_type_id")
            .first()
        )
        if pre_meta is None:
            raise BookingError("Không tìm thấy vé của bạn.")

        to_user_cand = _find_recipient(recipient)
        if to_user_cand is None:
            raise BookingError("Không tìm thấy tài khoản người nhận. Kiểm tra lại "
                               "tên đăng nhập hoặc email.")
        if to_user_cand.pk == user.pk:
            raise BookingError("Không thể chuyển vé cho chính mình.")

        # Thứ tự khóa chuẩn toàn cục: khóa cả 2 User theo pk tăng dần trước TicketType/Ticket
        _lock_users(user.pk, to_user_cand.pk)
        _lock_ticket_types(pre_meta["ticket_type_id"])
        try:
            ticket = (
                Ticket.objects.select_for_update()
                .select_related("event", "ticket_type")
                .get(pk=ticket_id, user=user)
            )
        except Ticket.DoesNotExist:
            raise BookingError("Không tìm thấy vé của bạn.")

        reason = transfer_block_reason(ticket)
        if reason:
            raise BookingError(reason)

        to_user = UserModel.objects.select_for_update().get(pk=to_user_cand.pk)
        if to_user.is_locked:
            raise BookingError("Tài khoản người nhận đang bị khoá.")
        if to_user.needs_email_verification:
            raise BookingError("Người nhận chưa xác minh email. Nhờ họ đăng nhập và "
                               "xác minh email trước rồi chuyển lại.")
        event = ticket.event
        limit = settings.MAX_TICKETS_PER_USER_PER_EVENT
        if _active_count(to_user, event) + 1 > limit:
            raise BookingError(f"Người nhận đã có đủ {limit} vé cho sự kiện này.")

        old_code = ticket.code
        ticket.user = to_user
        ticket.code = make_ticket_code()
        ticket.save(update_fields=["user", "code"])
        TicketTransfer.objects.create(ticket=ticket, from_user=user, to_user=to_user,
                                      old_code=old_code)
        AuditLog.write(user, "Chuyển nhượng vé", old_code,
                       f"{user} -> {to_user} - {event.name} - mã mới {ticket.code}")

        waiting_entry = (WaitlistEntry.objects
                         .select_for_update()
                         .filter(ticket_type__event=event, user=to_user,
                                 status=WaitlistStatus.WAITING)
                         .order_by("created_at", "id")
                         .first())
        if waiting_entry:
            waiting_entry.status = WaitlistStatus.CANCELLED
            waiting_entry.resolved_at = timezone.now()
            waiting_entry.save(update_fields=["status", "resolved_at"])

        my_tickets_url = reverse("registrations:my_tickets")
        giver = user.full_name or user.username
        taker = to_user.full_name or to_user.username
        title = f"Bạn được chuyển 1 vé: {event.name}"
        lead = f"{giver} đã chuyển cho bạn 1 vé sự kiện {event.name}."
        notify_on_commit(
            to_user, NotificationKind.TICKET_TRANSFER, title, lead,
            url=my_tickets_url, email_template="notice",
            context={"title": title, "message": lead,
                     "details": [("Sự kiện", event.name),
                                 ("Thời gian", _local(event.starts_at)),
                                 ("Địa điểm", event.location),
                                 ("Loại vé", ticket.ticket_type.name),
                                 ("Mã vé", ticket.code)],
                     "note": ("Sự kiện có đối chiếu giấy tờ: mang thẻ sinh viên hoặc "
                              "CCCD đúng tên tài khoản của bạn.")
                             if event.require_id_check else "",
                     "cta_url": my_tickets_url, "cta_label": "Xem vé của tôi"},
        )
        notify_on_commit(
            user, NotificationKind.TICKET_TRANSFER, f"Đã chuyển vé: {event.name}",
            f"Bạn đã chuyển vé {old_code} cho {taker}. Mã vé cũ không còn hiệu lực.",
            url=my_tickets_url)
        return ticket

    return _run_atomic_with_retry(_op)


# ---------------------------------------------------------------------------
# F4.5 - TỰ HUỶ VÉ QUÁ HẠN THANH TOÁN
# ---------------------------------------------------------------------------
def release_expired_tickets() -> int:
    """
    Huỷ các vé Chờ thanh toán quá hạn theo thứ tự khóa chuẩn User -> TicketType -> Ticket.
    """
    def _op():
        limit_time = timezone.now() - timezone.timedelta(
            hours=settings.PAYMENT_DEADLINE_HOURS)
        now = timezone.now()
        meta_rows = list(
            Ticket.objects.filter(status=TicketStatus.PENDING)
            .filter(Q(created_at__lt=limit_time) | Q(event__starts_at__lt=now))
            .values("pk", "user_id", "ticket_type_id")
        )
        if not meta_rows:
            return 0
        _lock_users(*(r["user_id"] for r in meta_rows))
        locked_types = _lock_ticket_types(*(r["ticket_type_id"] for r in meta_rows))
        expired = list(
            Ticket.objects.select_for_update()
            .select_related("user", "event")
            .filter(pk__in=sorted(r["pk"] for r in meta_rows), status=TicketStatus.PENDING)
            .order_by("pk")
        )

        count = 0
        per_user = defaultdict(list)
        freed_types = set()
        for ticket in expired:
            ticket_type = locked_types.get(ticket.ticket_type_id) or (
                TicketType.objects.select_for_update().select_related("event")
                .get(pk=ticket.ticket_type_id)
            )
            ticket.status = TicketStatus.CANCELLED
            ticket.save(update_fields=["status"])
            ticket_type.sold = max(ticket_type.sold - 1, 0)
            ticket_type.save(update_fields=["sold"])
            per_user[(ticket.user, ticket.event)].append(ticket)
            freed_types.add(ticket.ticket_type_id)
            count += 1

        for tt_id in sorted(freed_types):
            tt = locked_types.get(tt_id) or (
                TicketType.objects.select_for_update().select_related("event").get(pk=tt_id)
            )
            promote_from_waitlist(tt)

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

    return _run_atomic_with_retry(_op)


# ---------------------------------------------------------------------------
# F4.8 - DANH SÁCH CHỜ
# ---------------------------------------------------------------------------
def _waiting_count(user, event) -> int:
    return WaitlistEntry.objects.filter(
        user=user, ticket_type__event=event,
        status=WaitlistStatus.WAITING).count()


def join_waitlist(user: User, ticket_type_id: int) -> WaitlistEntry:
    """
    Vào danh sách chờ theo thứ tự khóa chuẩn User -> TicketType -> WaitlistEntry.
    """
    if getattr(user, "is_locked", False):
        raise BookingError("Tài khoản của bạn đang bị khoá.")
    _require_verified(user)

    def _op():
        _lock_users(user.pk)
        locked_types = _lock_ticket_types(ticket_type_id)
        tt = locked_types.get(ticket_type_id)
        if tt is None:
            raise BookingError("Loại vé không tồn tại.")
        ev = tt.event
        if ev.visibility == EventVisibility.INTERNAL and not can_view_internal_events(user):
            raise BookingError("Sự kiện nội bộ chỉ dành cho thành viên CLB.")
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

    return _run_atomic_with_retry(_op)


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
