"""Form cho M2 - Sự kiện."""
from django import forms
from django.utils import timezone

from .models import Event, TicketType

CTRL = {"class": "form-control"}
DT = {"class": "form-control", "type": "datetime-local"}


class EventForm(forms.ModelForm):
    """F2.1 - Tạo/sửa sự kiện."""

    class Meta:
        model = Event
        fields = ("name", "category", "description", "location", "starts_at",
                  "ends_at", "register_deadline", "capacity", "budget", "cover")
        widgets = {
            "name": forms.TextInput(attrs=CTRL),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={**CTRL, "rows": 4}),
            "location": forms.TextInput(attrs=CTRL),
            "starts_at": forms.DateTimeInput(attrs=DT, format="%Y-%m-%dT%H:%M"),
            "ends_at": forms.DateTimeInput(attrs=DT, format="%Y-%m-%dT%H:%M"),
            "register_deadline": forms.DateTimeInput(attrs=DT, format="%Y-%m-%dT%H:%M"),
            "capacity": forms.NumberInput(attrs={**CTRL, "min": 1}),
            "budget": forms.NumberInput(attrs={**CTRL, "min": 0, "step": 10000}),
            "cover": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        """Ràng buộc: hạn đăng ký phải trước giờ diễn ra."""
        data = super().clean()
        starts_at, deadline = data.get("starts_at"), data.get("register_deadline")
        if starts_at and deadline and deadline > starts_at:
            self.add_error("register_deadline",
                           "Hạn đăng ký phải trước thời gian diễn ra sự kiện.")
        # B4 - giờ kết thúc phải sau giờ bắt đầu
        ends_at = data.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error("ends_at", "Giờ kết thúc phải sau giờ bắt đầu.")
        # Chỉ kiểm tra khi tạo mới, để còn sửa được sự kiện cũ
        if starts_at and not self.instance.pk and starts_at < timezone.now():
            self.add_error("starts_at", "Thời gian diễn ra phải ở tương lai.")
        return data


class TicketTypeForm(forms.ModelForm):
    """F2.2 - Loại vé. Giá 0 là vé miễn phí."""

    class Meta:
        model = TicketType
        fields = ("name", "price", "quota")
        widgets = {
            "name": forms.TextInput(attrs=CTRL),
            "price": forms.NumberInput(attrs={**CTRL, "min": 0, "step": 1000}),
            "quota": forms.NumberInput(attrs={**CTRL, "min": 1}),
        }

    def __init__(self, *args, event=None, **kwargs):
        self.event = event
        super().__init__(*args, **kwargs)

    def clean_quota(self):
        """Tổng số vé các loại không được vượt sức chứa sự kiện."""
        quota = self.cleaned_data["quota"]
        event = self.event or getattr(self.instance, "event", None)
        if event:
            others = event.ticket_types.exclude(pk=self.instance.pk or 0)
            used = sum(t.quota for t in others)
            if used + quota > event.capacity:
                raise forms.ValidationError(
                    f"Vượt sức chứa sự kiện ({event.capacity}). "
                    f"Các loại vé khác đã chiếm {used}, còn lại {event.capacity - used}."
                )
        return quota
