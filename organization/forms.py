"""Form nghiệp vụ cho Phân hệ Tổ chức, Ứng tuyển & Hồ sơ Kỹ năng."""
from django import forms

from .models import (
    Department,
    MembershipApplication,
    Skill,
    SkillProficiency,
)

CTRL = {"class": "form-control"}
SEL = {"class": "form-select"}


class MembershipApplicationForm(forms.ModelForm):
    """Form Guest nộp đơn xin gia nhập CLB KMG (`WF01`)."""

    class Meta:
        model = MembershipApplication
        fields = (
            "primary_department",
            "secondary_department",
            "declared_skills_text",
            "portfolio_url",
            "motivation",
        )
        widgets = {
            "primary_department": forms.Select(attrs=SEL),
            "secondary_department": forms.Select(attrs=SEL),
            "declared_skills_text": forms.TextInput(
                attrs={
                    **CTRL,
                    "placeholder": "VD: Guitar Acoustic 2 năm, hát bè, thiết kế Canva/Photoshop...",
                }
            ),
            "portfolio_url": forms.URLInput(
                attrs={**CTRL, "placeholder": "https://..."}
            ),
            "motivation": forms.Textarea(
                attrs={
                    **CTRL,
                    "rows": 4,
                    "placeholder": "Chia sẻ niềm yêu thích âm nhạc và mong muốn đóng góp của bạn tại KMG...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_depts = Department.objects.filter(is_active=True)
        self.fields["primary_department"].queryset = active_depts
        self.fields["secondary_department"].queryset = active_depts
        self.fields["secondary_department"].required = False


class UserSkillDeclareForm(forms.Form):
    """Form thành viên tự khai báo kỹ năng cá nhân."""

    skill = forms.ModelChoiceField(
        label="Kỹ năng",
        queryset=Skill.objects.filter(is_active=True).select_related("category"),
        widget=forms.Select(attrs=SEL),
    )
    proficiency = forms.ChoiceField(
        label="Mức độ thành thạo",
        choices=SkillProficiency.choices,
        widget=forms.Select(attrs=SEL),
    )
    experience_note = forms.CharField(
        label="Kinh nghiệm / Nhạc cụ",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={**CTRL, "placeholder": "VD: Đệm hát Acoustic, sở hữu đàn Yamaha F310"}
        ),
    )
    evidence_url = forms.URLField(
        label="Link Video / Audio minh chứng",
        required=False,
        widget=forms.URLInput(attrs={**CTRL, "placeholder": "https://..."}),
    )
