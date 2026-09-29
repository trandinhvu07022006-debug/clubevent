"""View cho M3 - Phân công công việc BTC, kèm nút AI gợi ý."""
from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Role, User
from accounts.permissions import lead_required, staff_required
from aiassist.services import suggest_tasks
from events.models import Event

from .models import Task, TaskStatus

CTRL = {"class": "form-control"}


class TaskForm(forms.ModelForm):
    """F3.1 - Tạo/sửa công việc. Người phụ trách chỉ chọn trong BTC."""

    class Meta:
        model = Task
        fields = ("title", "description", "assignee", "deadline")
        widgets = {
            "title": forms.TextInput(attrs=CTRL),
            "description": forms.Textarea(attrs={**CTRL, "rows": 3}),
            "assignee": forms.Select(attrs={"class": "form-select"}),
            "deadline": forms.DateTimeInput(
                attrs={**CTRL, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = User.objects.filter(
            role__in=[Role.STAFF, Role.LEAD, Role.ADMIN], is_locked=False)
        self.fields["assignee"].required = False


@lead_required
def task_board(request, event_id):
    """F3.5 - Bảng công việc của một sự kiện, kèm % tiến độ."""
    event = get_object_or_404(Event, pk=event_id)
    tasks = event.tasks.select_related("assignee")
    return render(request, "organizing/board.html", {
        "event": event,
        "tasks": tasks,
        "overdue_count": sum(1 for t in tasks if t.is_overdue),
    })


@lead_required
def task_create(request, event_id):
    """F3.1 - Trưởng BTC tạo công việc và giao người."""
    event = get_object_or_404(Event, pk=event_id)
    form = TaskForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.event = event
        task.save()
        messages.success(request, f"Đã tạo công việc '{task.title}'.")
        return redirect("organizing:board", event_id=event.pk)
    return render(request, "organizing/form.html", {"form": form, "event": event})


@lead_required
def task_update(request, pk):
    """F3.2 - Sửa công việc hoặc giao lại cho người khác."""
    task = get_object_or_404(Task, pk=pk)
    form = TaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã cập nhật công việc.")
        return redirect("organizing:board", event_id=task.event_id)
    return render(request, "organizing/form.html",
                  {"form": form, "event": task.event, "task": task})


@lead_required
def task_delete(request, pk):
    """F3.2 - Xoá công việc. Task đã Xong thì không xoá được."""
    task = get_object_or_404(Task, pk=pk)
    event_id = task.event_id
    if task.status == TaskStatus.DONE:
        messages.error(request, "Công việc đã hoàn thành, không xoá được.")
    else:
        task.delete()
        messages.success(request, "Đã xoá công việc.")
    return redirect("organizing:board", event_id=event_id)


@staff_required
def my_tasks(request):
    """F3.3 - Việc của tôi, sắp theo deadline, quá hạn tô đỏ."""
    tasks = (Task.objects
             .filter(assignee=request.user)
             .exclude(event__status="CANCELLED")
             .select_related("event")
             .order_by("status", "deadline"))
    return render(request, "organizing/my_tasks.html", {
        "tasks": tasks,
        "overdue_count": sum(1 for t in tasks if t.is_overdue),
    })


@staff_required
def task_set_status(request, pk):
    """F3.4 - Cập nhật tiến độ. Chỉ người phụ trách hoặc Trưởng BTC được đổi."""
    task = get_object_or_404(Task, pk=pk)

    if not task.can_be_edited_by(request.user):
        messages.error(request, "Bạn không phụ trách công việc này.")
        return redirect("organizing:my_tasks")

    new_status = request.POST.get("status", "")
    if new_status not in TaskStatus.values:
        messages.error(request, "Trạng thái không hợp lệ.")
        return redirect("organizing:my_tasks")

    task.note = request.POST.get("note", task.note)[:255]
    task.mark(new_status)
    messages.success(request,
                     f"'{task.title}' -> {task.get_status_display()}.")
    return redirect(request.POST.get("next") or "organizing:my_tasks")


@lead_required
def ai_suggest(request, event_id):
    """
    Tích hợp AI - gợi ý công việc.

    Luồng: bấm nút -> AI trả danh sách -> Trưởng BTC tick chọn -> lưu thành
    task thật. Không tự động lưu hết, để người dùng còn quyền quyết định.
    """
    event = get_object_or_404(Event, pk=event_id)

    # Bước 2: người dùng đã tick chọn và bấm Lưu
    if request.method == "POST" and request.POST.get("action") == "save":
        titles = request.POST.getlist("title")
        days_list = request.POST.getlist("days_before")
        notes = request.POST.getlist("note")
        chosen = request.POST.getlist("chosen")  # index các dòng được tick

        created = 0
        for index in chosen:
            try:
                i = int(index)
                title = titles[i].strip()
            except (ValueError, IndexError):
                continue
            if not title:
                continue
            try:
                days_before = int(days_list[i])
            except (ValueError, IndexError):
                days_before = 0
            Task.objects.create(
                event=event,
                title=title[:200],
                description=notes[i][:500] if i < len(notes) else "",
                deadline=event.starts_at - timezone.timedelta(days=days_before),
                created_by_ai=True,
            )
            created += 1

        messages.success(request, f"Đã thêm {created} công việc vào sự kiện.")
        return redirect("organizing:board", event_id=event.pk)

    # Bước 1: gọi AI lấy gợi ý
    tasks, used_ai, error = suggest_tasks(event)
    if not used_ai:
        # FALLBACK: vẫn có danh sách mặc định để dùng, chỉ báo cho user biết
        messages.warning(
            request,
            f"Không gọi được AI ({error}) nên đang hiển thị danh sách công việc "
            f"mặc định. Bạn vẫn có thể chọn, sửa rồi lưu bình thường."
        )

    # Tính sẵn deadline để user thấy ngày cụ thể chứ không phải "trước 14 ngày"
    for t in tasks:
        t["deadline"] = event.starts_at - timezone.timedelta(days=t["days_before"])

    return render(request, "organizing/ai_suggest.html", {
        "event": event, "tasks": tasks, "used_ai": used_ai,
    })
