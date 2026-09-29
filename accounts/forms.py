"""Form cho M1 - Tài khoản."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Role, User

# Class CSS Bootstrap gắn chung cho mọi input
CTRL = {"class": "form-control"}


class RegisterForm(UserCreationForm):
    """F1.1 - Đăng ký. MSSV và email không được trùng."""

    full_name = forms.CharField(label="Họ tên", max_length=120,
                                widget=forms.TextInput(attrs=CTRL))
    mssv = forms.CharField(label="MSSV", max_length=20,
                           widget=forms.TextInput(attrs=CTRL))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs=CTRL))

    class Meta:
        model = User
        fields = ("username", "full_name", "mssv", "email")
        widgets = {"username": forms.TextInput(attrs=CTRL)}
        labels = {"username": "Tên đăng nhập"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.update(CTRL)

    def clean_mssv(self):
        mssv = self.cleaned_data["mssv"].strip()
        if User.objects.filter(mssv=mssv).exists():
            raise forms.ValidationError("MSSV này đã được đăng ký.")
        return mssv

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email này đã được đăng ký.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = Role.MEMBER          # đăng ký xong là Thành viên
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """F1.2 - Đăng nhập. Chặn luôn tài khoản đã bị khoá."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(CTRL)
        self.fields["password"].widget.attrs.update(CTRL)

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_locked:
            raise forms.ValidationError("Tài khoản của bạn đã bị khoá. "
                                        "Liên hệ Admin để được mở.")


class ProfileForm(forms.ModelForm):
    """F1.3 - Cập nhật hồ sơ."""

    class Meta:
        model = User
        fields = ("full_name", "phone", "avatar")
        widgets = {
            "full_name": forms.TextInput(attrs=CTRL),
            "phone": forms.TextInput(attrs=CTRL),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }


class RoleForm(forms.ModelForm):
    """F1.4 - Admin gán role."""

    class Meta:
        model = User
        fields = ("role",)
        widgets = {"role": forms.Select(attrs={"class": "form-select"})}
