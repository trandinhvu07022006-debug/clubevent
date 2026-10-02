"""
M3 - Phân công công việc BTC.

Task có máy trạng thái: Chưa làm -> Đang làm -> Xong (và lùi lại được).
Đây là module làm nên ý nghĩa "hỗ trợ tổ chức" của đề tài.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from events.models import Event


class TaskStatus(models.TextChoices):
    TODO = "TODO", "Chưa làm"
    DOING = "DOING", "Đang làm"
    DONE = "DONE", "Xong"


class TaskPriority(models.TextChoices):
    LOW = "LOW", "Thấp"
    NORMAL = "NORMAL", "Bình thường"
    HIGH = "HIGH", "Cao"
    URGENT = "URGENT", "Gấp"


class Department(models.Model):
    """
    Một BAN trong CLB (Truyền thông, Hậu cần, Đối ngoại...).

    Là đơn vị TỔ CHỨC: việc có thể giao cho cả Ban (chưa chỉ định người),
    thành viên trong Ban tự "nhận việc". Trưởng ban được giao việc trong Ban
    của mình mà không cần là Trưởng BTC - đúng cách CLB thật vận hành.
    Thành viên Ban là Thành viên CHÍNH THỨC trở lên (Khách thì chưa). Nhưng
    chỉ người trong Ban tổ chức (TV BTC trở lên) mới nhận/được nhắc việc,
    vì chỉ họ vào được các trang công việc.
    """

    name = models.CharField("Tên ban", max_length=80, unique=True)
    slug = models.SlugField("Đường dẫn", max_length=80, unique=True,
                            help_text="Chữ không dấu, nối bằng gạch ngang. Vd: truyen-thong")
    description = models.CharField("Giới thiệu ngắn", max_length=255, blank=True)
    icon = models.CharField("Icon", max_length=40, default="bi-people",
                            help_text="Tên icon Bootstrap Icons, vd bi-megaphone")
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="led_departments",
                             verbose_name="Trưởng ban")
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True,
                                     related_name="departments",
                                     verbose_name="Thành viên")
    order = models.PositiveSmallIntegerField("Thứ tự hiển thị", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ban"
        verbose_name_plural = "Các ban"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("organizing:department_detail", args=[self.slug])

    def is_managed_by(self, user):
        """Trưởng BTC/Admin quản mọi Ban; Trưởng ban quản Ban của mình."""
        return user.is_authenticated and (user.is_lead or self.lead_id == user.pk)

    def has_member(self, user):
        return (self.lead_id == user.pk
                or self.members.filter(pk=user.pk).exists())


class Task(models.Model):
    """
    Một công việc giao cho 1 thành viên BTC, hoặc cho cả một Ban.

    Gắn với một sự kiện (chuẩn bị sự kiện), hoặc để trống sự kiện = VIỆC CHUNG
    của CLB do Ban chủ nhiệm giao (họp định kỳ, tuyển thành viên, quyết toán...).
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True,
                              related_name="tasks", verbose_name="Sự kiện",
                              help_text="Để trống nếu là việc chung của CLB.")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="tasks",
                                   verbose_name="Ban phụ trách",
                                   help_text="Giao cho cả Ban; để trống người "
                                             "phụ trách thì thành viên Ban tự nhận.")
    title = models.CharField("Tên công việc", max_length=200)
    description = models.TextField("Mô tả", blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL,
                                 on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="tasks_assigned",
                                 verbose_name="Người phụ trách")
    deadline = models.DateTimeField("Deadline", null=True, blank=True)
    status = models.CharField("Trạng thái", max_length=6,
                              choices=TaskStatus.choices, default=TaskStatus.TODO)
    priority = models.CharField("Mức ưu tiên", max_length=6,
                                choices=TaskPriority.choices,
                                default=TaskPriority.NORMAL)
    note = models.CharField("Ghi chú tiến độ", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="tasks_created",
                                   verbose_name="Người giao")
    created_by_ai = models.BooleanField("Do AI gợi ý", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField("Hoàn thành lúc", null=True, blank=True)
    # Nhắc hạn: đánh dấu đã gửi để lệnh định kỳ chạy lại không nhắc trùng.
    # Đổi deadline thì xoá dấu (xem save_task) để được nhắc lại theo hạn mới.
    due_reminded_at = models.DateTimeField("Đã nhắc sắp đến hạn", null=True, blank=True)
    overdue_reminded_at = models.DateTimeField("Đã báo quá hạn", null=True, blank=True)

    class Meta:
        verbose_name = "Công việc"
        verbose_name_plural = "Công việc"
        ordering = ["deadline", "id"]

    def __str__(self):
        return self.title

    @property
    def scope_label(self):
        """Tên sự kiện, hoặc 'Việc chung CLB' khi không gắn sự kiện."""
        return self.event.name if self.event_id else "Việc chung CLB"

    @property
    def is_overdue(self):
        """F3.3 - task quá hạn thì tô đỏ trên giao diện."""
        if self.status == TaskStatus.DONE or not self.deadline:
            return False
        return self.deadline < timezone.now()

    @property
    def is_done_on_time(self):
        """Dùng cho thống kê F6.3 - tỉ lệ hoàn thành đúng hạn."""
        if self.status != TaskStatus.DONE or not self.deadline or not self.done_at:
            return None
        return self.done_at <= self.deadline

    def can_be_edited_by(self, user):
        """F3.4 - người phụ trách, Trưởng ban của Ban phụ trách, hoặc Trưởng BTC."""
        if user.is_lead or self.assignee_id == user.id:
            return True
        return bool(self.department_id and self.department.lead_id == user.id)

    def can_be_claimed_by(self, user):
        """Việc giao cho Ban mà chưa có người nhận: thành viên Ban được tự nhận."""
        return (self.assignee_id is None and self.department_id is not None
                and self.status != TaskStatus.DONE and user.is_staff_btc
                and self.department.has_member(user))

    def mark(self, new_status):
        """Đổi trạng thái, tự ghi nhận thời điểm hoàn thành."""
        self.status = new_status
        self.done_at = timezone.now() if new_status == TaskStatus.DONE else None
        self.save(update_fields=["status", "done_at"])


class ExpenseCategory(models.TextChoices):
    VENUE = "VENUE", "Địa điểm"
    EQUIPMENT = "EQUIP", "Âm thanh - thiết bị"
    PRINTING = "PRINT", "In ấn - truyền thông"
    FOOD = "FOOD", "Ăn uống"
    GIFT = "GIFT", "Quà tặng"
    TRANSPORT = "TRANS", "Di chuyển"
    OTHER = "OTHER", "Khác"


class Expense(models.Model):
    """
    Ngân sách sự kiện - một khoản chi.

    Thu tính tự động từ vé đã xác nhận/đã check-in, nên chỉ cần ghi khoản
    chi. Chỉ Trưởng BTC trở lên được xem vì đây là dữ liệu tài chính.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE,
                              related_name="expenses", verbose_name="Sự kiện")
    title = models.CharField("Khoản chi", max_length=200)
    category = models.CharField("Hạng mục", max_length=6,
                                choices=ExpenseCategory.choices,
                                default=ExpenseCategory.OTHER)
    amount = models.PositiveIntegerField("Số tiền (VNĐ)")
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="expenses_paid",
                                verbose_name="Người chi")
    spent_on = models.DateField("Ngày chi", default=timezone.localdate)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    receipt = models.ImageField("Ảnh hoá đơn", upload_to="receipts/",
                                null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, related_name="+", verbose_name="Người ghi")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Khoản chi"
        verbose_name_plural = "Khoản chi"
        ordering = ["-spent_on", "-id"]

    def __str__(self):
        return f"{self.title} - {self.amount}đ"
