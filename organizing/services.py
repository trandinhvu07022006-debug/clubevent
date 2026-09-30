"""Tầng SERVICE cho M3 - Công việc BTC và ngân sách sự kiện."""
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog
from notifications.models import NotificationKind
from notifications.services import notify_on_commit

from .models import Expense, Task


@transaction.atomic
def save_task(actor, task: Task, old_assignee_id=None) -> Task:
    """
    Lưu công việc và F7.1 - báo cho người được giao.

    Chỉ báo khi người phụ trách THỰC SỰ đổi (so với giá trị cũ), không báo
    khi chỉ sửa mô tả; và không báo nếu người giao tự giao cho chính mình.
    """
    task.save()
    new_id = task.assignee_id
    if new_id and new_id != old_assignee_id and new_id != actor.pk:
        deadline = (timezone.localtime(task.deadline).strftime("%H:%M %d/%m/%Y")
                    if task.deadline else "Chưa đặt")
        title = f"Việc mới: {task.title}"
        scope = f"của sự kiện {task.event.name}" if task.event_id else "(việc chung của CLB)"
        urgent = " [GẤP]" if task.priority == "URGENT" else ""
        message = (f"{actor.full_name or actor.username} giao cho bạn công việc "
                   f"\"{task.title}\"{urgent} {scope}. Deadline: {deadline}.")
        url = reverse("organizing:my_tasks")
        notify_on_commit(
            task.assignee, NotificationKind.TASK_ASSIGNED, title, message,
            url=url, email_template="notice",
            context={"title": title, "message": message,
                     "details": [("Công việc", task.title),
                                 ("Thuộc", task.scope_label),
                                 ("Mức ưu tiên", task.get_priority_display()),
                                 ("Người giao", actor.full_name or actor.username),
                                 ("Deadline", deadline)],
                     "note": task.description[:300] if task.description else "",
                     "cta_url": url, "cta_label": "Mở việc của tôi"})
    return task


def save_expense(actor, expense: Expense, is_new: bool) -> Expense:
    expense.save()
    AuditLog.write(actor, "Thêm khoản chi" if is_new else "Sửa khoản chi",
                   expense.event.name, f"{expense.title} - {expense.amount}đ")
    return expense


def delete_expense(actor, expense: Expense):
    AuditLog.write(actor, "Xoá khoản chi", expense.event.name,
                   f"{expense.title} - {expense.amount}đ")
    expense.delete()
