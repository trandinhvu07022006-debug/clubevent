"""
Trang công khai (giới thiệu CLB, điều hướng theo đối tượng) và trang Tổng quan
cá nhân hoá theo vai trò.

Điều hướng 2 tầng, học từ các sản phẩm lớn (Notion, Slack, Eventbrite, Luma):
  - KHÁCH vào "/" thấy trang giới thiệu, rồi chọn lối đi của mình:
    "Dành cho thành viên" (cá nhân) hay "Dành cho Ban tổ chức" (tổ chức).
  - ĐÃ ĐĂNG NHẬP vào "/" được đưa thẳng tới /tong-quan/ - nơi mỗi người thấy
    đúng việc của mình: Không gian cá nhân và (nếu là BTC) Không gian tổ chức.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from organizing.services import departments_with_stats
from recruitment.models import RecruitmentRound

from .club_content import ACHIEVEMENTS, CLUB_PROFILE, HIGHLIGHTS
from .models import ClubOfficer
from .services import club_numbers, org_space, personal_space, public_events


def _club_context():
    """Nội dung giới thiệu KMG dùng chung cho trang chủ và trang Giới thiệu."""
    return {
        "profile": CLUB_PROFILE,
        "highlights": HIGHLIGHTS,
        "achievements": ACHIEVEMENTS,
        "officers": list(ClubOfficer.objects.filter(is_current=True)
                          .select_related("department", "user")),
        "recruit_round": RecruitmentRound.current(),
    }


def home(request):
    """Trang chủ. Người đã đăng nhập đi thẳng vào Tổng quan (như Notion/Slack)."""
    if request.user.is_authenticated and "xem" not in request.GET:
        return redirect("pages:dashboard")
    return render(request, "pages/home.html", {
        **_club_context(),
        "events": public_events(3),
        "numbers": club_numbers(),
        "departments": departments_with_stats()[:6],
    })


def for_members(request):
    """Lối đi CÁ NHÂN: hành trình của một người tham gia sự kiện (Khách hay Thành viên)."""
    return render(request, "pages/for_members.html", {"events": public_events(3)})


def for_organizers(request):
    """Lối đi TỔ CHỨC: Ban chủ nhiệm / BTC / các Ban vận hành sự kiện ra sao."""
    return render(request, "pages/for_organizers.html", {
        "departments": departments_with_stats(),
    })


def about(request):
    return render(request, "pages/about.html", {
        **_club_context(),
        "numbers": club_numbers(),
        "departments": departments_with_stats(),
    })


@login_required
def dashboard(request):
    """
    Tổng quan cá nhân hoá. Hai "không gian" chuyển qua lại bằng ?space=:
      - me  : Cá nhân - vé, thanh toán, đánh giá, gợi ý sự kiện, bước bắt đầu.
      - org : Tổ chức - việc của tôi, Ban của tôi, sự kiện đang chạy, quản trị.
    BTC trở lên mặc định vào "org" (việc hằng ngày của họ), thành viên chỉ có "me".
    Thành viên tự gõ ?space=org vẫn chỉ thấy "me" - quyền kiểm ở server.
    """
    user = request.user
    space = request.GET.get("space")
    if not user.is_staff_btc or space not in ("me", "org"):
        space = "org" if user.is_staff_btc else "me"

    hour = timezone.localtime().hour
    greeting = ("Chào buổi sáng" if 4 <= hour < 11 else
                "Chào buổi trưa" if hour < 14 else
                "Chào buổi chiều" if hour < 18 else "Chào buổi tối")
    ctx = {"space": space, "greeting": greeting, "today": timezone.localdate()}
    if space == "org":
        ctx.update(org_space(user))
    else:
        ctx.update(personal_space(user))
    return render(request, "pages/dashboard.html", ctx)
