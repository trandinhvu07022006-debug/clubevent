"""
Số liệu cho trang chủ công khai và trang Tổng quan theo vai trò.

Tách khỏi view để test được riêng và để view chỉ lo "ai được xem gì".
Mọi hàm ở đây CHỈ ĐỌC, không ghi gì vào CSDL.
"""
from django.conf import settings
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Role, User
from events.models import Event, EventStatus
from events.services import upcoming_for_user
from feedback.models import Feedback
from organizing.models import Department, Task, TaskStatus
from organizing.services import departments_with_stats
from recruitment.models import Application, RecruitmentRound
from registrations.models import Ticket, TicketStatus
from registrations.services import user_stats


# ---------------------------------------------------------------------------
# TRANG CHỦ CÔNG KHAI
# ---------------------------------------------------------------------------
def public_events(limit=3):
    """Sự kiện sắp tới đang mở đăng ký (ưu tiên) rồi tới sắp diễn ra."""
    now = timezone.now()
    return list(Event.objects.filter(
        starts_at__gte=now,
        status__in=[EventStatus.OPEN, EventStatus.CLOSED],
    ).prefetch_related("ticket_types").order_by("starts_at")[:limit])


def club_numbers():
    """
    Con số THẬT của CLB cho dải "Con số nói lên tất cả".
    Không bịa số: CSDL trống thì trả 0 và template tự ẩn dải này.
    """
    return {
        "events_done": Event.objects.filter(status=EventStatus.DONE).count(),
        "events_total": Event.objects.exclude(
            status__in=[EventStatus.DRAFT, EventStatus.CANCELLED]).count(),
        "members": User.objects.filter(is_locked=False, is_superuser=False).count(),
        "checkins": Ticket.objects.filter(status=TicketStatus.CHECKED_IN).count(),
        "departments": Department.objects.count(),
    }


def can_apply(user) -> bool:
    """Được ứng tuyển thành viên không (theo RECRUIT_KMA_ONLY)."""
    return not settings.RECRUIT_KMA_ONLY or user.is_kma_student


# ---------------------------------------------------------------------------
# TỔNG QUAN - KHÔNG GIAN CÁ NHÂN (mọi người dùng)
# ---------------------------------------------------------------------------
def onboarding_steps(user):
    """
    Danh sách "Bắt đầu" kiểu Notion/Linear: vài bước để dùng hệ thống trọn vẹn.
    Trả về (steps, done_count). Xong hết thì template ẩn khối này.
    """
    has_ticket = Ticket.objects.filter(user=user).exists()
    steps = [
        {"label": ("Hoàn thiện hồ sơ (họ tên, MSSV)" if user.is_kma_student
                   else "Hoàn thiện hồ sơ (họ tên, số điện thoại)"),
         "done": bool(user.full_name and (user.mssv if user.is_kma_student else user.phone)),
         "url": reverse("accounts:profile"), "icon": "bi-person-vcard"},
        {"label": "Thêm ảnh đại diện để BTC nhận ra bạn khi check-in",
         "done": bool(user.avatar), "url": reverse("accounts:profile"),
         "icon": "bi-camera"},
        {"label": "Thêm email để nhận vé và nhắc lịch",
         "done": bool(user.email), "url": reverse("accounts:profile"),
         "icon": "bi-envelope"},
        {"label": "Đăng ký sự kiện đầu tiên",
         "done": has_ticket, "url": reverse("events:list") + "?when=upcoming",
         "icon": "bi-ticket-perforated"},
    ]
    if not user.is_club_member and can_apply(user) and RecruitmentRound.current():
        steps.append({
            "label": "Ứng tuyển thành viên CLB (đợt tuyển đang mở)",
            "done": Application.objects.filter(user=user).exists(),
            "url": reverse("recruitment:home"), "icon": "bi-person-plus"})
    if user.is_staff_btc:
        steps.append({
            "label": "Tham gia một Ban để nhận việc chung",
            "done": Department.objects.filter(
                Q(members=user) | Q(lead=user)).exists(),
            "url": reverse("organizing:department_list"), "icon": "bi-diagram-3"})
    return steps, sum(1 for s in steps if s["done"])


def personal_space(user):
    """Vé sắp tới, vé chờ thanh toán, việc cần làm, gợi ý sự kiện."""
    now = timezone.now()
    pending = (Ticket.objects.filter(user=user, status=TicketStatus.PENDING)
               .select_related("event").order_by("created_at"))
    pending_refs = {}
    for t in pending:
        g = pending_refs.setdefault(t.booking_ref or t.code, {
            "event": t.event, "count": 0, "amount": 0, "ref": t.booking_ref or t.code})
        g["count"] += 1
        g["amount"] += t.price

    # Sự kiện vừa dự (đã check-in) trong thời hạn đánh giá mà chưa đánh giá
    window = now - timezone.timedelta(days=settings.FEEDBACK_WINDOW_DAYS)
    rated = Feedback.objects.filter(user=user).values_list("event_id", flat=True)
    feedback_due = list(Event.objects.filter(
        tickets__user=user, tickets__status=TicketStatus.CHECKED_IN,
        starts_at__gte=window, starts_at__lte=now,
    ).exclude(pk__in=rated).distinct()[:3])

    # Gợi ý: sự kiện đang mở mà mình CHƯA có vé, gần nhất trước
    mine = Ticket.objects.filter(user=user).exclude(
        status=TicketStatus.CANCELLED).values_list("event_id", flat=True)
    suggestions = list(Event.objects.filter(
        status=EventStatus.OPEN, starts_at__gte=now, register_deadline__gte=now,
    ).exclude(pk__in=mine).prefetch_related("ticket_types")
        .order_by("starts_at")[:3])

    steps, steps_done = onboarding_steps(user)
    # Khách: tình trạng đơn ứng tuyển / đợt tuyển. Thành viên: Ban của mình.
    latest_app = (Application.objects.filter(user=user)
                  .select_related("round", "department").first())
    my_departments = (list(Department.objects.filter(Q(members=user) | Q(lead=user))
                           .distinct().select_related("lead"))
                      if user.is_club_member else [])
    return {
        "latest_app": latest_app,
        "can_apply": can_apply(user),
        "recruit_round": RecruitmentRound.current(),
        "my_departments_simple": my_departments,
        "upcoming": upcoming_for_user(user, limit=4),
        "pending_groups": list(pending_refs.values()),
        "feedback_due": feedback_due,
        "suggestions": suggestions,
        "stats": user_stats(user),
        "steps": steps,
        "steps_done": steps_done,
        "steps_total": len(steps),
    }


# ---------------------------------------------------------------------------
# TỔNG QUAN - KHÔNG GIAN TỔ CHỨC (BTC, Trưởng BTC, Admin)
# ---------------------------------------------------------------------------
def _today_start():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def org_space(user):
    """Số liệu cho người làm tổ chức, mở rộng dần theo vai trò."""
    now = timezone.now()
    soon = now + timezone.timedelta(days=3)
    live = Q(event__isnull=True) | ~Q(event__status=EventStatus.CANCELLED)

    my_open = (Task.objects.filter(live, assignee=user)
               .exclude(status=TaskStatus.DONE)
               .select_related("event", "department"))
    task_counts = my_open.aggregate(
        open=Count("id"),
        overdue=Count("id", filter=Q(deadline__lt=now)),
        due_soon=Count("id", filter=Q(deadline__gte=now, deadline__lte=soon)),
        doing=Count("id", filter=Q(status=TaskStatus.DOING)),
    )
    my_depts_qs = Department.objects.filter(Q(members=user) | Q(lead=user)).distinct()
    claimable = (Task.objects.filter(live, department__in=my_depts_qs,
                                     assignee__isnull=True)
                 .exclude(status=TaskStatus.DONE).count())
    data = {
        "my_tasks": list(my_open.order_by("deadline")[:5]),
        "task_counts": task_counts,
        "my_departments": departments_with_stats(my_depts_qs),
        "claimable_count": claimable,
        "pending_payments": Ticket.objects.filter(status=TicketStatus.PENDING)
                                  .values("booking_ref").distinct().count(),
        # Lọc theo KHOẢNG giờ của hôm nay, không dùng starts_at__date: trên MySQL
        # lookup theo ngày cần bảng múi giờ (xem events_for_calendar).
        "checkin_today": list(Event.objects.filter(
            status__in=[EventStatus.OPEN, EventStatus.CLOSED],
            starts_at__gte=_today_start(), starts_at__lt=_today_start()
            + timezone.timedelta(days=1)).order_by("starts_at")[:3]),
    }

    if user.is_lead:
        active = list(Event.objects.filter(
            status__in=[EventStatus.DRAFT, EventStatus.OPEN, EventStatus.CLOSED],
        ).prefetch_related("tasks", "ticket_types").order_by("starts_at")[:6])
        data["active_events"] = active
        data["all_departments"] = departments_with_stats()
        data["assigned_open"] = (Task.objects.filter(live, created_by=user)
                                 .exclude(status=TaskStatus.DONE).count())

    if user.is_admin_role:
        week_ago = now - timezone.timedelta(days=7)
        data["role_counts"] = dict(User.objects.values_list("role")
                                   .annotate(n=Count("id")))
        data["role_rows"] = [(label, data["role_counts"].get(value, 0))
                             for value, label in Role.choices]
        data["new_users_week"] = User.objects.filter(created_at__gte=week_ago).count()
        data["locked_users"] = User.objects.filter(is_locked=True).count()
        data["recent_logs"] = list(AuditLog.objects.select_related("user")[:6])
    return data
