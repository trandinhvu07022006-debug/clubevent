"""View cho M2 - Quản lý sự kiện."""
import calendar as pycalendar
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import lead_required
from core import once
from core.pagination import paginate
from core.qr import qr_data_uri
from feedback.services import event_statistics
from registrations.models import WaitlistEntry, WaitlistStatus

from .forms import EventForm, TicketTypeForm
from .models import CATEGORY_ICONS, Event, EventCategory, EventStatus
from .services import (cancel_event, cert_token, certificate_ticket, event_ics,
                       events_for_calendar, mask_mssv, upcoming_for_user,
                       verify_certificate)


def event_list(request):
    """F2.5 - Danh sách sự kiện, có lọc trạng thái và tìm theo tên."""
    status = request.GET.get("status", "")
    keyword = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    when = request.GET.get("when", "")
    # Giá trị lạ trên URL -> bỏ qua, không lỗi
    if status not in EventStatus.values:
        status = ""
    if category not in EventCategory.values:
        category = ""

    events = Event.objects.prefetch_related("ticket_types")
    # Người thường không thấy sự kiện đang chuẩn bị (bản nháp của BTC)
    if not (request.user.is_authenticated and request.user.is_staff_btc):
        events = events.exclude(status=EventStatus.DRAFT)
    if status:
        events = events.filter(status=status)
    if category:
        events = events.filter(category=category)
    if when == "upcoming":
        events = events.filter(starts_at__gte=timezone.now()).order_by("starts_at")
    elif when == "past":
        events = events.filter(starts_at__lt=timezone.now())
    else:
        when = ""
    if keyword:
        events = events.filter(Q(name__icontains=keyword)
                               | Q(location__icontains=keyword)
                               | Q(description__icontains=keyword))

    page_obj, querystring = paginate(request, events, per_page=9)
    return render(request, "events/list.html", {
        "events": page_obj,          # lặp qua page_obj cho ra các item của trang
        "page_obj": page_obj,
        "querystring": querystring,
        "statuses": EventStatus.choices,
        "categories": [(v, l, CATEGORY_ICONS[v]) for v, l in EventCategory.choices],
        "current_status": status,
        "current_category": category,
        "current_when": when,
        "keyword": keyword,
        "upcoming_mine": upcoming_for_user(request.user),
    })


def event_detail(request, pk):
    """F2.5 - Chi tiết sự kiện, hiển thị số chỗ còn lại từng loại vé."""
    event = get_object_or_404(
        Event.objects.prefetch_related("ticket_types"), pk=pk)

    user = request.user
    # Bản nháp chỉ BTC xem được
    if event.status == EventStatus.DRAFT and not (
            user.is_authenticated and user.is_staff_btc):
        raise Http404

    # Số vé user đang giữ, để biết còn được đặt bao nhiêu
    my_tickets = []
    my_waitlist = {}
    can_certificate = False
    if user.is_authenticated:
        my_tickets = event.tickets.filter(user=user).exclude(status="CANCELLED")
        # F4.8 - lượt chờ của user theo từng loại vé, kèm vị trí hiện tại
        for entry in WaitlistEntry.objects.filter(
                user=user, ticket_type__event=event, status=WaitlistStatus.WAITING):
            my_waitlist[entry.ticket_type_id] = entry
        can_certificate = certificate_ticket(user, event) is not None

    ticket_types = list(event.ticket_types.all())
    for tt in ticket_types:
        tt.my_wait = my_waitlist.get(tt.pk)

    my_ticket_count = len(my_tickets)
    limit = settings.MAX_TICKETS_PER_USER_PER_EVENT
    return render(request, "events/detail.html", {
        "event": event,
        "ticket_types": ticket_types,
        "has_available": any(not tt.is_sold_out for tt in ticket_types),
        "my_ticket_count": my_ticket_count,
        "max_tickets": limit,
        "can_book_more": max(limit - my_ticket_count - len(my_waitlist), 0),
        "can_certificate": can_certificate,
        "share_url": request.build_absolute_uri(event.get_absolute_url()),
        "stat": event_statistics(event) if (
            user.is_authenticated and user.is_lead) else None,
    })


@lead_required
def event_create(request):
    """F2.1 - Tạo sự kiện mới, trạng thái ban đầu là Đang chuẩn bị."""
    form = EventForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and not once.consume(request):
        messages.info(request, "Yêu cầu này đã được gửi rồi - bỏ qua lần bấm trùng.")
        return redirect("events:list")
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.created_by = request.user
        event.save()
        messages.success(request,
                         "Đã tạo sự kiện. Bước tiếp theo: thêm loại vé rồi mở đăng ký.")
        return redirect("events:detail", pk=event.pk)
    return render(request, "events/form.html", {"form": form, "is_new": True})


@lead_required
def event_update(request, pk):
    """F2.3 - Sửa sự kiện. Không sửa được sự kiện đã huỷ hoặc đã diễn ra."""
    event = get_object_or_404(Event, pk=pk)
    if event.status in (EventStatus.CANCELLED, EventStatus.DONE):
        messages.error(request, "Không sửa được sự kiện đã huỷ hoặc đã diễn ra.")
        return redirect("events:detail", pk=pk)

    form = EventForm(request.POST or None, request.FILES or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã cập nhật sự kiện.")
        return redirect("events:detail", pk=pk)
    return render(request, "events/form.html",
                  {"form": form, "event": event, "is_new": False})


@require_POST
@lead_required
def event_set_status(request, pk):
    """
    F2.4 - Chuyển trạng thái sự kiện, kiểm tra qua bảng ALLOWED_TRANSITIONS.

    Nhờ máy trạng thái mà không thể nhảy trạng thái sai, ví dụ từ Đã huỷ
    quay lại Mở đăng ký.
    """
    event = get_object_or_404(Event, pk=pk)
    new_status = request.POST.get("status", "")

    if not event.can_change_to(new_status):
        messages.error(request,
                       f"Không thể chuyển từ '{event.get_status_display()}' "
                       f"sang trạng thái này.")
        return redirect("events:detail", pk=pk)

    old = event.get_status_display()
    # F2.3 - huỷ sự kiện thì huỷ luôn toàn bộ vé, lượt chờ và báo cho mọi người
    if new_status == EventStatus.CANCELLED:
        cancel_event(request.user, event)
    else:
        event.status = new_status
        event.save(update_fields=["status"])
    messages.success(request,
                     f"Trạng thái: {old} -> {event.get_status_display()}.")
    return redirect("events:detail", pk=pk)


@lead_required
def ticket_type_create(request, pk):
    """F2.2 - Thêm loại vé cho sự kiện."""
    event = get_object_or_404(Event, pk=pk)
    # Chặn ở server, không chỉ ẩn nút trên giao diện
    if event.status in (EventStatus.CANCELLED, EventStatus.DONE):
        messages.error(request, "Không thêm loại vé cho sự kiện đã huỷ hoặc đã diễn ra.")
        return redirect("events:detail", pk=pk)
    form = TicketTypeForm(request.POST or None, event=event)
    if request.method == "POST" and form.is_valid():
        ticket_type = form.save(commit=False)
        ticket_type.event = event
        ticket_type.save()
        messages.success(request, f"Đã thêm loại vé '{ticket_type.name}'.")
        return redirect("events:detail", pk=pk)
    return render(request, "events/ticket_type_form.html",
                  {"form": form, "event": event})


@require_POST
@lead_required
def ticket_type_delete(request, pk):
    """Xoá loại vé. Không xoá được nếu đã có người đặt. Bắt buộc POST (chống CSRF qua link)."""
    from .models import TicketType

    ticket_type = get_object_or_404(TicketType, pk=pk)
    event_id = ticket_type.event_id
    if ticket_type.sold > 0:
        messages.error(request,
                       "Loại vé này đã có người đăng ký, không xoá được.")
    else:
        ticket_type.delete()
        messages.success(request, "Đã xoá loại vé.")
    return redirect("events:detail", pk=event_id)


@lead_required
def dashboard(request):
    """F6.3 + F6.4 - Trang thống kê tổng hợp cho Trưởng BTC."""
    from feedback.services import semester_overview

    rows = semester_overview()

    # Tính KPI tổng quan
    total_sold = sum(r["sold"] for r in rows)
    total_revenue = sum(r["revenue"] for r in rows)
    total_checked = sum(r["checked_in"] for r in rows)
    checkin_rate = round(total_checked * 100 / total_sold) if total_sold else 0

    # Dữ liệu cho biểu đồ. Truyền sang template bằng |json_script để tránh XSS
    # khi tên sự kiện có ký tự đặc biệt. Tên dài thì cắt bớt cho nhãn đỡ tràn.
    def short(name, limit=28):
        return name if len(name) <= limit else name[:limit - 1] + "…"

    checkin_chart = {
        "labels": [short(r["event"].name) for r in rows],
        "checked": [r["checked_in"] for r in rows],
        "remaining": [max(r["sold"] - r["checked_in"], 0) for r in rows],
    }

    # Chỉ vẽ sự kiện đã có đánh giá, tránh những thanh bằng 0 vô nghĩa
    rated = [r for r in rows if r["rating_avg"]]
    rating_chart = {
        "labels": [short(r["event"].name) for r in rated],
        "values": [r["rating_avg"] for r in rated],
        "counts": [r["rating_count"] for r in rated],
    }

    return render(request, "events/dashboard.html", {
        "rows": rows,
        "checkin_chart": checkin_chart,
        "rating_chart": rating_chart,
        "upcoming": Event.objects.filter(
            status=EventStatus.OPEN, starts_at__gte=timezone.now()).count(),
        "total_sold": total_sold,
        "total_revenue": total_revenue,
        "total_checked": total_checked,
        "checkin_rate": checkin_rate,
    })


def event_ics_download(request, pk):
    """F7.4 - Tải file lịch .ics. Bản nháp chỉ BTC tải được."""
    event = get_object_or_404(Event, pk=pk)
    if event.status == EventStatus.DRAFT and not (
            request.user.is_authenticated and request.user.is_staff_btc):
        raise Http404
    response = HttpResponse(event_ics(event),
                            content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="su-kien-{event.pk}.ics"'
    return response


def event_calendar(request):
    """Lịch sự kiện theo tháng - nhìn nhanh cả tháng có gì."""
    today = timezone.localdate()
    try:
        year = int(request.GET.get("y", today.year))
        month = int(request.GET.get("m", today.month))
        date(year, month, 1)
    except (TypeError, ValueError):
        year, month = today.year, today.month

    by_day = {}
    for ev in events_for_calendar(request.user, year, month):
        by_day.setdefault(timezone.localtime(ev.starts_at).day, []).append(ev)

    weeks = []
    for week in pycalendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        weeks.append([{"day": d, "events": by_day.get(d, []),
                       "is_today": (year, month, d) == (today.year, today.month, today.day)}
                      for d in week])

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    return render(request, "events/calendar.html", {
        "weeks": weeks, "year": year, "month": month,
        "prev": {"y": prev_y, "m": prev_m}, "next": {"y": next_y, "m": next_m},
        "today": today,
        "weekdays": ["T2", "T3", "T4", "T5", "T6", "T7", "CN"],
        "month_events": [e for d in sorted(by_day) for e in by_day[d]],
    })


@login_required
def certificate(request, pk):
    """F8.2 - Giấy chứng nhận tham gia, trang HTML in được (A4 ngang)."""
    event = get_object_or_404(Event.objects.select_related("created_by"), pk=pk)
    ticket = certificate_ticket(request.user, event)
    if ticket is None:
        raise Http404
    token = cert_token(ticket)
    verify_url = settings.SITE_URL + reverse("events:cert_verify",
                                             args=[ticket.code, token])
    return render(request, "events/certificate.html", {
        "event": event,
        "ticket": ticket,
        "person": request.user,
        "issued_on": timezone.localdate(),
        "verify_url": verify_url,
        "verify_qr": qr_data_uri(verify_url),
    })


def certificate_verify(request, code, token):
    """
    F8.2 - Trang xác thực CÔNG KHAI. Mọi lý do không hợp lệ đều cùng một
    thông báo; chỉ hiện dữ liệu cá nhân tối thiểu (MSSV đã che).
    """
    ticket = verify_certificate(code, token)
    return render(request, "events/certificate_verify.html", {
        "ticket": ticket,
        "masked_mssv": mask_mssv(ticket.user.mssv or "") if ticket else "",
    })
