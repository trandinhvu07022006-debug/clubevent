"""Tầng SERVICE cho M3 - Công việc BTC, các Ban và ngân sách sự kiện."""
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User
from notifications.models import NotificationKind
from notifications.services import notify_many, notify_on_commit

from .models import Department, Expense, Task, TaskStatus

_UNSET = object()


def _fmt_deadline(task: Task) -> str:
    return (timezone.localtime(task.deadline).strftime("%H:%M %d/%m/%Y")
            if task.deadline else "Chưa đặt")


@transaction.atomic
def save_task(actor, task: Task, old_assignee_id=None, old_department_id=None,
              old_deadline=_UNSET) -> Task:
    """
    Lưu công việc và F7.1 - báo cho người được giao.

    - Giao cho MỘT NGƯỜI: báo người đó khi người phụ trách THỰC SỰ đổi (so với
      giá trị cũ), không báo khi chỉ sửa mô tả; không báo khi tự giao cho mình.
    - Giao cho CẢ BAN (chưa chỉ định người): báo mọi thành viên Ban để ai rảnh
      thì nhận việc. Chỉ báo khi Ban đổi, tránh spam mỗi lần sửa.
    - Đổi deadline: xoá dấu "đã nhắc" để lệnh định kỳ nhắc lại theo hạn mới.
    """
    if old_deadline is not _UNSET and old_deadline != task.deadline:
        task.due_reminded_at = None
        task.overdue_reminded_at = None
    task.save()

    deadline = _fmt_deadline(task)
    scope = f"của sự kiện {task.event.name}" if task.event_id else "(việc chung của CLB)"
    urgent = " [GẤP]" if task.priority == "URGENT" else ""
    actor_name = actor.full_name or actor.username
    url = reverse("organizing:my_tasks")

    new_id = task.assignee_id
    if new_id and new_id != old_assignee_id and new_id != actor.pk:
        title = f"Việc mới: {task.title}"
        message = (f"{actor_name} giao cho bạn công việc "
                   f"\"{task.title}\"{urgent} {scope}. Deadline: {deadline}.")
        notify_on_commit(
            task.assignee, NotificationKind.TASK_ASSIGNED, title, message,
            url=url, email_template="notice",
            context={"title": title, "message": message,
                     "details": [("Công việc", task.title),
                                 ("Thuộc", task.scope_label),
                                 ("Ban", task.department.name if task.department_id else "-"),
                                 ("Mức ưu tiên", task.get_priority_display()),
                                 ("Người giao", actor_name),
                                 ("Deadline", deadline)],
                     "note": task.description[:300] if task.description else "",
                     "cta_url": url, "cta_label": "Mở việc của tôi"})
    elif (not new_id and task.department_id
          and task.department_id != old_department_id):
        dept = task.department
        users = [u for u in department_people(dept, btc_only=True) if u.pk != actor.pk]
        title = f"Việc mới cho {dept.name}: {task.title}"
        message = (f"{actor_name} giao cho {dept.name} công việc \"{task.title}\""
                   f"{urgent} {scope}. Chưa có ai nhận - vào trang Ban để nhận việc. "
                   f"Deadline: {deadline}.")
        dept_url = dept.get_absolute_url()
        transaction.on_commit(lambda: notify_many(
            users, NotificationKind.TASK_ASSIGNED, title, message, url=dept_url))
    return task


@transaction.atomic
def claim_task(user, task: Task) -> bool:
    """
    Thành viên Ban tự nhận một việc đang treo của Ban.

    Khoá dòng để 2 người bấm "Nhận" cùng lúc thì chỉ 1 người được (cùng cách
    chống bán vượt vé). Trả về False nếu việc đã có người nhận trước.
    """
    task = (Task.objects.select_for_update().select_related("department")
            .get(pk=task.pk))
    if not task.can_be_claimed_by(user):
        return False
    task.assignee = user
    task.save(update_fields=["assignee"])
    AuditLog.write(user, "Nhận việc của Ban", task.title,
                   task.department.name if task.department_id else "")
    return True


# ---------------------------------------------------------------------------
# CÁC BAN
# ---------------------------------------------------------------------------
def department_people(dept: Department, btc_only=False) -> list[User]:
    """
    Trưởng ban + thành viên, không trùng, bỏ tài khoản bị khoá.
    btc_only=True: chỉ người trong Ban tổ chức - dùng khi BÁO VIỆC, vì Thành
    viên thường không vào được trang công việc, báo cho họ chỉ gây rối.
    """
    people = {u.pk: u for u in dept.members.filter(is_locked=False)}
    if dept.lead_id and not dept.lead.is_locked:
        people.setdefault(dept.lead_id, dept.lead)
    if btc_only:
        return [u for u in people.values() if u.is_staff_btc]
    return list(people.values())


def departments_with_stats(qs=None):
    """
    Danh sách Ban kèm số liệu tiến độ, tính bằng MỘT truy vấn có annotate
    (không lặp truy vấn theo từng Ban). Việc của sự kiện đã huỷ không tính.
    """
    now = timezone.now()
    live = Q(tasks__event__isnull=True) | ~Q(tasks__event__status="CANCELLED")
    not_done = ~Q(tasks__status=TaskStatus.DONE)
    qs = qs if qs is not None else Department.objects.all()
    rows = list(qs.select_related("lead").annotate(
        task_total=Count("tasks", filter=live, distinct=True),
        task_done=Count("tasks", filter=live & Q(tasks__status=TaskStatus.DONE),
                        distinct=True),
        task_unclaimed=Count("tasks", filter=live & not_done
                             & Q(tasks__assignee__isnull=True), distinct=True),
        task_overdue=Count("tasks", filter=live & not_done
                           & Q(tasks__deadline__lt=now), distinct=True),
        member_count=Count("members", distinct=True),
    ))
    for d in rows:
        d.progress = round(d.task_done * 100 / d.task_total) if d.task_total else 0
    return rows


# ---------------------------------------------------------------------------
# NHẮC HẠN CÔNG VIỆC - chạy trong run_periodic (mỗi 15 phút)
# ---------------------------------------------------------------------------
def send_task_reminders() -> int:
    """
    Nhắc việc sắp đến hạn (trong 24h tới) và báo việc vừa quá hạn.

    - Mỗi việc nhắc tối đa 1 lần "sắp đến hạn" + 1 lần "quá hạn": đánh dấu
      due_reminded_at / overdue_reminded_at TRƯỚC khi gửi, trong transaction
      có khoá dòng, nên lệnh chạy 2 lần cũng không gửi trùng.
    - Người nhận: người phụ trách; việc chưa ai nhận thì gửi cả Ban.
    - Quá hạn thì báo thêm cho người giao việc, để Ban chủ nhiệm nắm được.
    - Việc của sự kiện đã huỷ / đã diễn ra thì bỏ qua.
    Trả về số việc đã nhắc.
    """
    now = timezone.now()
    base = (Task.objects.exclude(status=TaskStatus.DONE)
            .filter(deadline__isnull=False)
            .filter(Q(event__isnull=True)
                    | ~Q(event__status__in=["CANCELLED", "DONE"])))
    due_ids = list(base.filter(deadline__gt=now,
                               deadline__lte=now + timezone.timedelta(hours=24),
                               due_reminded_at__isnull=True)
                   .values_list("pk", flat=True))
    overdue_ids = list(base.filter(deadline__lte=now,
                                   overdue_reminded_at__isnull=True)
                       .values_list("pk", flat=True))

    sent = 0
    for pk in due_ids:
        sent += _remind_one(pk, overdue=False, now=now)
    for pk in overdue_ids:
        sent += _remind_one(pk, overdue=True, now=now)
    return sent


def _remind_one(pk, overdue: bool, now) -> int:
    field = "overdue_reminded_at" if overdue else "due_reminded_at"
    with transaction.atomic():
        task = (Task.objects.select_for_update()
                .select_related("assignee", "department__lead", "created_by", "event")
                .get(pk=pk))
        if getattr(task, field):
            return 0                                   # tiến trình khác đã gửi
        setattr(task, field, now)
        # Đã quá hạn thì không cần nhắc "sắp đến hạn" nữa
        if overdue and not task.due_reminded_at:
            task.due_reminded_at = now
        task.save(update_fields=["due_reminded_at", "overdue_reminded_at"])

        if task.assignee_id:
            users = [task.assignee]
            url = reverse("organizing:my_tasks")
        elif task.department_id:
            users = department_people(task.department, btc_only=True)
            url = task.department.get_absolute_url()
        else:
            users = []
            url = reverse("organizing:my_tasks")
        if overdue and task.created_by_id and task.created_by not in users:
            users.append(task.created_by)
        users = [u for u in users if not u.is_locked]
        if not users:
            return 0

        deadline = _fmt_deadline(task)
        if overdue:
            title = f"Quá hạn: {task.title}"
            message = (f"Công việc \"{task.title}\" ({task.scope_label}) đã quá hạn "
                       f"lúc {deadline} mà chưa xong. Cập nhật tiến độ hoặc báo người giao.")
        else:
            title = f"Sắp đến hạn: {task.title}"
            message = (f"Công việc \"{task.title}\" ({task.scope_label}) đến hạn lúc "
                       f"{deadline}. Đừng quên hoàn thành nhé!")
        ctx = {"title": title, "message": message,
               "details": [("Công việc", task.title), ("Thuộc", task.scope_label),
                           ("Deadline", deadline)],
               "cta_url": url, "cta_label": "Mở công việc"}
        transaction.on_commit(lambda: notify_many(
            users, NotificationKind.TASK_DUE, title, message, url=url,
            email_template="notice", context=ctx))
    return 1


def save_expense(actor, expense: Expense, is_new: bool) -> Expense:
    expense.save()
    AuditLog.write(actor, "Thêm khoản chi" if is_new else "Sửa khoản chi",
                   expense.event.name, f"{expense.title} - {expense.amount}đ")
    return expense


def delete_expense(actor, expense: Expense):
    AuditLog.write(actor, "Xoá khoản chi", expense.event.name,
                   f"{expense.title} - {expense.amount}đ")
    expense.delete()
