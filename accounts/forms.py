"""Form cho M1 - Đăng ký Email/SĐT + OTP, Đăng nhập Đa định danh, Hồ sơ & Quyền riêng tư."""
from __future__ import annotations

import re
import secrets

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    UserCreationForm,
)
from django.contrib.auth.validators import UnicodeUsernameValidator

from core.images import shrink_image

from .models import (
    AccountStatus,
    Affiliation,
    OtpChannel,
    Role,
    User,
    UserProfile,
    canonical_email,
    is_valid_phone_number,
    normalize_phone_number,
)
from .services import find_user_by_login_identifier

CTRL = {"class": "form-control"}
SEL = {"class": "form-select"}
CHK = {"class": "form-check-input"}

AVATAR_MAX_BYTES = 2 * 1024 * 1024
_USERNAME_VALIDATOR = UnicodeUsernameValidator()


def _generate_unique_username(email: str = "", phone: str = "") -> str:
    """Tự động sinh username sạch và không trùng khi người dùng chỉ nhập Email hoặc SĐT."""
    base = ""
    if email and "@" in email:
        base = re.sub(r"[^a-z0-9_]", "", email.split("@", 1)[0].lower())[:20]
    if len(base) < 3 and phone:
        norm = normalize_phone_number(phone) or ""
        digits = "".join(ch for ch in norm if ch.isdigit())
        if len(digits) >= 6:
            base = f"kmg_{digits[-6:]}"
    if len(base) < 3:
        base = "kmg_member"

    candidate = base
    for _ in range(25):
        if not User.objects.filter(username__iexact=candidate).exists():
            return candidate
        candidate = f"{base}_{secrets.randbelow(9000) + 1000}"
    return f"{base}_{secrets.token_hex(3)}"


class AffiliationMixin:
    """
    Quy tắc chung cho form đăng ký và hồ sơ:
      - Sinh viên Học viện: BẮT BUỘC MSSV (để BTC đối chiếu, để ứng tuyển).
      - Sinh viên trường khác / không phải sinh viên: MSSV bỏ trống được,
        "Trường / đơn vị" không bắt buộc. Họ vẫn đặt vé xem show bình thường.
    MSSV để trống lưu NULL (không phải ""), vì cột unique chỉ cho 1 chuỗi rỗng.
    """

    def clean_mssv(self):
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
            data["mssv"] = None
        data["school"] = (data.get("school") or "").strip()
        return data


class RegisterForm(AffiliationMixin, UserCreationForm):
    """
    F1.1 - Đăng ký tài khoản qua Email HOẶC Số điện thoại (SĐT):
    - Bắt buộc có ít nhất 1 trong 2: `email` hoặc `phone`.
    - `username` và `mssv` là tuỳ chọn (nếu để trống `username` hệ thống tự tạo; nếu nhập `mssv` vẫn kiểm tra chống trùng).
    - Sau khi đăng ký xong (kể cả sau khi xác minh OTP), tài khoản mặc định là Khách (`GUEST`).
    """

    OTP_CHANNEL_CHOICES = (
        ("AUTO", "Tự động theo Email / SĐT đã nhập"),
        (OtpChannel.EMAIL, "Nhận mã OTP qua Email"),
        (OtpChannel.SMS, "Nhận mã OTP qua Tin nhắn SMS (SĐT)"),
    )

    affiliation = forms.ChoiceField(
        label="Bạn là",
        choices=Affiliation.choices,
        initial=Affiliation.KMA,
        widget=forms.RadioSelect,
    )
    full_name = forms.CharField(
        label="Họ và tên",
        max_length=120,
        widget=forms.TextInput(attrs={**CTRL, "placeholder": "Ví dụ: Nguyễn Minh Khôi"}),
    )
    email = forms.EmailField(
        label="Email",
        required=False,
        widget=forms.EmailInput(
            attrs={**CTRL, "placeholder": "tenban@example.com (hoặc dùng SĐT bên dưới)"}
        ),
    )
    phone = forms.CharField(
        label="Số điện thoại (SĐT)",
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={**CTRL, "placeholder": "0901234567 hoặc +84901234567 (hoặc dùng Email)"}
        ),
    )
    otp_channel = forms.ChoiceField(
        label="Phương thức xác minh OTP",
        choices=OTP_CHANNEL_CHOICES,
        required=False,
        initial="AUTO",
        widget=forms.Select(attrs=SEL),
    )
    username = forms.CharField(
        label="Tên đăng nhập (tuỳ chọn)",
        max_length=150,
        required=False,
        validators=[_USERNAME_VALIDATOR],
        help_text="Có thể bỏ trống — bạn vẫn đăng nhập trực tiếp được bằng Email hoặc Số điện thoại.",
        widget=forms.TextInput(
            attrs={**CTRL, "placeholder": "Bỏ trống hệ thống sẽ tự tạo"}
        ),
    )
    mssv = forms.CharField(
        label="MSSV (tuỳ chọn)",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={**CTRL, "placeholder": "Nhập MSSV nếu có"}),
    )
    school = forms.CharField(
        label="Trường / đơn vị",
        max_length=120,
        required=False,
        help_text="Không bắt buộc.",
        widget=forms.TextInput(attrs={**CTRL, "placeholder": "Vd: Đại học Bách khoa Hà Nội"}),
    )

    class Meta:
        model = User
        fields = ("affiliation", "full_name", "email", "phone", "otp_channel", "username", "mssv", "school")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs.update(CTRL)

    def clean_username(self):
        raw = (self.cleaned_data.get("username") or "").strip()
        if not raw:
            return ""
        if User.objects.filter(username__iexact=raw).exists():
            raise forms.ValidationError("Tên đăng nhập này đã tồn tại.")
        return raw

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return ""
        if (
            User.objects.filter(normalized_email=email).exists()
            or User.objects.filter(email__iexact=email).exists()
        ):
            raise forms.ValidationError("Email này đã được đăng ký.")
        canon = canonical_email(email)
        if User.objects.filter(email_canonical=canon).exists():
            raise forms.ValidationError(
                "Hộp thư này đã có tài khoản (cùng địa chỉ, chỉ khác dấu chấm hoặc phần sau dấu +). Hãy đăng nhập bằng tài khoản đó."
            )
        return email

    def clean_phone(self):
        raw_phone = (self.cleaned_data.get("phone") or "").strip()
        if not raw_phone:
            return ""
        if not is_valid_phone_number(raw_phone):
            raise forms.ValidationError(
                "Số điện thoại không hợp lệ (ví dụ hợp lệ: 0901234567 hoặc +84901234567)."
            )
        norm = normalize_phone_number(raw_phone)
        if norm and User.objects.filter(normalized_phone=norm).exists():
            raise forms.ValidationError("Số điện thoại này đã được đăng ký.")
        return norm or raw_phone

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email") or ""
        phone = cleaned.get("phone") or ""
        channel_pref = (cleaned.get("otp_channel") or "AUTO").upper()

        # Chỉ báo lỗi thiếu cả Email & SĐT nếu không phải do bản thân trường email/phone đang sai định dạng
        if not email and not phone and "email" not in self.errors and "phone" not in self.errors:
            raise forms.ValidationError(
                "Vui lòng nhập ít nhất Email hoặc Số điện thoại (SĐT) để đăng ký và nhận mã xác minh OTP."
            )

        if channel_pref == OtpChannel.EMAIL and not email and "email" not in self.errors:
            self.add_error(
                "otp_channel",
                "Bạn chọn nhận OTP qua Email nhưng chưa nhập địa chỉ Email.",
            )
        elif channel_pref == OtpChannel.SMS and not phone and "phone" not in self.errors:
            self.add_error(
                "otp_channel",
                "Bạn chọn nhận OTP qua SMS nhưng chưa nhập Số điện thoại.",
            )

        if channel_pref == OtpChannel.SMS and phone:
            cleaned["resolved_otp_channel"] = OtpChannel.SMS
        elif channel_pref == OtpChannel.EMAIL and email:
            cleaned["resolved_otp_channel"] = OtpChannel.EMAIL
        elif email:
            cleaned["resolved_otp_channel"] = OtpChannel.EMAIL
        else:
            cleaned["resolved_otp_channel"] = OtpChannel.SMS

        if not cleaned.get("username"):
            generated = _generate_unique_username(email=email, phone=phone)
            cleaned["username"] = generated
            self.instance.username = generated

        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["username"]
        user.full_name = self.cleaned_data["full_name"].strip()
        user.display_name = user.full_name
        user.affiliation = self.cleaned_data.get("affiliation") or Affiliation.KMA
        user.mssv = self.cleaned_data.get("mssv") or None
        user.school = self.cleaned_data.get("school") or ""
        user.email = self.cleaned_data.get("email") or ""
        user.phone = self.cleaned_data.get("phone") or ""
        # Tự đăng ký online chỉ là KHÁCH (đặt vé được). Lên Thành viên phải qua đợt tuyển
        user.role = Role.GUEST
        user.account_status = AccountStatus.UNVERIFIED
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """F1.2 - Đăng nhập bằng Email, Số điện thoại (SĐT) hoặc Tên đăng nhập. Chặn tài khoản bị khoá."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Email / Số điện thoại / Tên đăng nhập hoặc mật khẩu không chính xác.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email, Số điện thoại hoặc Tên đăng nhập"
        self.fields["username"].widget.attrs.update(
            {**CTRL, "placeholder": "Nhập Email, SĐT hoặc Tên đăng nhập"}
        )
        self.fields["password"].widget.attrs.update(CTRL)

    def clean(self):
        identifier = (self.cleaned_data.get("username") or "").strip()
        if identifier:
            matched_user = find_user_by_login_identifier(identifier)
            if matched_user is not None:
                self.cleaned_data["username"] = matched_user.username
        return super().clean()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_locked or user.account_status == AccountStatus.LOCKED:
            raise forms.ValidationError(
                "Tài khoản của bạn đã bị khoá. Liên hệ Admin để được mở."
            )


class OTPVerifyForm(forms.Form):
    """Form nhập mã OTP 6 chữ số xác minh qua SMS hoặc Email."""

    code = forms.CharField(
        label="Mã xác minh OTP (6 chữ số)",
        max_length=12,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg text-center fw-bold",
                "style": "letter-spacing: 0.35em; font-size: 1.35rem;",
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "placeholder": "000000",
                "autofocus": "autofocus",
            }
        ),
    )
    channel = forms.ChoiceField(
        choices=OtpChannel.choices,
        required=False,
        widget=forms.HiddenInput(),
    )

    def clean_code(self):
        raw = self.cleaned_data.get("code") or ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) != 6:
            raise forms.ValidationError("Vui lòng nhập đúng mã OTP gồm 6 chữ số.")
        return digits


class ProfileForm(AffiliationMixin, forms.ModelForm):
    """F1.3 - Cập nhật hồ sơ. Đổi đối tượng / bổ sung MSSV về sau cũng được."""

    class Meta:
        model = User
        fields = ("full_name", "display_name", "affiliation", "mssv", "school", "phone", "avatar")
        help_texts = {
            "mssv": "Bắt buộc với sinh viên Học viện.",
            "school": "Không bắt buộc.",
            "phone": "Không bắt buộc.",
        }
        widgets = {
            "full_name": forms.TextInput(attrs=CTRL),
            "display_name": forms.TextInput(attrs=CTRL),
            "affiliation": forms.Select(attrs={"class": "form-select"}),
            "mssv": forms.TextInput(attrs=CTRL),
            "school": forms.TextInput(attrs=CTRL),
            "phone": forms.TextInput(attrs={**CTRL, "type": "tel"}),
            "avatar": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
        }

    def clean_phone(self):
        raw_phone = (self.cleaned_data.get("phone") or "").strip()
        if not raw_phone:
            return ""
        if not is_valid_phone_number(raw_phone):
            raise forms.ValidationError(
                "Số điện thoại không hợp lệ (ví dụ: 0901234567 hoặc +84901234567)."
            )
        norm = normalize_phone_number(raw_phone)
        qs = User.objects.filter(normalized_phone=norm)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if norm and qs.exists():
            raise forms.ValidationError("Số điện thoại này đã thuộc về một tài khoản khác.")
        return raw_phone

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and getattr(avatar, "size", 0) > AVATAR_MAX_BYTES:
            raise forms.ValidationError("Ảnh đại diện tối đa 2 MB.")
        return shrink_image(avatar, 400)

    def save(self, commit=True):
        old_norm_phone = (
            User.objects.filter(pk=self.instance.pk)
            .values_list("normalized_phone", flat=True)
            .first()
            if self.instance and self.instance.pk
            else None
        )
        user = super().save(commit=False)
        new_norm_phone = normalize_phone_number(user.phone)
        if old_norm_phone != new_norm_phone:
            user.phone_verified_at = None
        if commit:
            user.save()
        return user


class ExtendedProfileForm(forms.ModelForm):
    """Hồ sơ nghệ thuật & kiểm soát quyền riêng tư PII trong CLB."""

    class Meta:
        model = UserProfile
        fields = (
            "stage_name",
            "faculty",
            "cohort",
            "date_of_birth",
            "social_url",
            "bio",
            "privacy_show_email",
            "privacy_show_phone",
            "privacy_show_dob",
        )
        widgets = {
            "stage_name": forms.TextInput(attrs=CTRL),
            "faculty": forms.TextInput(attrs=CTRL),
            "cohort": forms.TextInput(attrs=CTRL),
            "date_of_birth": forms.DateInput(
                attrs={**CTRL, "type": "date"}, format="%Y-%m-%d"
            ),
            "social_url": forms.URLInput(attrs=CTRL),
            "bio": forms.Textarea(attrs={**CTRL, "rows": 3}),
            "privacy_show_email": forms.CheckboxInput(attrs=CHK),
            "privacy_show_phone": forms.CheckboxInput(attrs=CHK),
            "privacy_show_dob": forms.CheckboxInput(attrs=CHK),
        }


class RoleForm(forms.ModelForm):
    """F1.4 - Admin gán role BTC sự kiện / quyền Admin Server."""

    class Meta:
        model = User
        fields = ("role",)
        widgets = {"role": forms.Select(attrs={"class": "form-select"})}


class AppPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        return (
            u
            for u in super().get_users(email)
            if not u.is_locked and u.account_status != AccountStatus.LOCKED
        )
