"""View cho M1 - Tài khoản & phân quyền."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView, PasswordResetView, PasswordResetDoneView, PasswordResetConfirmView, PasswordResetCompleteView
import time
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from core.pagination import paginate
from registrations.services import attended_events, user_stats

from .forms import LoginForm, ProfileForm, RegisterForm, RoleForm, AppPasswordResetForm
from .models import AuditLog, User
from .permissions import admin_required


class AppLoginView(LoginView):
    """F1.2 - Đăng nhập."""
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class AppLogoutView(LogoutView):
    pass


def register(request):
    """F1.1 - Đăng ký rồi đăng nhập luôn."""
    if request.user.is_authenticated:
        return redirect("pages:dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Đăng ký thành công. Chào mừng bạn đến với KMG Club!")
        return redirect("pages:dashboard")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile(request):
    """F1.3 - Cập nhật hồ sơ."""
    form = ProfileForm(request.POST or None, request.FILES or None,
                       instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã cập nhật hồ sơ.")
        return redirect("accounts:profile")
    # F8.1 - lịch sử tham gia (sự kiện đã check-in) + chứng nhận (F8.2)
    attended = list(attended_events(request.user))
    return render(request, "accounts/profile.html", {
        "form": form,
        "attended": attended,
        "stats": user_stats(request.user),
    })


class AppPasswordChangeView(PasswordChangeView):
    """
    F1.3 - Đổi mật khẩu.

    Dùng PasswordChangeView có sẵn của Django thay vì tự viết, vì nó đã xử lý
    đúng mấy việc dễ sai: bắt nhập mật khẩu cũ, chạy bộ kiểm tra độ mạnh, và
    quan trọng nhất là giữ phiên đăng nhập sau khi đổi (không có bước này thì
    user bị đăng xuất ngay khi vừa đổi xong).
    """
    template_name = "accounts/password_change.html"
    form_class = PasswordChangeForm
    success_url = reverse_lazy("accounts:profile")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs.update({"class": "form-control"})
        return form

    def form_valid(self, form):
        messages.success(self.request, "Đã đổi mật khẩu thành công.")
        AuditLog.write(self.request.user, "Đổi mật khẩu", self.request.user)
        return super().form_valid(form)


class AppPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    form_class = AppPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")

    def dispatch(self, request, *args, **kwargs):
        # Chặn spam: tối đa 5 yêu cầu/giờ mỗi session
        now = time.time()
        key = "pwd_reset_timestamps"
        timestamps = request.session.get(key, [])
        timestamps = [t for t in timestamps if now - t < 3600]
        if len(timestamps) >= 5:
            # Vượt ngưỡng vẫn hiện trang "đã gửi" (không lộ thông tin)
            return redirect(self.success_url)
        timestamps.append(now)
        request.session[key] = timestamps
        return super().dispatch(request, *args, **kwargs)


class AppPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        AuditLog.write(self.user, "Đặt lại mật khẩu", self.user.username)
        return response


@admin_required
def user_list(request):
    """F1.4 - Admin xem và tìm kiếm tài khoản."""
    keyword = request.GET.get("q", "").strip()
    users = User.objects.all().order_by("-created_at")
    if keyword:
        users = users.filter(Q(full_name__icontains=keyword)
                             | Q(mssv__icontains=keyword)
                             | Q(username__icontains=keyword))
    page_obj, querystring = paginate(request, users, per_page=20)
    return render(request, "accounts/user_list.html",
                  {"users": page_obj, "page_obj": page_obj,
                   "querystring": querystring, "keyword": keyword})


@admin_required
def user_set_role(request, pk):
    """F1.4 - Admin gán role. Ghi audit log vì đây là thao tác quan trọng."""
    target = get_object_or_404(User, pk=pk)
    # Tự hạ quyền của chính mình có thể làm hệ thống không còn Admin nào
    if target == request.user:
        messages.error(request, "Không thể tự đổi vai trò của chính mình.")
        return redirect("accounts:user_list")
    form = RoleForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        old_role = target.get_role_display()
        form.save()
        AuditLog.write(request.user, "Gán role", target,
                       f"{old_role} -> {target.get_role_display()}")
        messages.success(request, f"Đã đổi vai trò của {target.full_name}.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_role.html",
                  {"form": form, "target": target})


@require_POST
@admin_required
def user_toggle_lock(request, pk):
    """
    F1.4 - Khoá hoặc mở khoá tài khoản.

    Bắt buộc POST để chống CSRF via GET: nếu chỉ nhận GET thì attacker gửi
    link cho admin click vào là khoá/mở khoá tài khoản mà admin không biết.
    """
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "Không thể tự khoá tài khoản của mình.")
        return redirect("accounts:user_list")
    target.is_locked = not target.is_locked
    target.save(update_fields=["is_locked"])
    AuditLog.write(request.user,
                   "Khoá tài khoản" if target.is_locked else "Mở khoá tài khoản",
                   target)
    messages.success(request, "Đã cập nhật trạng thái tài khoản.")
    return redirect("accounts:user_list")


@admin_required
def audit_log(request):
    """F0.2 - Xem nhật ký thao tác, 200 dòng gần nhất."""
    return render(request, "accounts/audit_log.html",
                  {"logs": AuditLog.objects.select_related("user")[:200]})
