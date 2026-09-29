"""Form cho M6 - Phản hồi."""
from django import forms

from .models import Feedback


class FeedbackForm(forms.ModelForm):
    """F6.1 - Form gửi đánh giá 1-5 sao."""

    rating = forms.ChoiceField(
        label="Bạn chấm sự kiện mấy sao?",
        choices=[(i, f"{i} sao") for i in range(5, 0, -1)],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Feedback
        fields = ("rating", "content")
        widgets = {"content": forms.Textarea(attrs={
            "class": "form-control", "rows": 4,
            "placeholder": "Điều bạn thích nhất, điều nên cải thiện..."})}
        labels = {"content": "Góp ý (không bắt buộc)"}
