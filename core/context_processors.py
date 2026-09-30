from django.core.cache import cache
from organizing.models import Task, TaskStatus
from registrations.models import Ticket, TicketStatus

def user_badges(request):
    """
    Context processor trả về số lượng thông báo (badge) cho sidebar:
    - Xác nhận TT: vé đang chờ thanh toán.
    - Việc của tôi: task đang TODO, DOING được giao cho user.
    Chỉ query với user có quyền (BTC) và được cache 60s.
    """
    if not request.user.is_authenticated:
        return {}

    user = request.user
    # Chỉ tính badge cho Ban tổ chức vì 2 mục này dành riêng cho BTC
    if not user.is_staff_btc:
        return {}

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
            ).count(),
        }
        cache.set(cache_key, badges, 60)

    return badges
