"""Form Liên hệ trên Trang chủ KMG có Honeypot chống bot."""
from django import forms

from .models import ContactSubmission

CTRL = {"class": "form-control"}


class PublicContactForm(forms.ModelForm):
    # Trường bẫy bot tự động (ẩn với người thật)
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ContactSubmission
        fields = ("full_name", "email", "phone", "topic", "message")
        widgets = {
            "full_name": forms.TextInput(
                attrs={**CTRL, "placeholder": "Nguyễn Văn A"}
            ),
            "email": forms.EmailInput(
                attrs={**CTRL, "placeholder": "ban@sinhvien.edu.vn"}
            ),
            "phone": forms.TextInput(
                attrs={**CTRL, "placeholder": "09xx xxx xxx (không bắt buộc)"}
            ),
            "topic": forms.Select(attrs={"class": "form-select"}),
            "message": forms.Textarea(
                attrs={
                    **CTRL,
                    "rows": 4,
                    "placeholder": "Lời nhắn, câu hỏi về đợt tuyển thành viên hoặc đề xuất hợp tác biểu diễn...",
                }
            ),
        }

    def clean_website(self):
        val = (self.cleaned_data.get("website") or "").strip()
        if val:
            raise forms.ValidationError("Phát hiện yêu cầu tự động không hợp lệ.")
        return val
