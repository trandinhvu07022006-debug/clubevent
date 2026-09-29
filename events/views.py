"""View cho M2 - Quản lý sự kiện."""
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import AuditLog
from accounts.permissions import lead_required
from core.pagination import paginate
from feedback.services import event_statistics

from .forms import EventForm, TicketTypeForm
from .models import Event, EventStatus


def event_list(request):
    """F2.5 - Danh sách sự kiện, có lọc trạng thái và tìm theo tên."""
    status = request.GET.get("status", "")
    keyword = request.GET.get("q", "").strip()

    events = Event.objects.prefetch_related("ticket_types")
    # Người thường không thấy sự kiện đang chuẩn bị (bản nháp của BTC)
    if not (request.user.is_authenticated and request.user.is_staff_btc):
        events = events.exclude(status=EventStatus.DRAFT)
    if status:
        events = events.filter(status=status)
    if keyword:
        events = events.filter(Q(name__icontains=keyword)
                               | Q(location__icontains=keyword))

    page_obj, querystring = paginate(request, events, per_page=9)
    return render(request, "events/list.html", {
        "events": page_obj,          # lặp qua page_obj cho ra các item của trang
        "page_obj": page_obj,
        "querystring": querystring,
        "statuses": EventStatus.choices,
        "current_status": status,
        "keyword": keyword,
    })


def event_detail(request, pk):
    """F2.5 - Chi tiết sự kiện, hiển thị số chỗ còn lại từng loại vé."""
    event = get_object_or_404(
        Event.objects.prefetch_related("ticket_types"), pk=pk)

    # Số vé user đang giữ, để biết còn được đặt bao nhiêu
    my_tickets = []
    if request.user.is_authenticated:
        my_tickets = event.tickets.filter(user=request.user).exclude(
            status="CANCELLED")

    return render(request, "events/detail.html", {
        "event": event,
        "my_ticket_count": len(my_tickets),
        "stat": event_statistics(event) if (
            request.user.is_authenticated and request.user.is_lead) else None,
    })


@lead_required
def event_create(request):
    """F2.1 - Tạo sự kiện mới, trạng thái ban đầu là Đang chuẩn bị."""
    form = EventForm(request.POST or None, request.FILES or None)
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

    # F2.3 - huỷ sự kiện thì huỷ luôn toàn bộ vé
    if new_status == EventStatus.CANCELLED:
        event.tickets.exclude(status="CANCELLED").update(status="CANCELLED")
        for ticket_type in event.ticket_types.all():
            ticket_type.sold = 0
            ticket_type.save(update_fields=["sold"])
        AuditLog.write(request.user, "Huỷ sự kiện", event.name)

    old = event.get_status_display()
    event.status = new_status
    event.save(update_fields=["status"])
    messages.success(request,
                     f"Trạng thái: {old} -> {event.get_status_display()}.")
    return redirect("events:detail", pk=pk)


@lead_required
def ticket_type_create(request, pk):
    """F2.2 - Thêm loại vé cho sự kiện."""
    event = get_object_or_404(Event, pk=pk)
    form = TicketTypeForm(request.POST or None, event=event)
    if request.method == "POST" and form.is_valid():
        ticket_type = form.save(commit=False)
        ticket_type.event = event
        ticket_type.save()
        messages.success(request, f"Đã thêm loại vé '{ticket_type.name}'.")
        return redirect("events:detail", pk=pk)
    return render(request, "events/ticket_type_form.html",
                  {"form": form, "event": event})


@lead_required
def ticket_type_delete(request, pk):
    """Xoá loại vé. Không xoá được nếu đã có người đặt."""
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
    })
