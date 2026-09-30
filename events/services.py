from django.db import transaction
from registrations.models import TicketStatus
from accounts.models import AuditLog, User
from events.models import Event, EventStatus
from notifications.services import notify_many, NotificationKind

@transaction.atomic
def cancel_event(user: User, event: Event):
    """B1: Huỷ sự kiện, huỷ vé và gửi thông báo."""
    # 1. LẤY DANH SÁCH NGƯỜI BỊ ẢNH HƯỞNG TRƯỚC — sau .update() là mất thông tin
    affected_user_ids = list(event.tickets
                             .exclude(status=TicketStatus.CANCELLED)
                             .values_list("user_id", flat=True).distinct())
    
    # 2. Đổi trạng thái sự kiện (kiểm tra ALLOWED_TRANSITIONS ở view)
    # 3. Huỷ vé hàng loạt
    event.tickets.exclude(status=TicketStatus.CANCELLED).update(status=TicketStatus.CANCELLED)
    # 4. Trả sold về 0 cho mọi loại vé của sự kiện (sự kiện đã huỷ, cho số liệu nhất quán)
    event.ticket_types.update(sold=0)
    # 5. Huỷ mọi mục danh sách chờ còn hiệu lực (khi đã có F4.8) - TODO
    # 6. AuditLog
    AuditLog.write(user, "Huỷ sự kiện", event.name)
    
    # 7. notify_many(...) qua on_commit — chỉ báo MỖI NGƯỜI MỘT LẦN dù họ giữ 4 vé
    users_to_notify = list(User.objects.filter(id__in=affected_user_ids))
    transaction.on_commit(lambda: notify_many(
        users_to_notify,
        kind=NotificationKind.EVENT_CANCELLED,
        title=f"Sự kiện bị huỷ: {event.name}",
        message=f"Sự kiện {event.name} đã bị huỷ. Thành thật xin lỗi bạn. Nếu bạn có vé đã thanh toán, BTC sẽ liên hệ hoàn tiền.",
        url=f"/sukien/{event.pk}/",
    ))
    
    return affected_user_ids
