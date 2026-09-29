"""Service cho M6 - Phản hồi & thống kê."""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from organizing.models import Task, TaskStatus
from registrations.models import Ticket, TicketStatus

from .models import Feedback

if TYPE_CHECKING:
    from accounts.models import User
    from events.models import Event


class FeedbackError(Exception):
    """Lỗi nghiệp vụ khi gửi phản hồi."""


def can_submit_feedback(user: User, event: Event) -> tuple[bool, str]:
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


def submit_feedback(user: User, event: Event, rating: int,
                    content: str) -> Feedback:
    """Lưu đánh giá sau khi kiểm tra đủ điều kiện."""
    ok, reason = can_submit_feedback(user, event)
    if not ok:
        raise FeedbackError(reason)
    return Feedback.objects.create(event=event, user=user,
                                   rating=rating, content=content)


def event_statistics(event: Event) -> dict:
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


def semester_overview() -> list[dict]:
    """
    F6.4 - So sánh các sự kiện: số người tham gia và điểm đánh giá.

    Phiên bản tối ưu: dùng annotate để gộp hầu hết thống kê vào 1 query
    thay vì gọi event_statistics() cho từng sự kiện (N+1 query).
    Trước: 20 sự kiện → 120+ SQL queries.
    Sau: 20 sự kiện → ~3 SQL queries.
    """
    from events.models import Event, EventStatus

    events = (Event.objects
              .exclude(status=EventStatus.DRAFT)
              .annotate(
                  _sold=Count("tickets", filter=~Q(tickets__status=TicketStatus.CANCELLED)),
                  _checked_in=Count("tickets", filter=Q(tickets__status=TicketStatus.CHECKED_IN)),
                  _pending=Count("tickets", filter=Q(tickets__status=TicketStatus.PENDING)),
                  _cancelled=Count("tickets", filter=Q(tickets__status=TicketStatus.CANCELLED)),
                  _revenue=Sum("tickets__price", filter=Q(
                      tickets__status__in=[TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN]),
                      default=0),
                  _rating_avg=Avg("feedbacks__rating"),
                  _rating_count=Count("feedbacks"),
                  _task_total=Count("tasks"),
                  _task_done=Count("tasks", filter=Q(tasks__status=TaskStatus.DONE)),
              )
              .order_by("starts_at"))

    # on_time cần logic Python (so sánh done_at với deadline), nên vẫn phải
    # query tasks riêng, nhưng chỉ 1 query cho tất cả sự kiện.
    event_ids = [e.pk for e in events]
    done_tasks = (Task.objects
                  .filter(event_id__in=event_ids, status=TaskStatus.DONE)
                  .only("event_id", "deadline", "done_at"))
    on_time_map = {}
    for t in done_tasks:
        if t.deadline and t.done_at:
            on_time_map.setdefault(t.event_id, [0, 0])
            on_time_map[t.event_id][1] += 1  # total done
            if t.done_at <= t.deadline:
                on_time_map[t.event_id][0] += 1  # on time

    rows = []
    for event in events:
        done = event._task_done
        ot = on_time_map.get(event.pk, [0, 0])
        rows.append({
            "event": event,
            "sold": event._sold,
            "checked_in": event._checked_in,
            "checkin_rate": round(event._checked_in * 100 / event._sold) if event._sold else 0,
            "pending": event._pending,
            "cancelled": event._cancelled,
            "revenue": event._revenue,
            "by_type": [],  # không cần chi tiết loại vé ở trang so sánh tổng
            "rating_avg": round(event._rating_avg, 1) if event._rating_avg else None,
            "rating_count": event._rating_count,
            "rating_distribution": [],
            "task_total": event._task_total,
            "task_done": done,
            "task_on_time_rate": round(ot[0] * 100 / ot[1]) if ot[1] else 0,
        })
    return rows
