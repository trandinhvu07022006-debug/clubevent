"""Tầng SERVICE cho tuyển thành viên: nộp đơn, rút đơn, duyệt đơn."""
from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Role, User
from notifications.models import NotificationKind
from notifications.services import notify_on_commit

from .models import Application, ApplicationStatus, RecruitmentRound


KMA_ONLY_REASON = ("Tuyển thành viên dành cho sinh viên Học viện Kỹ thuật Mật mã. "
                   "Nếu bạn là sinh viên Học viện, hãy cập nhật đối tượng và MSSV "
                   "trong Hồ sơ.")


class RecruitmentError(Exception):
    """Lỗi nghiệp vụ, view hiện thông điệp này cho người dùng."""


def reviewer_departments(user):
    """Ban mà user duyệt được đơn: Ban chủ nhiệm -> None (= tất cả)."""
    from organizing.models import Department
    if user.is_lead:
        return None
    return Department.objects.filter(lead=user)


def can_review(user) -> bool:
    if not user.is_authenticated:
        return False
    depts = reviewer_departments(user)
    return depts is None or depts.exists()


def applications_for_reviewer(user):
    qs = Application.objects.select_related("user", "department", "round", "reviewer")
    depts = reviewer_departments(user)
    if depts is not None:
        qs = qs.filter(department__in=depts)
    return qs


def eligibility(user, rnd: RecruitmentRound | None) -> str:
    """Trả về "" nếu được nộp đơn, ngược lại là lý do không được."""
    if rnd is None or not rnd.is_open:
        return "Hiện CLB chưa mở đợt tuyển thành viên."
    if not user.is_authenticated:
        return "Bạn cần tạo tài khoản và đăng nhập để nộp đơn."
    if user.is_club_member:
        return "Bạn đã là thành viên CLB rồi."
    if settings.RECRUIT_KMA_ONLY and not (user.is_kma_student and user.mssv):
        return KMA_ONLY_REASON
    if Application.objects.filter(round=rnd, user=user).exists():
        return "Bạn đã nộp đơn trong đợt này."
    return ""


@transaction.atomic
def submit_application(user, rnd: RecruitmentRound, app: Application) -> Application:
    reason = eligibility(user, rnd)
    if reason:
        raise RecruitmentError(reason)
    if app.department_id and not rnd.open_departments().filter(pk=app.department_id).exists():
        raise RecruitmentError("Ban này không nhận đơn trong đợt tuyển hiện tại.")
    app.round, app.user = rnd, user
    try:
        with transaction.atomic():
            app.save()
    except IntegrityError:
        raise RecruitmentError("Bạn đã nộp đơn trong đợt này.")
    AuditLog.write(user, "Nộp đơn ứng tuyển", rnd.name,
                   app.department.name if app.department_id else "")
    return app


@transaction.atomic
def withdraw_application(user, app: Application):
    app = Application.objects.select_for_update().get(pk=app.pk)
    if app.user_id != user.pk or not app.is_active:
        raise RecruitmentError("Không rút được đơn này.")
    app.status = ApplicationStatus.WITHDRAWN
    app.save(update_fields=["status"])


@transaction.atomic
def review_application(actor, app: Application, new_status: str,
                       note: str = "", interview_at=None) -> Application:
    """
    Duyệt đơn. Khoá dòng để 2 người duyệt cùng lúc không đè nhau.

    ĐÃ NHẬN: Khách -> Thành viên (không hạ vai trò của ai đang cao hơn) và
    được thêm vào Ban đã chọn. Mọi bước đều báo cho ứng viên (thông báo + email).
    """
    app = (Application.objects.select_for_update()
           .select_related("user", "department", "round").get(pk=app.pk))
    if not app.can_be_reviewed_by(actor):
        raise RecruitmentError("Bạn không có quyền duyệt đơn này.")
    if new_status not in [s for s, _ in app.next_statuses()]:
        raise RecruitmentError("Không chuyển được sang trạng thái này.")
    if new_status == ApplicationStatus.INTERVIEW and not interview_at:
        raise RecruitmentError("Hãy chọn lịch casting / phỏng vấn.")

    app.status = new_status
    app.review_note = (note or "")[:255]
    if interview_at:
        app.interview_at = interview_at
    app.reviewer = actor
    app.reviewed_at = timezone.now()
    app.save()

    user = app.user
    dept_name = app.department.name if app.department_id else "CLB"
    if new_status == ApplicationStatus.ACCEPTED:
        if user.role == Role.GUEST:
            User.objects.filter(pk=user.pk).update(role=Role.MEMBER)
        if app.department_id:
            app.department.members.add(user)
        title = f"Chúc mừng! Bạn đã là thành viên {dept_name}"
        message = (f"Đơn ứng tuyển đợt \"{app.round.name}\" đã được nhận. "
                   f"Chào mừng bạn đến với {dept_name}!")
    elif new_status == ApplicationStatus.INTERVIEW:
        when = timezone.localtime(app.interview_at).strftime("%H:%M %d/%m/%Y")
        title = f"Lịch casting / phỏng vấn {dept_name}"
        message = f"Bạn có lịch casting / phỏng vấn lúc {when}."
    else:
        title = "Kết quả ứng tuyển"
        message = (f"Cảm ơn bạn đã ứng tuyển {dept_name}. Đợt này bạn chưa phù hợp, "
                   f"hẹn gặp lại ở đợt tuyển sau nhé!")
    if app.review_note:
        message = f"{message} Lời nhắn: {app.review_note}"

    AuditLog.write(actor, f"Duyệt đơn: {app.get_status_display()}",
                   user.full_name or user.username, dept_name)
    url = reverse("recruitment:my_application")
    details = [("Đợt tuyển", app.round.name), ("Ban", dept_name),
               ("Trạng thái", app.get_status_display())]
    if new_status == ApplicationStatus.INTERVIEW:
        details.append(("Lịch", timezone.localtime(app.interview_at)
                        .strftime("%H:%M %d/%m/%Y")))
    notify_on_commit(user, NotificationKind.APPLICATION, title, message, url=url,
                     email_template="notice",
                     context={"title": title, "message": message, "details": details,
                              "note": app.review_note,
                              "cta_url": url, "cta_label": "Xem đơn của tôi"})
    return app
