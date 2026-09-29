"""View cho M1 - Tài khoản & phân quyền."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from .forms import LoginForm, ProfileForm, RegisterForm, RoleForm
from .models import AuditLog, User
from .pagination import paginate
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
        return redirect("events:list")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Đăng ký thành công. Chào mừng bạn!")
        return redirect("events:list")
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
    return render(request, "accounts/profile.html", {"form": form})


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


@admin_required
def user_toggle_lock(request, pk):
    """F1.4 - Khoá hoặc mở khoá tài khoản."""
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
