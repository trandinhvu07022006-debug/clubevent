from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from organizing.models import Department, Task, TaskStatus
from recruitment.models import Application, ApplicationStatus, RecruitmentRound
from registrations.models import Ticket, TicketStatus


def site_info(request):
    """
    Thông tin CLB (settings.CLUB_INFO) + có đang mở đợt tuyển thành viên không
    (để menu hiện nhãn "Đang mở"). Cache 60s: trang công khai tải nhiều nhất.
    """
    recruiting = cache.get("recruit_open")
    if recruiting is None:
        now = timezone.now()
        recruiting = RecruitmentRound.objects.filter(
            opens_at__lte=now, closes_at__gte=now).exists()
        cache.set("recruit_open", recruiting, 60)
    return {"club": settings.CLUB_INFO, "recruit_open": recruiting}


def user_badges(request):
    """
    Context processor trả về các con số (badge) cho sidebar và chuông:
    - unread_count: thông báo chưa đọc (F7.3) - mọi user đã đăng nhập.
      KHÔNG cache: vừa bấm "đọc hết" mà chuông vẫn hiện số thì rất khó chịu.
      Truy vấn chạy trên index (user, is_read) nên rẻ.
    - recent_notifications: 5 thông báo mới nhất cho dropdown chuông. Truyền
      dạng hàm để template chỉ truy vấn khi thật sự dùng tới (lazy).
    - Xác nhận TT / Việc của tôi / Việc Ban chờ nhận / quyền giao việc / đơn
      ứng tuyển chờ duyệt: chỉ cho BTC, cache 60s.
    Khách (chưa đăng nhập): trả {} và không truy vấn gì.
    """
    if not request.user.is_authenticated:
        return {}

    user = request.user
    data = {
        "unread_count": user.notifications.filter(is_read=False).count(),
        "recent_notifications": lambda: list(user.notifications.all()[:5]),
    }

    # Chỉ tính badge cho Ban tổ chức vì các mục này dành riêng cho BTC
    if not user.is_staff_btc:
        return data

    cache_key = f"user_badges_{user.id}"
    badges = cache.get(cache_key)

    if badges is None:
        my_depts = Department.objects.filter(Q(members=user) | Q(lead=user))
        led = Department.objects.filter(lead=user)
        is_dept_lead = led.exists()
        apps = Application.objects.filter(status=ApplicationStatus.PENDING)
        if not user.is_lead:
            apps = apps.filter(department__in=led)
        badges = {
            'my_tasks_count': Task.objects.filter(
                assignee=user,
                status__in=[TaskStatus.TODO, TaskStatus.DOING]
            ).count(),
            'pending_tickets_count': Ticket.objects.filter(
                status=TicketStatus.PENDING
            ).values("booking_ref").distinct().count(),
            # Việc giao cho Ban mình mà chưa ai nhận
            'claimable_count': Task.objects.filter(
                department__in=my_depts, assignee__isnull=True,
                status__in=[TaskStatus.TODO, TaskStatus.DOING]
            ).count(),
            # Trưởng ban (không phải Trưởng BTC) cũng giao việc + duyệt đơn Ban mình
            'can_assign': user.is_lead or is_dept_lead,
            'can_review': user.is_lead or is_dept_lead,
            'pending_applications_count': apps.count() if (user.is_lead or is_dept_lead) else 0,
        }
        cache.set(cache_key, badges, 60)

    return {**data, **badges}
