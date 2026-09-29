"""
Các filter dùng chung cho giao diện.

Đặt trong app events nhưng dùng được ở mọi template, chỉ cần {% load ui %}.
"""
from django import template

register = template.Library()


@register.filter
def cover_index(event):
    """
    Chọn ảnh bìa mặc định cho sự kiện chưa upload ảnh.

    Chia lấy dư theo id để mỗi sự kiện có một ảnh cố định, không đổi mỗi
    lần tải trang. Ảnh nằm trong static/ nên không bị mất khi deploy lại.
    """
    return (event.pk or 0) % 4 + 1


@register.filter
def initials(user):
    """Lấy 2 chữ cái đầu của họ tên, dùng làm avatar khi chưa có ảnh."""
    name = (getattr(user, "full_name", "") or getattr(user, "username", "")).strip()
    if not name:
        return "?"
    parts = name.split()
    if len(parts) == 1:
        return parts[0][:2].upper()
    # Tiếng Việt viết họ trước tên sau, nên lấy chữ đầu của TÊN cho dễ nhận
    return (parts[-1][:1] + parts[0][:1]).upper()


@register.filter
def vnd(value):
    """
    Định dạng tiền Việt: 1400000 -> 1.400.000

    Python format dùng dấu phẩy nên phải đổi sang dấu chấm cho đúng kiểu VN.
    """
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return value
