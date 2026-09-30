from django.core.cache import cache
from organizing.models import Task, TaskStatus
from registrations.models import Ticket, TicketStatus


def user_badges(request):
    """
    Context processor trả về các con số (badge) cho sidebar và chuông:
    - unread_count: thông báo chưa đọc (F7.3) — mọi user đã đăng nhập.
      KHÔNG cache: vừa bấm "đọc hết" mà chuông vẫn hiện số thì rất khó chịu.
      Truy vấn chạy trên index (user, is_read) nên rẻ.
    - recent_notifications: 5 thông báo mới nhất cho dropdown chuông. Truyền
      dạng hàm để template chỉ truy vấn khi thật sự dùng tới (lazy).
    - Xác nhận TT / Việc của tôi: chỉ cho BTC, cache 60s.
    Khách (chưa đăng nhập): trả {} và không truy vấn gì.
    """
    if not request.user.is_authenticated:
        return {}

    user = request.user
    data = {
        "unread_count": user.notifications.filter(is_read=False).count(),
        "recent_notifications": lambda: list(user.notifications.all()[:5]),
    }

    # Chỉ tính badge cho Ban tổ chức vì 2 mục này dành riêng cho BTC
    if not user.is_staff_btc:
        return data

    cache_key = f"user_badges_{user.id}"
    badges = cache.get(cache_key)

    if badges is None:
        badges = {
            'my_tasks_count': Task.objects.filter(
                assignee=user,
                status__in=[TaskStatus.TODO, TaskStatus.DOING]
            ).count(),
            'pending_tickets_count': Ticket.objects.filter(
                status=TicketStatus.PENDING
            ).values("booking_ref").distinct().count(),
        }
        cache.set(cache_key, badges, 60)

    return {**data, **badges}
