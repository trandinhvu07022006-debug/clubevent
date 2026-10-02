"""View cho M3 - Phân công công việc BTC, kèm nút AI gợi ý."""
import csv
import re

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts.models import AuditLog, Role, User
from accounts.permissions import lead_required, member_required, staff_required
from aiassist.services import suggest_tasks
from core import once
from core.images import shrink_image
from events.models import Event, EventStatus
from events.services import budget_summary

from .models import Department, Expense, Task, TaskPriority, TaskStatus
from .services import (claim_task, delete_expense, departments_with_stats,
                       department_people, save_expense, save_task)

CTRL = {"class": "form-control"}


BTC_ROLES = [Role.STAFF, Role.LEAD, Role.ADMIN]


class TaskForm(forms.ModelForm):
    """F3.1 - Tạo/sửa công việc. Người phụ trách chỉ chọn trong BTC."""

    class Meta:
        model = Task
        fields = ("title", "description", "department", "assignee", "priority",
                  "deadline")
        widgets = {
            "title": forms.TextInput(attrs=CTRL),
            "description": forms.Textarea(attrs={**CTRL, "rows": 3}),
            "department": forms.Select(attrs={"class": "form-select"}),
            "assignee": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "deadline": forms.DateTimeInput(
                attrs={**CTRL, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Người nhận việc: mọi thành viên BTC, kể cả Ban chủ nhiệm (Trưởng BTC, Admin)
        self.fields["assignee"].queryset = (User.objects.filter(
            role__in=BTC_ROLES, is_locked=False).order_by("role", "full_name"))
        self.fields["assignee"].label_from_instance = (
            lambda u: f"{u.full_name or u.username} - {u.get_role_display()}")
        self.fields["assignee"].required = False
        self.fields["department"].required = False
        self.fields["department"].empty_label = "- Không thuộc Ban nào -"


class AssignForm(TaskForm):
    """
    Giao việc nhanh từ trang "Việc của tôi" / trang Ban.

    - Chọn được sự kiện, hoặc để trống = việc chung của CLB.
    - Giao cho MỘT NGƯỜI, cho CẢ BAN (thành viên tự nhận), hoặc cả hai
      (người đó phụ trách, Ban cùng theo dõi). Phải có ít nhất một trong hai.
    - Ban chủ nhiệm giao cho bất kỳ ai. Trưởng ban (không phải Trưởng BTC)
      chỉ giao được trong Ban mình quản và cho người trong Ban đó.
    """

    class Meta(TaskForm.Meta):
        fields = ("title", "event", "department", "assignee", "priority",
                  "deadline", "description")
        widgets = {**TaskForm.Meta.widgets,
                   "event": forms.Select(attrs={"class": "form-select"})}

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        # Chỉ sự kiện còn đang tổ chức; sự kiện đã xong/huỷ thì không giao thêm
        self.fields["event"].queryset = Event.objects.exclude(
            status__in=[EventStatus.DONE, EventStatus.CANCELLED]).order_by("starts_at")
        self.fields["event"].empty_label = "- Việc chung của CLB (không thuộc sự kiện) -"
        self.fields["event"].required = False
        self.fields["assignee"].empty_label = "- Để Ban tự nhận -"

        if actor is not None and not actor.is_lead:
            led = Department.objects.filter(lead=actor)
            self.fields["department"].queryset = led
            self.fields["department"].required = True
            self.fields["department"].empty_label = None
            self.fields["assignee"].queryset = (User.objects.filter(
                Q(departments__in=led) | Q(led_departments__in=led),
                role__in=BTC_ROLES, is_locked=False)
                .distinct().order_by("full_name"))

    def clean(self):
        data = super().clean()
        assignee, dept = data.get("assignee"), data.get("department")
        if not assignee and not dept:
            raise forms.ValidationError(
                "Chọn người nhận, hoặc chọn Ban để thành viên Ban tự nhận việc.")
        restricted = self.actor is not None and not self.actor.is_lead
        if restricted and assignee and dept and not dept.has_member(assignee):
            self.add_error("assignee", f"{assignee.full_name or assignee.username} "
                                       f"không thuộc {dept.name}.")
        return data


class DepartmentForm(forms.ModelForm):
    """Tạo / sửa một Ban. Đường dẫn để trống thì tự sinh từ tên."""

    class Meta:
        model = Department
        fields = ("name", "slug", "icon", "description", "lead", "members", "order")
        widgets = {
            "name": forms.TextInput(attrs={**CTRL, "placeholder": "Vd: Ban Truyền thông"}),
            "slug": forms.TextInput(attrs={**CTRL, "placeholder": "tự sinh nếu để trống"}),
            "icon": forms.TextInput(attrs={**CTRL, "placeholder": "bi-megaphone"}),
            "description": forms.TextInput(attrs=CTRL),
            "lead": forms.Select(attrs={"class": "form-select"}),
            "members": forms.CheckboxSelectMultiple,
            "order": forms.NumberInput(attrs={**CTRL, "min": 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        btc = (User.objects.filter(role__in=BTC_ROLES, is_locked=False)
               .order_by("full_name"))
        official = (User.objects.exclude(role=Role.GUEST).filter(is_locked=False)
                    .order_by("role", "full_name"))
        self.fields["lead"].queryset = btc
        self.fields["members"].queryset = official
        label = lambda u: f"{u.full_name or u.username} - {u.get_role_display()}"  # noqa: E731
        self.fields["lead"].label_from_instance = label
        self.fields["members"].label_from_instance = label
        self.fields["slug"].required = False
        self.fields["members"].help_text = (
            "Thành viên chính thức trở lên (Khách phải qua đợt tuyển). Chỉ người "
            "trong Ban tổ chức mới nhận được việc của Ban.")

    def clean_icon(self):
        icon = (self.cleaned_data.get("icon") or "bi-people").strip()
        # Chỉ nhận tên class icon hợp lệ, chặn chèn class/thuộc tính lạ vào HTML
        if not re.fullmatch(r"bi-[a-z0-9-]{1,36}", icon):
            raise forms.ValidationError("Icon có dạng bi-ten-icon, vd bi-megaphone.")
        return icon

    def clean(self):
        data = super().clean()
        if not data.get("slug") and data.get("name"):
            slug = vn_slugify(data["name"])
            exists = Department.objects.filter(slug=slug)
            if self.instance.pk:
                exists = exists.exclude(pk=self.instance.pk)
            if exists.exists():
                self.add_error("slug", "Đường dẫn này đã có Ban khác dùng, hãy nhập tay.")
            data["slug"] = slug
            self.instance.slug = slug
        return data


def vn_slugify(text: str) -> str:
    """slugify của Django bỏ mất chữ 'đ' (không tách dấu được) -> thay trước."""
    return slugify(text.replace("đ", "d").replace("Đ", "D"))[:80] or "ban"


def _can_assign(user) -> bool:
    """Ban chủ nhiệm, hoặc Trưởng của ít nhất một Ban."""
    return user.is_lead or Department.objects.filter(lead=user).exists()


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

    def clean_receipt(self):
        receipt = self.cleaned_data.get("receipt")
        if receipt and getattr(receipt, "size", 0) > 5 * 1024 * 1024:
            raise forms.ValidationError("Ảnh hoá đơn tối đa 5 MB.")
        # Hoá đơn cần đọc được chữ nên giữ độ phân giải cao hơn
        return shrink_image(receipt, 2000, quality=85)


@lead_required
def task_board(request, event_id):
    """F3.5 - Bảng công việc của một sự kiện, kèm % tiến độ."""
    event = get_object_or_404(Event, pk=event_id)
    tasks = event.tasks.select_related("assignee", "department")
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
    if request.method == "POST" and not once.consume(request):
        messages.info(request, "Yêu cầu này đã được gửi rồi - bỏ qua lần bấm trùng.")
        return redirect("organizing:board", event_id=event.pk)
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
    old = (task.assignee_id, task.department_id, task.deadline)
    # Việc chung (không thuộc sự kiện) sửa bằng form giao việc để giữ ô Sự kiện
    form_class = TaskForm if task.event_id else AssignForm
    form = form_class(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        save_task(request.user, form.save(commit=False), old_assignee_id=old[0],
                  old_department_id=old[1], old_deadline=old[2])
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


@staff_required
def task_assign(request):
    """
    Giao việc: cho một sự kiện hoặc việc chung của CLB; cho một người hoặc
    cho cả một Ban. Ban chủ nhiệm giao cho bất kỳ ai; Trưởng ban giao trong
    Ban của mình. Người nhận được thông báo + email (qua save_task).
    """
    if not _can_assign(request.user):
        raise PermissionDenied("Chỉ Ban chủ nhiệm hoặc Trưởng ban được giao việc.")
    initial = {}
    for key in ("event", "department"):
        if request.GET.get(key, "").isdigit():
            initial[key] = request.GET[key]
    form = AssignForm(request.POST or None, initial=initial, actor=request.user)
    if request.method == "POST" and not once.consume(request):
        messages.info(request, "Yêu cầu này đã được gửi rồi - bỏ qua lần bấm trùng.")
        return redirect(reverse("organizing:my_tasks") + "?view=assigned")
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.created_by = request.user
        save_task(request.user, task)
        if task.assignee_id:
            who = task.assignee.full_name or task.assignee.username
        else:
            who = f"{task.department.name} (chờ thành viên nhận)"
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
    can_assign = _can_assign(request.user)
    if view != "assigned" or not can_assign:
        view = "mine"

    live = Q(event__isnull=True) | ~Q(event__status=EventStatus.CANCELLED)
    if view == "assigned":
        base = Task.objects.filter(created_by=request.user)
    else:
        base = Task.objects.filter(assignee=request.user)
    base = base.filter(live).select_related("event", "assignee", "created_by",
                                            "department")

    # Việc của các Ban mình thuộc về mà CHƯA AI NHẬN - hiện riêng để nhận nhanh
    claimable = []
    if view == "mine":
        my_depts = Department.objects.filter(
            Q(members=request.user) | Q(lead=request.user)).distinct()
        claimable = list(Task.objects.filter(
            live, department__in=my_depts, assignee__isnull=True)
            .exclude(status=TaskStatus.DONE)
            .select_related("event", "department", "created_by")
            .order_by(_PRIORITY_RANK, "deadline"))

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
        "claimable": claimable,
        "can_assign": can_assign,
    })


@require_POST
@staff_required
def task_claim(request, pk):
    """Thành viên Ban tự nhận một việc đang chờ của Ban."""
    task = get_object_or_404(Task.objects.select_related("department"), pk=pk)
    if claim_task(request.user, task):
        messages.success(request, f"Bạn đã nhận việc '{task.title}'.")
    else:
        messages.error(request, "Không nhận được: việc đã có người nhận "
                                "hoặc bạn không thuộc Ban này.")
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("organizing:my_tasks")


# ---------------------------------------------------------------------------
# CÁC BAN - đơn vị tổ chức trong CLB
# ---------------------------------------------------------------------------
@member_required
def department_list(request):
    """Tất cả các Ban kèm tiến độ; Ban của tôi được đưa lên đầu."""
    rows = departments_with_stats()
    mine_ids = set(Department.objects.filter(
        Q(members=request.user) | Q(lead=request.user)).values_list("pk", flat=True))
    for d in rows:
        d.is_mine = d.pk in mine_ids
    rows.sort(key=lambda d: (not d.is_mine, d.order, d.name))
    return render(request, "organizing/department_list.html", {
        "departments": rows,
        "mine_count": len(mine_ids),
    })


@member_required
def department_detail(request, slug):
    """Trang của một Ban: thành viên, việc đang treo chờ nhận, tiến độ."""
    dept = get_object_or_404(Department.objects.select_related("lead"), slug=slug)
    status = request.GET.get("status", "")
    live = Q(event__isnull=True) | ~Q(event__status=EventStatus.CANCELLED)
    all_tasks = (dept.tasks.filter(live)
                 .select_related("event", "assignee", "created_by"))
    counts = all_tasks.aggregate(
        all=Count("id"),
        todo=Count("id", filter=Q(status=TaskStatus.TODO)),
        doing=Count("id", filter=Q(status=TaskStatus.DOING)),
        done=Count("id", filter=Q(status=TaskStatus.DONE)),
    )
    tasks = all_tasks.order_by(_OPEN_FIRST, _PRIORITY_RANK, "deadline", "id")
    if status in TaskStatus.values:
        tasks = tasks.filter(status=status)
    else:
        status = ""
    tasks = list(tasks)
    for t in tasks:
        t.claimable = t.can_be_claimed_by(request.user)

    people = sorted(department_people(dept),
                    key=lambda u: (u.pk != dept.lead_id, u.full_name or u.username))
    # Số việc đang mở của từng người trong Ban - để Trưởng ban chia việc đều tay
    load = dict(Task.objects.filter(department=dept, assignee__in=people)
                .exclude(status=TaskStatus.DONE)
                .values_list("assignee").annotate(n=Count("id")))
    for u in people:
        u.open_load = load.get(u.pk, 0)

    return render(request, "organizing/department_detail.html", {
        "dept": dept,
        "tasks": tasks,
        "counts": counts,
        "current_status": status,
        "progress": round(counts["done"] * 100 / counts["all"]) if counts["all"] else 0,
        "overdue_count": sum(1 for t in tasks if t.is_overdue),
        "unclaimed_count": sum(1 for t in tasks
                               if t.assignee_id is None and t.status != TaskStatus.DONE),
        "people": people,
        "is_member": dept.has_member(request.user),
        "can_manage": dept.is_managed_by(request.user),
    })


@lead_required
def department_create(request):
    form = DepartmentForm(request.POST or None)
    if request.method == "POST" and not once.consume(request):
        messages.info(request, "Yêu cầu này đã được gửi rồi - bỏ qua lần bấm trùng.")
        return redirect("organizing:department_list")
    if request.method == "POST" and form.is_valid():
        dept = form.save()
        AuditLog.write(request.user, "Tạo Ban", dept.name)
        messages.success(request, f"Đã tạo {dept.name}.")
        return redirect(dept)
    return render(request, "organizing/department_form.html", {"form": form})


@lead_required
def department_update(request, slug):
    dept = get_object_or_404(Department, slug=slug)
    form = DepartmentForm(request.POST or None, instance=dept)
    if request.method == "POST" and form.is_valid():
        dept = form.save()
        AuditLog.write(request.user, "Sửa Ban", dept.name)
        messages.success(request, f"Đã cập nhật {dept.name}.")
        return redirect(dept)
    return render(request, "organizing/department_form.html",
                  {"form": form, "dept": dept})


@require_POST
@lead_required
def department_delete(request, slug):
    """Xoá Ban. Công việc của Ban VẪN GIỮ (chỉ bỏ gắn Ban), không mất dữ liệu."""
    dept = get_object_or_404(Department, slug=slug)
    AuditLog.write(request.user, "Xoá Ban", dept.name)
    dept.delete()
    messages.success(request, f"Đã xoá {dept.name}. Công việc của Ban vẫn được giữ lại.")
    return redirect("organizing:department_list")


@require_POST
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
    # Chỉ quay về trang nội bộ - chặn open redirect qua tham số next
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
# NGÂN SÁCH SỰ KIỆN - chỉ Trưởng BTC trở lên (dữ liệu tài chính)
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
    if request.method == "POST" and not once.consume(request):
        messages.info(request, "Yêu cầu này đã được gửi rồi - bỏ qua lần bấm trùng.")
        return redirect("organizing:budget", event_id=event.pk)
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
