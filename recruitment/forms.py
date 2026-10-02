from django import forms

from .models import Application, ApplicationStatus, RecruitmentRound

CTRL = {"class": "form-control"}
DT = {"class": "form-control", "type": "datetime-local"}
DT_FMT = "%Y-%m-%dT%H:%M"


class ApplicationForm(forms.ModelForm):
    """Đơn ứng tuyển. Chỉ hiện các Ban đang nhận đơn trong đợt."""

    class Meta:
        model = Application
        fields = ("department", "strengths", "level", "portfolio_url", "motivation")
        widgets = {
            "department": forms.RadioSelect,
            "strengths": forms.TextInput(attrs=CTRL),
            "level": forms.Select(attrs={"class": "form-select"}),
            "portfolio_url": forms.URLInput(attrs={**CTRL, "placeholder": "https://"}),
            "motivation": forms.Textarea(attrs={**CTRL, "rows": 4, "maxlength": 1000}),
        }

    def __init__(self, *args, rnd: RecruitmentRound, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = rnd.open_departments()
        self.fields["department"].required = True
        self.fields["department"].empty_label = None


class ReviewForm(forms.Form):
    """Ban chủ nhiệm / Trưởng ban chuyển trạng thái đơn."""

    status = forms.ChoiceField(label="Quyết định",
                               widget=forms.Select(attrs={"class": "form-select"}))
    interview_at = forms.DateTimeField(
        label="Lịch casting / phỏng vấn", required=False,
        input_formats=[DT_FMT], widget=forms.DateTimeInput(attrs=DT, format=DT_FMT))
    note = forms.CharField(label="Lời nhắn cho ứng viên", max_length=255, required=False,
                           widget=forms.TextInput(attrs={**CTRL, "placeholder":
                               "Vd: Mang theo đàn, casting tại phòng sinh hoạt CLB"}))

    def __init__(self, *args, app: Application, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = app.next_statuses()
        if app.interview_at:
            self.fields["interview_at"].initial = app.interview_at

    def clean(self):
        data = super().clean()
        if (data.get("status") == ApplicationStatus.INTERVIEW
                and not data.get("interview_at")):
            self.add_error("interview_at", "Chọn lịch casting / phỏng vấn.")
        return data


class RoundForm(forms.ModelForm):
    class Meta:
        model = RecruitmentRound
        fields = ("name", "opens_at", "closes_at", "departments", "description")
        widgets = {
            "name": forms.TextInput(attrs={**CTRL, "placeholder": "Vd: Tuyển thành viên Gen mới – HK1 2026-2027"}),
            "opens_at": forms.DateTimeInput(attrs=DT, format=DT_FMT),
            "closes_at": forms.DateTimeInput(attrs=DT, format=DT_FMT),
            "departments": forms.CheckboxSelectMultiple,
            "description": forms.Textarea(attrs={**CTRL, "rows": 5}),
        }

    def clean(self):
        data = super().clean()
        if data.get("opens_at") and data.get("closes_at") and \
                data["closes_at"] <= data["opens_at"]:
            self.add_error("closes_at", "Hạn nộp đơn phải sau thời điểm mở.")
        return data
