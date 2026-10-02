"""
Tuyển thành viên theo đợt.

Luồng: Khách xem trang Tuyển thành viên -> nộp đơn (chọn Ban) -> Ban chủ
nhiệm / Trưởng ban duyệt: hẹn casting, nhận hoặc chưa nhận -> nhận thì
tài khoản lên Thành viên và vào Ban. Ứng viên theo dõi ở "Đơn của tôi".
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.permissions import lead_required, staff_required
from core import once
from core.pagination import paginate
from organizing.models import Department
from pages.club_content import CLUB_PROFILE, HIGHLIGHTS

from .forms import ApplicationForm, ReviewForm, RoundForm
from .models import Application, ApplicationStatus, RecruitmentRound
from .services import (KMA_ONLY_REASON, RecruitmentError, applications_for_reviewer, can_review,
                       eligibility, review_application, submit_application,
                       withdraw_application)


def recruit_home(request):
    """Trang công khai: đợt tuyển đang mở, các Ban, quy trình, nút nộp đơn."""
    rnd = RecruitmentRound.current()
    my_app = None
    if request.user.is_authenticated and rnd:
        my_app = Application.objects.filter(round=rnd, user=request.user).first()
    return render(request, "recruitment/home.html", {
        "round": rnd,
        "upcoming": None if rnd else RecruitmentRound.next_upcoming(),
        "departments": rnd.open_departments() if rnd else None,
        "reason": eligibility(request.user, rnd),
        "kma_only_reason": KMA_ONLY_REASON,
        "my_app": my_app,
        "profile": CLUB_PROFILE,
        "profile_highlights": HIGHLIGHTS,
        "all_departments": Department.objects.all(),
    })


@login_required
def apply(request):
    rnd = RecruitmentRound.current()
    reason = eligibility(request.user, rnd)
    if reason:
        messages.info(request, reason)
        return redirect("recruitment:home")
    form = ApplicationForm(request.POST or None, rnd=rnd)
    if request.method == "POST" and not once.consume(request):
        messages.info(request, "Yêu cầu này đã được gửi rồi - bỏ qua lần bấm trùng.")
        return redirect("recruitment:my_application")
    if request.method == "POST" and form.is_valid():
        try:
            submit_application(request.user, rnd, form.save(commit=False))
        except RecruitmentError as e:
            messages.error(request, str(e))
            return redirect("recruitment:home")
        messages.success(request, "Đã nộp đơn! Bạn sẽ nhận thông báo và email khi có kết quả.")
        return redirect("recruitment:my_application")
    return render(request, "recruitment/apply.html", {"form": form, "round": rnd})


@login_required
def my_application(request):
    apps = (Application.objects.filter(user=request.user)
            .select_related("round", "department", "reviewer"))
    return render(request, "recruitment/my_application.html", {
        "apps": apps, "round": RecruitmentRound.current()})


@require_POST
@login_required
def withdraw(request, pk):
    app = get_object_or_404(Application, pk=pk, user=request.user)
    try:
        withdraw_application(request.user, app)
        messages.success(request, "Đã rút đơn.")
    except RecruitmentError as e:
        messages.error(request, str(e))
    return redirect("recruitment:my_application")


# ---------------------------------------------------------------------------
# DUYỆT ĐƠN - Ban chủ nhiệm (mọi Ban) và Trưởng ban (Ban mình)
# ---------------------------------------------------------------------------
def _reviewer_or_403(user):
    if not can_review(user):
        raise PermissionDenied("Chỉ Ban chủ nhiệm hoặc Trưởng ban được duyệt đơn.")


@staff_required
def review_list(request):
    _reviewer_or_403(request.user)
    rounds = RecruitmentRound.objects.all()
    rnd_id = request.GET.get("dot", "")
    rnd = (rounds.filter(pk=rnd_id).first() if rnd_id.isdigit() else None) \
        or RecruitmentRound.current() or rounds.first()
    status = request.GET.get("status", "")

    base = applications_for_reviewer(request.user)
    if rnd:
        base = base.filter(round=rnd)
    counts = base.aggregate(
        all=Count("id"),
        **{s.lower(): Count("id", filter=Q(status=s)) for s in ApplicationStatus.values})
    qs = base.filter(status=status) if status in ApplicationStatus.values else base
    if status not in ApplicationStatus.values:
        status = ""
    page_obj, querystring = paginate(request, qs.order_by("status", "-created_at"), per_page=20)
    return render(request, "recruitment/review_list.html", {
        "apps": page_obj, "page_obj": page_obj, "querystring": querystring,
        "rounds": rounds, "round": rnd, "counts": counts, "current_status": status,
        "statuses": ApplicationStatus.choices,
    })


@staff_required
def review_detail(request, pk):
    _reviewer_or_403(request.user)
    app = get_object_or_404(applications_for_reviewer(request.user), pk=pk)
    form = ReviewForm(request.POST or None, app=app) if app.next_statuses() else None
    if request.method == "POST" and form and form.is_valid():
        try:
            review_application(request.user, app, form.cleaned_data["status"],
                               note=form.cleaned_data["note"],
                               interview_at=form.cleaned_data["interview_at"])
        except RecruitmentError as e:
            messages.error(request, str(e))
        else:
            app.refresh_from_db()
            messages.success(request, f"Đã cập nhật: {app.get_status_display()}. "
                                      f"Ứng viên đã được thông báo.")
            return redirect("recruitment:review_list")
    others = (Application.objects.filter(user=app.user).exclude(pk=app.pk)
              .select_related("round", "department"))
    return render(request, "recruitment/review_detail.html",
                  {"app": app, "form": form, "others": others})


@lead_required
def round_form(request, pk=None):
    rnd = get_object_or_404(RecruitmentRound, pk=pk) if pk else None
    form = RoundForm(request.POST or None, instance=rnd)
    if request.method == "POST" and not once.consume(request):
        messages.info(request, "Yêu cầu này đã được gửi rồi - bỏ qua lần bấm trùng.")
        return redirect("recruitment:review_list")
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.created_by_id:
            obj.created_by = request.user
        obj.save()
        form.save_m2m()
        cache.delete("recruit_open")      # menu "Đang mở" cập nhật ngay
        messages.success(request, f"Đã lưu đợt tuyển '{obj.name}'.")
        return redirect(reverse("recruitment:review_list") + f"?dot={obj.pk}")
    return render(request, "recruitment/round_form.html", {"form": form, "round": rnd})
