"""View cho M6 - Phản hồi & thống kê."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import lead_required
from aiassist.services import summarize_feedback
from events.models import Event

from .models import Feedback
from .services import (FeedbackError, can_submit_feedback, event_statistics,
                       submit_feedback)


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


@login_required
def send_feedback(request, event_id):
    """F6.1 - Người đã check-in gửi đánh giá."""
    event = get_object_or_404(Event, pk=event_id)
    allowed, reason = can_submit_feedback(request.user, event)

    if not allowed:
        messages.error(request, reason)
        return redirect("events:detail", pk=event_id)

    form = FeedbackForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            submit_feedback(request.user, event,
                            int(form.cleaned_data["rating"]),
                            form.cleaned_data["content"])
            messages.success(request, "Cảm ơn bạn đã gửi đánh giá!")
            return redirect("events:detail", pk=event_id)
        except FeedbackError as e:
            messages.error(request, str(e))

    return render(request, "feedback/form.html", {"form": form, "event": event})


@lead_required
def feedback_list(request, event_id):
    """F6.2 + F6.3 - Xem phản hồi và thống kê của một sự kiện."""
    event = get_object_or_404(Event, pk=event_id)
    stat = event_statistics(event)

    # Dữ liệu biểu đồ, truyền qua |json_script trong template
    type_chart = {
        "labels": [row["ticket_type__name"] for row in stat["by_type"]],
        "values": [row["count"] for row in stat["by_type"]],
    }
    return render(request, "feedback/list.html", {
        "event": event,
        "feedbacks": Feedback.objects.filter(event=event).select_related("user"),
        "stat": stat,
        "type_chart": type_chart,
        "rating_dist": {"counts": stat["rating_distribution"]},
        "summary": getattr(event, "ai_summary", None),
    })


@lead_required
def ai_summarize(request, event_id):
    """
    Tích hợp AI - tóm tắt phản hồi.

    Kết quả lưu vào DB nên chỉ cần gọi API 1 lần, mở lại trang không gọi nữa.
    """
    event = get_object_or_404(Event, pk=event_id)
    summary, error = summarize_feedback(event)

    if summary:
        messages.success(request,
                         f"AI đã tóm tắt {summary.feedback_count} phản hồi.")
    else:
        # FALLBACK: không có AI thì vẫn xem được danh sách phản hồi thủ công
        messages.warning(request,
                         f"Không tóm tắt được bằng AI ({error}). "
                         f"Bạn vẫn có thể đọc danh sách phản hồi bên dưới.")
    return redirect("feedback:list", event_id=event_id)
