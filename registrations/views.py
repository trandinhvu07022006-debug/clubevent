"""View cho M4 - Đăng ký vé và M5 - Check-in."""
import base64
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import lead_required, staff_required
from core.pagination import paginate
from events.models import Event

from .models import Ticket, TicketStatus
from .services import (CHECKIN_OK, CHECKIN_USED, BookingError, book_tickets,
                       cancel_ticket, check_in, confirm_payment, participants)


def qr_data_uri(text):
    """
    Sinh mã QR dạng data URI để nhúng thẳng vào thẻ <img>, không cần lưu file.

    Nếu máy chưa cài thư viện qrcode thì trả None, template sẽ hiện mã chữ
    thay thế — vẫn check-in được bằng cách nhập tay.
    """
    try:
        import qrcode
    except ImportError:
        return None
    img = qrcode.make(text)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


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
    """F4.2 - Vé của tôi, kèm mã QR."""
    tickets = (Ticket.objects
               .filter(user=request.user)
               .select_related("event", "ticket_type")
               .order_by("-created_at"))
    # Gắn QR trực tiếp vào từng vé để template chỉ cần {{ ticket.qr }}.
    # Chỉ sinh QR cho vé còn hiệu lực, đỡ tốn thời gian render.
    for ticket in tickets:
        ticket.qr = qr_data_uri(ticket.code) if ticket.is_active else None
    return render(request, "registrations/my_tickets.html", {"tickets": tickets})


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
    """F4.4 - Danh sách vé chờ xác nhận thanh toán."""
    keyword = request.GET.get("q", "").strip()
    tickets = (Ticket.objects
               .filter(status=TicketStatus.PENDING)
               .select_related("event", "ticket_type", "user")
               .order_by("created_at"))
    if keyword:
        tickets = tickets.filter(code__icontains=keyword)
    return render(request, "registrations/payment_list.html",
                  {"tickets": tickets, "keyword": keyword})


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

    Kết quả trả về 3 loại, hiển thị bằng 3 màu khác nhau để BTC nhìn là
    biết ngay, không cần đọc chữ:
      xanh = hợp lệ, vàng = đã dùng rồi, đỏ = không hợp lệ.
    """
    event = get_object_or_404(Event, pk=event_id)
    result = ticket = None
    note = ""

    if request.method == "POST":
        code = request.POST.get("code", "")
        result, ticket, note = check_in(request.user, code, event=event)

    total = event.tickets.exclude(status=TicketStatus.CANCELLED).count()
    done = event.tickets.filter(status=TicketStatus.CHECKED_IN).count()

    return render(request, "registrations/checkin.html", {
        "event": event,
        "result": result,
        "ticket": ticket,
        "note": note,
        "css_class": {CHECKIN_OK: "success", CHECKIN_USED: "warning"}.get(
            result, "danger"),
        "total": total,
        "done": done,
        "percent": round(done * 100 / total) if total else 0,
    })


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
    import csv

    from django.http import HttpResponse

    event = get_object_or_404(Event, pk=event_id)
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = (
        f'attachment; filename="nguoi-tham-gia-{event.pk}.csv"')

    writer = csv.writer(response)
    writer.writerow(["Mã vé", "Họ tên", "MSSV", "Loại vé", "Giá",
                     "Trạng thái", "Ngày đặt", "Check-in lúc"])
    for t in participants(event):
        writer.writerow([
            t.code, t.user.full_name, t.user.mssv or "", t.ticket_type.name,
            t.price, t.get_status_display(),
            t.created_at.strftime("%d/%m/%Y %H:%M"),
            t.checked_in_at.strftime("%d/%m/%Y %H:%M") if t.checked_in_at else "",
        ])
    return response
