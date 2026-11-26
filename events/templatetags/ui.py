"""
Các filter dùng chung cho giao diện.

Đặt trong app events nhưng dùng được ở mọi template, chỉ cần {% load ui %}.
"""
from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from core import once
from core.icons import KMG_SOFT_ICONS

register = template.Library()

_ICON_SIZES = {"sm", "md", "lg", "xl"}


@register.simple_tag
def kmg_icon(name: str, size: str = "md", css_class: str = "", label: str = ""):
    """Render SVG icon nét mềm KMG Soft Icons 1.0 (tương thích Light & Dark)."""
    spec = KMG_SOFT_ICONS.get(name) or KMG_SOFT_ICONS["sparkles"]
    size_key = size if size in _ICON_SIZES else "md"
    classes = f"kmg-icon kmg-icon-{size_key}"
    if css_class:
        classes = f"{classes} {escape(str(css_class).strip())}"
    if label:
        return format_html(
            '<svg class="{}" viewBox="0 0 24 24" role="img" aria-label="{}">{}</svg>',
            mark_safe(classes),
            escape(str(label)),
            mark_safe(spec.svg_inner),
        )
    return format_html(
        '<svg class="{}" viewBox="0 0 24 24" aria-hidden="true">{}</svg>',
        mark_safe(classes),
        mark_safe(spec.svg_inner),
    )


@register.simple_tag
def once_token():
    """Ô ẩn chứa mã dùng-một-lần, chống gửi trùng form (xem core/once.py)."""
    return format_html('<input type="hidden" name="{}" value="{}">',
                       once.FIELD, once.new_token())


# Ảnh bìa mặc định - TÊN PHẢI KHỚP FILE CÓ THẬT trong static/img/.
# Trước đây filter trả về số 1..4 và template ghép thành "cover-1.jpg"…
# nhưng trong static/img/ không hề có file nào tên như vậy, nên mọi sự kiện
# chưa upload ảnh đều hiện ảnh vỡ.
DEFAULT_COVERS = (
    "img/scene-sunset.jpg",
    "img/scene-dawn.jpg",
    "img/scene-2.jpg",
    "img/scene-3.jpg",
    "img/scene-4.jpg",
)


@register.filter
def default_cover(event):
    """
    Chọn ảnh bìa mặc định cho sự kiện chưa upload ảnh.

    Trả về ĐƯỜNG DẪN ĐẦY ĐỦ trong static (vd "img/scene-2.jpg") để template
    gọi thẳng {% static path %}. Không ghép chuỗi kiểu {% static 'img/' %} +
    tên file: khi deploy (ManifestStaticFilesStorage) 'img/' không có trong
    manifest nên sẽ ném ValueError làm sập trang.

    Chia lấy dư theo id để mỗi sự kiện có một ảnh cố định, không đổi mỗi
    lần tải trang. Ảnh nằm trong static/ nên không bị mất khi deploy lại.
    """
    return DEFAULT_COVERS[(event.pk or 0) % len(DEFAULT_COVERS)]


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


@register.filter
def khoang(value, now=None):
    """
    Khoảng cách từ bây giờ tới `value` (hoặc ngược lại) bằng tiếng Việt, gọn:
    "5 phút", "3 giờ", "2 ngày", "1 tuần 6 ngày".

    Filter timesince/timeuntil có sẵn của Django dịch tiếng Việt chưa trọn
    ("1 week, 6 days"), nên tự viết.
    """
    from django.utils import timezone
    if not value:
        return ""
    seconds = abs(int((value - (now or timezone.now())).total_seconds()))
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400
    if days >= 7:
        weeks, rest = divmod(days, 7)
        return f"{weeks} tuần" + (f" {rest} ngày" if rest else "")
    if days:
        rest = hours - days * 24
        return f"{days} ngày" + (f" {rest} giờ" if rest and days < 3 else "")
    if hours:
        return f"{hours} giờ"
    if minutes:
        return f"{minutes} phút"
    return "vài giây"
