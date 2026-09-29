"""Service cho M6 - Phản hồi & thống kê."""
from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from organizing.models import Task, TaskStatus
from registrations.models import Ticket, TicketStatus

from .models import Feedback


class FeedbackError(Exception):
    """Lỗi nghiệp vụ khi gửi phản hồi."""


def can_submit_feedback(user, event):
    """
    F6.1 - Điều kiện gửi đánh giá:
      1. Đã check-in sự kiện này (không dự thì không đánh giá).
      2. Trong vòng 7 ngày sau sự kiện.
      3. Chưa từng gửi.

    Trả về (được_gửi: bool, lý_do_nếu_không: str).
    """
    if not user.is_authenticated:
        return False, "Bạn cần đăng nhập."

    checked_in = Ticket.objects.filter(
        user=user, event=event, status=TicketStatus.CHECKED_IN).exists()
    if not checked_in:
        return False, "Chỉ người đã check-in sự kiện mới được gửi đánh giá."

    days = settings.FEEDBACK_WINDOW_DAYS
    if timezone.now() > event.starts_at + timezone.timedelta(days=days):
        return False, f"Đã quá thời hạn gửi đánh giá ({days} ngày sau sự kiện)."

    if Feedback.objects.filter(user=user, event=event).exists():
        return False, "Bạn đã gửi đánh giá cho sự kiện này."

    return True, ""


def submit_feedback(user, event, rating, content):
    """Lưu đánh giá sau khi kiểm tra đủ điều kiện."""
    ok, reason = can_submit_feedback(user, event)
    if not ok:
        raise FeedbackError(reason)
    return Feedback.objects.create(event=event, user=user,
                                   rating=rating, content=content)


def event_statistics(event):
    """
    F6.3 - Thống kê một sự kiện.

    Dùng aggregate của CSDL thay vì đếm bằng Python để không phải tải hết
    dữ liệu lên bộ nhớ (vấn đề N+1 query).
    """
    tickets = Ticket.objects.filter(event=event)
    active = tickets.exclude(status=TicketStatus.CANCELLED)

    sold = active.count()
    checked_in = tickets.filter(status=TicketStatus.CHECKED_IN).count()
    revenue = (tickets.filter(status__in=[TicketStatus.CONFIRMED,
                                          TicketStatus.CHECKED_IN])
               .aggregate(total=Sum("price"))["total"] or 0)

    # Số vé theo từng loại
    by_type = (active.values("ticket_type__name")
               .annotate(count=Count("id"))
               .order_by("ticket_type__name"))

    fb = Feedback.objects.filter(event=event).aggregate(
        avg=Avg("rating"), n=Count("id"))

    # Phân bố số sao 1..5, dùng cho biểu đồ. Đếm bằng 1 query rồi đổ vào list
    # 5 phần tử, thay vì chạy 5 query riêng.
    counts = dict(Feedback.objects.filter(event=event)
                  .values_list("rating")
                  .annotate(n=Count("id")))
    rating_distribution = [counts.get(star, 0) for star in range(1, 6)]

    tasks = Task.objects.filter(event=event)
    task_total = tasks.count()
    task_done = tasks.filter(status=TaskStatus.DONE).count()
    on_time = sum(1 for t in tasks if t.is_done_on_time is True)

    return {
        "sold": sold,
        "checked_in": checked_in,
        "checkin_rate": round(checked_in * 100 / sold) if sold else 0,
        "pending": tickets.filter(status=TicketStatus.PENDING).count(),
        "cancelled": tickets.filter(status=TicketStatus.CANCELLED).count(),
        "revenue": revenue,
        "by_type": list(by_type),
        "rating_avg": round(fb["avg"], 1) if fb["avg"] else None,
        "rating_count": fb["n"],
        "rating_distribution": rating_distribution,
        "task_total": task_total,
        "task_done": task_done,
        "task_on_time_rate": round(on_time * 100 / task_done) if task_done else 0,
    }


def semester_overview():
    """F6.4 - So sánh các sự kiện: số người tham gia và điểm đánh giá."""
    from events.models import Event, EventStatus

    rows = []
    for event in Event.objects.exclude(status=EventStatus.DRAFT).order_by("starts_at"):
        stat = event_statistics(event)
        rows.append({"event": event, **stat})
    return rows
