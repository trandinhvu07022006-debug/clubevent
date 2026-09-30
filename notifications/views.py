"""F7.3 - Chuông thông báo trong app."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.pagination import paginate

from .models import Notification


@login_required
def notification_list(request):
    """Danh sách thông báo của chính mình, phân trang 20, lọc chưa đọc."""
    qs = request.user.notifications.all()
    only_unread = request.GET.get("chua-doc") == "1"
    if only_unread:
        qs = qs.filter(is_read=False)
    page_obj, querystring = paginate(request, qs, per_page=20)
    return render(request, "notifications/list.html", {
        "items": page_obj, "page_obj": page_obj, "querystring": querystring,
        "only_unread": only_unread,
    })


@require_POST
@login_required
def notification_open(request, pk):
    """
    Đánh dấu đã đọc rồi chuyển tới trang liên quan.

    - Lấy theo (pk, user) để không ai mở được thông báo của người khác (IDOR).
    - url do code sinh ra nhưng vẫn kiểm tra chống open redirect.
    """
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    if n.url and url_has_allowed_host_and_scheme(
            n.url, allowed_hosts={request.get_host()},
            require_https=request.is_secure()):
        return redirect(n.url)
    return redirect("notifications:list")


@require_POST
@login_required
def notification_read_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("notifications:list")
