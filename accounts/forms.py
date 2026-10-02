"""Form cho M1 - Tài khoản."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, PasswordResetForm

from core.images import shrink_image

from .models import Affiliation, Role, User, canonical_email

# Class CSS Bootstrap gắn chung cho mọi input
CTRL = {"class": "form-control"}

AVATAR_MAX_BYTES = 2 * 1024 * 1024


class AffiliationMixin:
    """
    Quy tắc chung cho form đăng ký và hồ sơ:
      - Sinh viên Học viện: BẮT BUỘC MSSV (để BTC đối chiếu, để ứng tuyển).
      - Sinh viên trường khác / không phải sinh viên: MSSV bỏ trống được,
        "Trường / đơn vị" không bắt buộc. Họ vẫn đặt vé xem show bình thường.
    MSSV để trống lưu NULL (không phải ""), vì cột unique chỉ cho 1 chuỗi rỗng.
    """

    def clean_mssv(self):
        # Chuẩn hoá chữ hoa: "at190001" và "AT190001" là cùng một sinh viên
        mssv = (self.cleaned_data.get("mssv") or "").strip().upper()
        if not mssv:
            return None
        taken = User.objects.filter(mssv__iexact=mssv)
        if self.instance.pk:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError("MSSV này đã được đăng ký.")
        return mssv

    def clean(self):
        data = super().clean()
        if data.get("affiliation") == Affiliation.KMA:
            if not data.get("mssv") and "mssv" not in self.errors:
                self.add_error("mssv", "Sinh viên Học viện vui lòng nhập MSSV.")
        else:
            # Người ngoài Học viện: không lưu MSSV (tránh chiếm MSSV của
            # sinh viên Học viện nếu trùng định dạng).
            data["mssv"] = None
        data["school"] = (data.get("school") or "").strip()
        return data


class RegisterForm(AffiliationMixin, UserCreationForm):
    """F1.1 - Đăng ký. Email không được trùng; MSSV chỉ bắt buộc với sinh viên Học viện."""

    affiliation = forms.ChoiceField(label="Bạn là", choices=Affiliation.choices,
                                    initial=Affiliation.KMA, widget=forms.RadioSelect)
    full_name = forms.CharField(label="Họ tên", max_length=120,
                                widget=forms.TextInput(attrs=CTRL))
    mssv = forms.CharField(label="MSSV", max_length=20, required=False,
                           help_text="Bắt buộc với sinh viên Học viện.",
                           widget=forms.TextInput(attrs={**CTRL, "autocomplete": "off"}))
    school = forms.CharField(label="Trường / đơn vị", max_length=120, required=False,
                             help_text="Không bắt buộc.",
                             widget=forms.TextInput(attrs={**CTRL, "placeholder": "Vd: Đại học Bách khoa Hà Nội"}))
    email = forms.EmailField(label="Email", help_text="Vé và nhắc lịch được gửi qua email này.",
                             widget=forms.EmailInput(attrs={**CTRL, "autocomplete": "email"}))
    phone = forms.CharField(label="Số điện thoại", max_length=20, required=False,
                            help_text="Không bắt buộc. BTC liên hệ khi cần.",
                            widget=forms.TextInput(attrs={**CTRL, "type": "tel", "autocomplete": "tel"}))

    class Meta:
        model = User
        fields = ("affiliation", "full_name", "username", "email", "mssv", "school", "phone")
        widgets = {"username": forms.TextInput(attrs=CTRL)}
        labels = {"username": "Tên đăng nhập"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.update(CTRL)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email này đã được đăng ký.")
        # F1.8 - "abc+1@gmail.com", "a.bc@gmail.com"... cùng hộp thư với "abc@gmail.com"
        if User.objects.filter(email_canonical=canonical_email(email)).exists():
            raise forms.ValidationError(
                "Hộp thư này đã có tài khoản (cùng địa chỉ, chỉ khác dấu chấm "
                "hoặc phần sau dấu +). Hãy đăng nhập bằng tài khoản đó.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        # Tự đăng ký online chỉ là KHÁCH (đặt vé được). Lên Thành viên phải
        # qua đợt tuyển - xem app recruitment.
        user.role = Role.GUEST
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


class ProfileForm(AffiliationMixin, forms.ModelForm):
    """F1.3 - Cập nhật hồ sơ. Đổi đối tượng / bổ sung MSSV về sau cũng được."""

    class Meta:
        model = User
        fields = ("full_name", "affiliation", "mssv", "school", "phone", "avatar")
        help_texts = {"mssv": "Bắt buộc với sinh viên Học viện.",
                      "school": "Không bắt buộc.", "phone": "Không bắt buộc."}
        widgets = {
            "full_name": forms.TextInput(attrs=CTRL),
            "affiliation": forms.Select(attrs={"class": "form-select"}),
            "mssv": forms.TextInput(attrs=CTRL),
            "school": forms.TextInput(attrs=CTRL),
            "phone": forms.TextInput(attrs={**CTRL, "type": "tel"}),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control",
                                                      "accept": "image/*"}),
        }

    def clean_avatar(self):
        """Giới hạn ảnh đại diện 2 MB - host miễn phí có dung lượng rất hạn chế."""
        avatar = self.cleaned_data.get("avatar")
        if avatar and getattr(avatar, "size", 0) > AVATAR_MAX_BYTES:
            raise forms.ValidationError("Ảnh đại diện tối đa 2 MB.")
        return shrink_image(avatar, 400)


class RoleForm(forms.ModelForm):
    """F1.4 - Admin gán role."""

    class Meta:
        model = User
        fields = ("role",)
        widgets = {"role": forms.Select(attrs={"class": "form-select"})}


class AppPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        # Không gửi link cho tài khoản bị khoá: có đặt lại được mật khẩu thì
        # vẫn không đăng nhập được (confirm_login_allowed chặn), chỉ gây rối.
        return (u for u in super().get_users(email) if not u.is_locked)

