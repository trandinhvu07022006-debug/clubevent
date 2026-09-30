"""View cho M3 - Phân công công việc BTC, kèm nút AI gợi ý."""
import csv

from django import forms
from django.contrib import messages
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from accounts.permissions import lead_required, staff_required
from aiassist.services import suggest_tasks
from events.models import Event, EventStatus
from events.services import budget_summary

from .models import Expense, Task, TaskPriority, TaskStatus
from .services import delete_expense, save_expense, save_task

CTRL = {"class": "form-control"}


class TaskForm(forms.ModelForm):
    """F3.1 - Tạo/sửa công việc. Người phụ trách chỉ chọn trong BTC."""

    class Meta:
        model = Task
        fields = ("title", "description", "assignee", "priority", "deadline")
        widgets = {
            "title": forms.TextInput(attrs=CTRL),
            "description": forms.Textarea(attrs={**CTRL, "rows": 3}),
            "assignee": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "deadline": forms.DateTimeInput(
                attrs={**CTRL, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Người nhận việc: mọi thành viên BTC, kể cả Ban chủ nhiệm (Trưởng BTC, Admin)
        self.fields["assignee"].queryset = (User.objects.filter(
            role__in=[Role.STAFF, Role.LEAD, Role.ADMIN], is_locked=False)
            .order_by("role", "full_name"))
        self.fields["assignee"].label_from_instance = (
            lambda u: f"{u.full_name or u.username} — {u.get_role_display()}")
        self.fields["assignee"].required = False


class AssignForm(TaskForm):
    """
    Giao việc nhanh của Ban chủ nhiệm từ trang "Việc của tôi".

    Khác TaskForm ở chỗ chọn được sự kiện, hoặc để trống = việc chung của CLB;
    và bắt buộc có người nhận (giao việc mà không giao cho ai thì vô nghĩa).
    """

    class Meta(TaskForm.Meta):
        fields = ("title", "event", "assignee", "priority", "deadline", "description")
        widgets = {**TaskForm.Meta.widgets,
                   "event": forms.Select(attrs={"class": "form-select"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].required = True
        # Chỉ sự kiện còn đang tổ chức; sự kiện đã xong/huỷ thì không giao thêm
        self.fields["event"].queryset = Event.objects.exclude(
            status__in=[EventStatus.DONE, EventStatus.CANCELLED]).order_by("starts_at")
        self.fields["event"].empty_label = "— Việc chung của CLB (không thuộc sự kiện) —"
        self.fields["event"].required = False


def _back_to_task_list(task):
    """Sau khi sửa/xoá: việc thuộc sự kiện về bảng công việc, việc chung về 'Đã giao'."""
    if task.event_id:
        return redirect("organizing:board", event_id=task.event_id)
    return redirect(reverse("organizing:my_tasks") + "?view=assigned")


class ExpenseForm(forms.ModelForm):
    """Ghi một khoản chi của sự kiện."""

    class Meta:
        model = Expense
        fields = ("title", "category", "amount", "paid_by", "spent_on", "note",
                  "receipt")
        widgets = {
            "title": forms.TextInput(attrs=CTRL),
            "category": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={**CTRL, "min": 0, "step": 1000}),
            "paid_by": forms.Select(attrs={"class": "form-select"}),
            "spent_on": forms.DateInput(attrs={**CTRL, "type": "date"},
                                        format="%Y-%m-%d"),
            "note": forms.TextInput(attrs=CTRL),
            "receipt": forms.ClearableFileInput(attrs=CTRL),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paid_by"].queryset = User.objects.filter(
            role__in=[Role.STAFF, Role.LEAD, Role.ADMIN])
        self.fields["paid_by"].required = False


@lead_required
def task_board(request, event_id):
    """F3.5 - Bảng công việc của một sự kiện, kèm % tiến độ."""
    event = get_object_or_404(Event, pk=event_id)
    tasks = event.tasks.select_related("assignee")
    return render(request, "organizing/board.html", {
        "event": event,
        "tasks": tasks,
        "overdue_count": sum(1 for t in tasks if t.is_overdue),
        "done_count": sum(1 for t in tasks if t.status == "DONE"),
        "total_count": len(tasks),
    })


@lead_required
def task_create(request, event_id):
    """F3.1 - Trưởng BTC tạo công việc và giao người."""
    event = get_object_or_404(Event, pk=event_id)
    form = TaskForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.event = event
        task.created_by = request.user
        save_task(request.user, task)
        messages.success(request, f"Đã tạo công việc '{task.title}'.")
        return redirect("organizing:board", event_id=event.pk)
    return render(request, "organizing/form.html", {"form": form, "event": event})


@lead_required
def task_update(request, pk):
    """F3.2 - Sửa công việc hoặc giao lại cho người khác."""
    task = get_object_or_404(Task, pk=pk)
    old_assignee_id = task.assignee_id
    # Việc chung (không thuộc sự kiện) sửa bằng form giao việc để giữ ô Sự kiện
    form_class = TaskForm if task.event_id else AssignForm
    form = form_class(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        save_task(request.user, form.save(commit=False), old_assignee_id)
        messages.success(request, "Đã cập nhật công việc.")
        return _back_to_task_list(task)
    return render(request, "organizing/form.html",
                  {"form": form, "event": task.event, "task": task})


@require_POST
@lead_required
def task_delete(request, pk):
    """F3.2 - Xoá công việc. Task đã Xong thì không xoá được. Bắt buộc POST."""
    task = get_object_or_404(Task, pk=pk)
    if task.status == TaskStatus.DONE:
        messages.error(request, "Công việc đã hoàn thành, không xoá được.")
    else:
        task.delete()
        messages.success(request, "Đã xoá công việc.")
    return _back_to_task_list(task)


@lead_required
def task_assign(request):
    """
    Ban chủ nhiệm giao việc: cho một sự kiện hoặc việc chung của CLB, cho bất
    kỳ thành viên BTC nào — kể cả các thành viên Ban chủ nhiệm khác.
    Người nhận được thông báo + email (qua save_task).
    """
    initial = {}
    if request.GET.get("event", "").isdigit():
        initial["event"] = request.GET["event"]
    form = AssignForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.created_by = request.user
        save_task(request.user, task)
        who = task.assignee.full_name or task.assignee.username
        messages.success(request, f"Đã giao '{task.title}' cho {who}.")
        if request.POST.get("again"):
            return redirect("organizing:assign")
        return redirect(reverse("organizing:my_tasks") + "?view=assigned")
    return render(request, "organizing/assign.html", {"form": form})


# Sắp xếp: việc chưa xong lên trước, gấp lên trước, rồi theo deadline
_OPEN_FIRST = Case(When(status=TaskStatus.DONE, then=Value(1)), default=Value(0),
                   output_field=IntegerField())
_PRIORITY_RANK = Case(When(priority=TaskPriority.URGENT, then=Value(0)),
                      When(priority=TaskPriority.HIGH, then=Value(1)),
                      When(priority=TaskPriority.NORMAL, then=Value(2)),
                      default=Value(3), output_field=IntegerField())


@staff_required
def my_tasks(request):
    """
    F3.3 - Việc của tôi, sắp theo deadline, quá hạn tô đỏ.

    Ban chủ nhiệm có thêm chế độ xem "Việc tôi đã giao" (?view=assigned) để
    theo dõi tiến độ những việc mình giao cho người khác.
    """
    status = request.GET.get("status")
    view = request.GET.get("view")
    if view != "assigned" or not request.user.is_lead:
        view = "mine"

    if view == "assigned":
        base = Task.objects.filter(created_by=request.user)
    else:
        base = Task.objects.filter(assignee=request.user)
    base = (base.filter(Q(event__isnull=True) | ~Q(event__status=EventStatus.CANCELLED))
            .select_related("event", "assignee", "created_by"))

    counts = base.aggregate(
        all=Count("id"),
        todo=Count("id", filter=Q(status=TaskStatus.TODO)),
        doing=Count("id", filter=Q(status=TaskStatus.DOING)),
        done=Count("id", filter=Q(status=TaskStatus.DONE)),
    )
    tasks_query = base.order_by(_OPEN_FIRST, _PRIORITY_RANK,
                                "deadline", "id")
    if status in TaskStatus.values:
        tasks_query = tasks_query.filter(status=status)
    else:
        status = ""
    tasks = list(tasks_query)

    return render(request, "organizing/my_tasks.html", {
        "tasks": tasks,
        "overdue_count": sum(1 for t in tasks if t.is_overdue),
        "current_status": status,
        "view": view,
        "counts": counts,
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
    # Chỉ quay về trang nội bộ — chặn open redirect qua tham số next
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("organizing:my_tasks")


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
                created_by=request.user,
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


# ---------------------------------------------------------------------------
# NGÂN SÁCH SỰ KIỆN — chỉ Trưởng BTC trở lên (dữ liệu tài chính)
# ---------------------------------------------------------------------------
@lead_required
def budget(request, event_id):
    """Tổng quan thu - chi - lãi/lỗ và danh sách khoản chi của sự kiện."""
    event = get_object_or_404(Event, pk=event_id)
    summary = budget_summary(event)
    return render(request, "organizing/budget.html", {
        "event": event,
        "summary": summary,
        "expenses": event.expenses.select_related("paid_by"),
    })


@lead_required
def expense_create(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    form = ExpenseForm(request.POST or None, request.FILES or None,
                       initial={"paid_by": request.user})
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.event = event
        expense.created_by = request.user
        save_expense(request.user, expense, is_new=True)
        messages.success(request, f"Đã ghi khoản chi '{expense.title}'.")
        return redirect("organizing:budget", event_id=event.pk)
    return render(request, "organizing/expense_form.html",
                  {"form": form, "event": event})


@lead_required
def expense_update(request, pk):
    expense = get_object_or_404(Expense.objects.select_related("event"), pk=pk)
    form = ExpenseForm(request.POST or None, request.FILES or None, instance=expense)
    if request.method == "POST" and form.is_valid():
        save_expense(request.user, form.save(commit=False), is_new=False)
        messages.success(request, "Đã cập nhật khoản chi.")
        return redirect("organizing:budget", event_id=expense.event_id)
    return render(request, "organizing/expense_form.html",
                  {"form": form, "event": expense.event, "expense": expense})


@require_POST
@lead_required
def expense_delete(request, pk):
    expense = get_object_or_404(Expense.objects.select_related("event"), pk=pk)
    event_id = expense.event_id
    delete_expense(request.user, expense)
    messages.success(request, "Đã xoá khoản chi.")
    return redirect("organizing:budget", event_id=event_id)


@lead_required
def budget_csv(request, event_id):
    """Xuất bảng chi tiêu ra CSV để nộp quyết toán."""
    event = get_object_or_404(Event, pk=event_id)
    summary = budget_summary(event)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="ngan-sach-{event.pk}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Ngày chi", "Khoản chi", "Hạng mục", "Số tiền", "Người chi",
                     "Ghi chú"])
    for e in event.expenses.select_related("paid_by"):
        writer.writerow([e.spent_on.strftime("%d/%m/%Y"), e.title,
                         e.get_category_display(), e.amount,
                         e.paid_by.full_name if e.paid_by else "", e.note])
    writer.writerow([])
    writer.writerow(["", "Tổng thu (vé đã xác nhận)", "", summary["income"]])
    writer.writerow(["", "Tổng chi", "", summary["spent"]])
    writer.writerow(["", "Chênh lệch", "", summary["balance"]])
    return response
