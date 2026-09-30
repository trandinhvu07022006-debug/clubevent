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

    # Mọi con số về vé lấy bằng MỘT truy vấn aggregate (trước đây 5 truy vấn)
    t = tickets.aggregate(
        sold=Count("id", filter=~Q(status=TicketStatus.CANCELLED)),
        checked_in=Count("id", filter=Q(status=TicketStatus.CHECKED_IN)),
        pending=Count("id", filter=Q(status=TicketStatus.PENDING)),
        cancelled=Count("id", filter=Q(status=TicketStatus.CANCELLED)),
        revenue=Sum("price", filter=Q(status__in=[TicketStatus.CONFIRMED,
                                                  TicketStatus.CHECKED_IN]), default=0),
    )
    sold, checked_in, revenue = t["sold"], t["checked_in"], t["revenue"]

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
        "pending": t["pending"],
        "cancelled": t["cancelled"],
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

    Không gọi event_statistics() cho từng sự kiện (N+1 query). Mỗi bảng (vé,
    phản hồi, công việc) được gom nhóm theo sự kiện bằng MỘT truy vấn riêng:
    tổng cộng 4 truy vấn dù có bao nhiêu sự kiện.

    KHÔNG gộp cả 3 bảng vào một annotate(): JOIN nhiều bảng một-nhiều cùng lúc
    sẽ nhân dòng, ví dụ 30 vé × 8 phản hồi × 6 công việc làm Count("tickets")
    ra 1440 và doanh thu bị nhân 48 lần.
    """
    from events.models import Event, EventStatus

    events = list(Event.objects.exclude(status=EventStatus.DRAFT).order_by("starts_at"))
    ids = [e.pk for e in events]

    paid = [TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN]
    ticket_stats = {r["event_id"]: r for r in (
        Ticket.objects.filter(event_id__in=ids).values("event_id").annotate(
            sold=Count("id", filter=~Q(status=TicketStatus.CANCELLED)),
            checked_in=Count("id", filter=Q(status=TicketStatus.CHECKED_IN)),
            pending=Count("id", filter=Q(status=TicketStatus.PENDING)),
            cancelled=Count("id", filter=Q(status=TicketStatus.CANCELLED)),
            revenue=Sum("price", filter=Q(status__in=paid), default=0),
        ).order_by())}
    rating_stats = {r["event_id"]: r for r in (
        Feedback.objects.filter(event_id__in=ids).values("event_id").annotate(
            avg=Avg("rating"), n=Count("id")).order_by())}

    # Tỉ lệ đúng hạn cần so sánh done_at với deadline nên tính bằng Python,
    # nhưng vẫn chỉ 1 truy vấn cho mọi sự kiện.
    task_stats = {}
    for t in (Task.objects.filter(event_id__in=ids)
              .only("event_id", "status", "deadline", "done_at")):
        s = task_stats.setdefault(t.event_id, {"total": 0, "done": 0,
                                               "timed": 0, "on_time": 0})
        s["total"] += 1
        if t.status == TaskStatus.DONE:
            s["done"] += 1
            if t.deadline and t.done_at:
                s["timed"] += 1
                s["on_time"] += t.done_at <= t.deadline

    rows = []
    for event in events:
        tk = ticket_stats.get(event.pk, {})
        fb = rating_stats.get(event.pk, {})
        ts = task_stats.get(event.pk, {})
        sold, checked_in = tk.get("sold", 0), tk.get("checked_in", 0)
        rows.append({
            "event": event,
            "sold": sold,
            "checked_in": checked_in,
            "checkin_rate": round(checked_in * 100 / sold) if sold else 0,
            "pending": tk.get("pending", 0),
            "cancelled": tk.get("cancelled", 0),
            "revenue": tk.get("revenue", 0),
            "by_type": [],  # không cần chi tiết loại vé ở trang so sánh tổng
            "rating_avg": round(fb["avg"], 1) if fb.get("avg") else None,
            "rating_count": fb.get("n", 0),
            "rating_distribution": [],
            "task_total": ts.get("total", 0),
            "task_done": ts.get("done", 0),
            "task_on_time_rate": (round(ts["on_time"] * 100 / ts["timed"])
                                  if ts.get("timed") else 0),
        })
    return rows
