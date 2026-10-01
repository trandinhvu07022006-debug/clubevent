"""View cho M4 - Đăng ký vé và M5 - Check-in."""
import csv
import hmac
import json
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.permissions import lead_required, staff_required
from core.pagination import paginate
from core.qr import qr_data_uri
from events.models import Event, TicketType

from .models import Ticket, TicketStatus, WaitlistEntry, WaitlistStatus
from .services import (CHECKIN_OK, CHECKIN_USED, BookingError,
                       auto_confirm_transfer, book_tickets,
                       cancel_ticket, check_in, checkin_progress_data,
                       confirm_booking, confirm_payment, event_waitlist,
                       join_waitlist, leave_waitlist, participants,
                       pending_bookings)
from .vietqr import payment_info, transfer_content


@login_required
def book(request, event_id):
    """F4.1 - Đăng ký tham gia / đặt vé."""
    event = get_object_or_404(Event, pk=event_id)

    if request.method != "POST":
        return redirect("events:detail", pk=event_id)

    try:
        ticket_type_id = int(request.POST.get("ticket_type", 0))
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        messages.error(request, "Dữ liệu không hợp lệ.")
        return redirect("events:detail", pk=event_id)

    try:
        tickets = book_tickets(request.user, ticket_type_id, quantity)
    except BookingError as e:
        # Lỗi nghiệp vụ: hết chỗ, vượt giới hạn, quá hạn...
        messages.error(request, str(e))
        return redirect("events:detail", pk=event_id)

    first = tickets[0]
    if first.status == TicketStatus.CONFIRMED:
        messages.success(request,
                         f"Đăng ký thành công {len(tickets)} vé (miễn phí). "
                         f"Mã vé đã có trong mục 'Vé của tôi'.")
    else:
        messages.success(request,
                         f"Đã giữ {len(tickets)} vé. Vui lòng thanh toán trong 24h, "
                         f"sau đó BTC sẽ xác nhận.")
    return redirect("registrations:my_tickets")


@login_required
def my_tickets(request):
    """
    F4.2 - Vé của tôi, kèm mã QR.

    Chia 3 nhóm cho dễ nhìn: sắp tới (còn hiệu lực), đã qua/đã huỷ, và khối
    "Cần thanh toán" gom theo mã giao dịch kèm VietQR (F4.7).
    """
    tab = request.GET.get("tab", "active")
    tickets = list(Ticket.objects
                   .filter(user=request.user)
                   .select_related("event", "ticket_type")
                   .order_by("event__starts_at", "created_at"))

    active, history = [], []
    for ticket in tickets:
        if ticket.is_active and ticket.status != TicketStatus.CHECKED_IN \
                and not ticket.event.is_past:
            active.append(ticket)
        else:
            history.append(ticket)
    history.reverse()      # đã qua: mới nhất lên đầu

    # Gắn QR trực tiếp vào từng vé để template chỉ cần {{ ticket.qr }}.
    # Chỉ sinh QR cho vé đang hiển thị và còn hiệu lực, đỡ tốn thời gian render.
    shown = active if tab == "active" else history
    for ticket in shown:
        ticket.qr = (qr_data_uri(ticket.code)
                     if ticket.is_active and ticket.status != TicketStatus.PENDING
                     else None)

    # F4.7 - nhóm vé chờ thanh toán theo mã giao dịch
    payments = {}
    for t in active:
        if t.status != TicketStatus.PENDING:
            continue
        p = payments.setdefault(t.booking_ref, {
            "ref": t.booking_ref, "event": t.event, "count": 0, "total": 0,
            "deadline": t.payment_deadline,
            "content": transfer_content(t.booking_ref),
        })
        p["count"] += 1
        p["total"] += t.price
    for p in payments.values():
        p["bank"] = payment_info(p["ref"], p["total"])

    waitlist = (WaitlistEntry.objects
                .filter(user=request.user, status=WaitlistStatus.WAITING)
                .select_related("ticket_type__event"))
    return render(request, "registrations/my_tickets.html", {
        "tab": tab,
        "tickets": shown,
        "active_count": len(active),
        "history_count": len(history),
        "payments": list(payments.values()),
        "waitlist": waitlist,
    })


@login_required
def ticket_print(request, pk):
    """Bản in / lưu PDF của một vé (khổ nhỏ, có QR to)."""
    ticket = get_object_or_404(
        Ticket.objects.select_related("event", "ticket_type"),
        pk=pk, user=request.user)
    return render(request, "registrations/ticket_print.html", {
        "ticket": ticket,
        "qr": qr_data_uri(ticket.code) if ticket.is_active else None,
    })


@require_POST
@login_required
def waitlist_join(request, ticket_type_id):
    """F4.8 - Vào danh sách chờ của loại vé đã hết chỗ."""
    tt = get_object_or_404(TicketType, pk=ticket_type_id)
    try:
        entry = join_waitlist(request.user, tt.pk)
        messages.success(
            request,
            f"Đã vào danh sách chờ '{tt.name}'. Bạn đang ở vị trí thứ "
            f"{entry.position}. Khi có người huỷ, hệ thống tự cấp vé và báo cho bạn.")
    except BookingError as e:
        messages.error(request, str(e))
    return redirect("events:detail", pk=tt.event_id)


@require_POST
@login_required
def waitlist_leave(request, pk):
    """F4.8 - Rời danh sách chờ."""
    try:
        entry = leave_waitlist(request.user, pk)
        messages.success(request, "Đã rời danh sách chờ.")
        event_id = entry.ticket_type.event_id
    except BookingError as e:
        messages.error(request, str(e))
        return redirect("registrations:my_tickets")
    if request.POST.get("next") == "event":
        return redirect("events:detail", pk=event_id)
    return redirect("registrations:my_tickets")


@require_POST
@login_required
def cancel(request, pk):
    """F4.3 - Huỷ vé, trả lại chỗ cho người khác."""
    try:
        cancel_ticket(request.user, pk)
        messages.success(request, "Đã huỷ vé và trả lại chỗ.")
    except BookingError as e:
        messages.error(request, str(e))
    return redirect("registrations:my_tickets")


@staff_required
def payment_list(request):
    """
    F4.4 + F4.7 - Vé chờ xác nhận thanh toán, gom theo mã giao dịch.
    Tìm theo nội dung chuyển khoản ("KMG ABCD2345"), mã vé, tên hoặc MSSV.
    """
    keyword = request.GET.get("q", "").strip()
    groups = pending_bookings(keyword)
    return render(request, "registrations/payment_list.html", {
        "groups": groups,
        "keyword": keyword,
        "total_amount": sum(g["total"] for g in groups),
        "ticket_count": sum(len(g["tickets"]) for g in groups),
    })


@require_POST
@staff_required
def payment_confirm_booking(request, ref):
    """F4.7 - Xác nhận cả nhóm vé cùng mã giao dịch."""
    try:
        tickets = confirm_booking(request.user, ref)
        messages.success(request,
                         f"Đã xác nhận {len(tickets)} vé của giao dịch {ref}.")
    except BookingError as e:
        messages.error(request, str(e))
    # Giữ lại từ khoá tìm kiếm để BTC xác nhận tiếp các giao dịch khác
    keyword = request.POST.get("q", "")
    url = reverse("registrations:payment_list")
    return redirect(f"{url}?{urlencode({'q': keyword})}" if keyword else url)


@csrf_exempt
@require_POST
def sepay_webhook(request):
    """
    SePay gọi vào đây mỗi khi tài khoản ngân hàng có giao dịch.
    Xác thực bằng header "Authorization: Apikey <SEPAY_API_KEY>".
    Phải trả 200 + {"success": true}, nếu không SePay sẽ gọi lại tối đa 7 lần.
    """
    key = settings.SEPAY_API_KEY
    if not key:
        raise Http404
    sent = request.headers.get("Authorization", "")
    if not hmac.compare_digest(sent.encode(), f"Apikey {key}".encode()):
        return JsonResponse({"success": False}, status=401)
    try:
        data = json.loads(request.body)
        amount = int(data.get("transferAmount") or 0)
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"success": False, "message": "JSON lỗi"}, status=400)

    if data.get("transferType") != "in":
        return JsonResponse({"success": True, "message": "Bỏ qua tiền ra."})
    ok, message = auto_confirm_transfer(data.get("content", ""), amount,
                                        str(data.get("accountNumber") or ""))
    return JsonResponse({"success": True, "confirmed": ok, "message": message})


@require_POST
@staff_required
def payment_confirm(request, pk):
    """F4.4 - Xác nhận một vé đã thanh toán."""
    try:
        ticket = confirm_payment(request.user, pk)
        messages.success(request, f"Đã xác nhận thanh toán vé {ticket.code}.")
    except BookingError as e:
        messages.error(request, str(e))
    return redirect("registrations:payment_list")


@staff_required
def checkin(request, event_id):
    """
    F5.1 + F5.2 - Trang check-in.
    """
    event = get_object_or_404(Event, pk=event_id)
    result = ticket = None
    note = ""

    if request.method == "POST":
        code = request.POST.get("code", "")
        result, ticket, note = check_in(request.user, code, event=event)

    progress = checkin_progress_data(event)

    return render(request, "registrations/checkin.html", {
        "event": event,
        "result": result,
        "ticket": ticket,
        "note": note,
        "css_class": {CHECKIN_OK: "success", CHECKIN_USED: "warning"}.get(
            result, "danger"),
        **progress,
    })



@staff_required
@require_POST
def checkin_scan(request, event_id):
    """F5.3 - API quét QR bằng camera."""
    event = get_object_or_404(Event, pk=event_id)
    try:
        data = json.loads(request.body)
        code = data.get("code", "") if isinstance(data, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        code = None
    if not isinstance(code, str):
        return JsonResponse({"result": "INVALID", "error": "Dữ liệu không hợp lệ.",
                             "note": "Dữ liệu không hợp lệ."}, status=400)

    result, ticket, note = check_in(request.user, code, event=event)

    # Thông tin người tham gia để BTC đối chiếu tại cửa
    ticket_data = None
    if ticket:
        ticket_data = {
            "code": ticket.code,
            "user_name": ticket.user.full_name or ticket.user.username,
            "mssv": ticket.user.mssv or "",
            "ticket_type": ticket.ticket_type.name,
        }
        
    return JsonResponse({
        "result": result,
        "note": note,
        "ticket": ticket_data,
        "css_class": {CHECKIN_OK: "success", CHECKIN_USED: "warning"}.get(result, "danger"),
    })


@staff_required
def checkin_progress(request, event_id):
    """F5.4 - API lấy tiến độ điểm danh (cập nhật liên tục)."""
    event = get_object_or_404(Event, pk=event_id)
    return JsonResponse(checkin_progress_data(event))


@lead_required
def participant_list(request, event_id):
    """F4.6 - Danh sách người tham gia, lọc theo trạng thái."""
    event = get_object_or_404(Event, pk=event_id)
    status = request.GET.get("status", "")
    keyword = request.GET.get("q", "").strip()
    tickets = participants(event, status=status or None, keyword=keyword)
    page_obj, querystring = paginate(request, tickets, per_page=25)
    return render(request, "registrations/participants.html", {
        "event": event,
        "waitlist": event_waitlist(event),
        "view": request.GET.get("view", ""),
        "tickets": page_obj,
        "page_obj": page_obj,
        "querystring": querystring,
        "statuses": TicketStatus.choices,
        "current_status": status,
        "keyword": keyword,
    })


@lead_required
def participant_csv(request, event_id):
    """F4.6 - Xuất danh sách người tham gia ra CSV (Excel mở được)."""
    event = get_object_or_404(Event, pk=event_id)
    # charset utf-8 + ghi BOM MỘT lần ở đầu file. Không dùng "utf-8-sig" làm
    # charset: HttpResponse mã hoá TỪNG lần write nên mỗi dòng sẽ dính 1 BOM.
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="nguoi-tham-gia-{event.pk}.csv"')
    
    response.write('\ufeff')  # BOM for Excel

    writer = csv.writer(response)
    writer.writerow(["Mã vé", "Mã giao dịch", "Họ tên", "MSSV", "Email",
                     "Loại vé", "Giá", "Trạng thái", "Ngày đặt", "Check-in lúc"])
    for t in participants(event):
        writer.writerow([
            t.code, t.booking_ref, t.user.full_name, t.user.mssv or "",
            t.user.email, t.ticket_type.name,
            t.price, t.get_status_display(),
            timezone.localtime(t.created_at).strftime("%d/%m/%Y %H:%M"),
            timezone.localtime(t.checked_in_at).strftime("%d/%m/%Y %H:%M")
            if t.checked_in_at else "",
        ])
    return response
