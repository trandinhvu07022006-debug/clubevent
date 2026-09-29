"""
M2 - Quản lý sự kiện.

Event có máy trạng thái hữu hạn (FSM):
    Đang chuẩn bị -> Mở đăng ký -> Đóng đăng ký -> Đã diễn ra
    và bất kỳ trạng thái nào (trừ Đã diễn ra) -> Đã huỷ
Xem state diagram trong docs/.
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class EventStatus(models.TextChoices):
    DRAFT = "DRAFT", "Đang chuẩn bị"
    OPEN = "OPEN", "Mở đăng ký"
    CLOSED = "CLOSED", "Đóng đăng ký"
    DONE = "DONE", "Đã diễn ra"
    CANCELLED = "CANCELLED", "Đã huỷ"


# Bảng chuyển trạng thái hợp lệ. Mọi thay đổi trạng thái đều phải đi qua đây
# để không có trường hợp nhảy trạng thái sai (ví dụ Đã huỷ -> Mở đăng ký).
ALLOWED_TRANSITIONS = {
    EventStatus.DRAFT: [EventStatus.OPEN, EventStatus.CANCELLED],
    EventStatus.OPEN: [EventStatus.CLOSED, EventStatus.CANCELLED],
    EventStatus.CLOSED: [EventStatus.DONE, EventStatus.OPEN, EventStatus.CANCELLED],
    EventStatus.DONE: [],
    EventStatus.CANCELLED: [],
}


class Event(models.Model):
    """Một sự kiện của CLB."""

    name = models.CharField("Tên sự kiện", max_length=200)
    description = models.TextField("Mô tả", blank=True)
    location = models.CharField("Địa điểm", max_length=200)
    starts_at = models.DateTimeField("Thời gian diễn ra")
    register_deadline = models.DateTimeField("Hạn đăng ký")
    capacity = models.PositiveIntegerField("Sức chứa", default=100)
    cover = models.ImageField("Ảnh bìa", upload_to="events/", null=True, blank=True)
    status = models.CharField("Trạng thái", max_length=10,
                              choices=EventStatus.choices, default=EventStatus.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True,
                                   related_name="events_created",
                                   verbose_name="Người tạo")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sự kiện"
        verbose_name_plural = "Sự kiện"
        ordering = ["-starts_at"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:detail", args=[self.pk])

    # --- Máy trạng thái ---
    def can_change_to(self, new_status):
        """Kiểm tra chuyển trạng thái có hợp lệ không."""
        return new_status in ALLOWED_TRANSITIONS.get(self.status, [])

    def next_statuses(self):
        """Các trạng thái có thể chuyển tới, dùng để render nút trên giao diện."""
        return [(s, EventStatus(s).label) for s in ALLOWED_TRANSITIONS.get(self.status, [])]

    # --- Thuộc tính suy diễn ---
    @property
    def is_registerable(self):
        """F4.1 - chỉ đăng ký được khi đang Mở đăng ký và chưa quá hạn."""
        return (self.status == EventStatus.OPEN
                and timezone.now() <= self.register_deadline)

    @property
    def is_past(self):
        return self.starts_at < timezone.now()

    @property
    def total_quota(self):
        """Tổng số vé của mọi loại vé."""
        return sum(t.quota for t in self.ticket_types.all())

    @property
    def total_sold(self):
        return sum(t.sold for t in self.ticket_types.all())

    @property
    def seats_left(self):
        return max(self.total_quota - self.total_sold, 0)

    @property
    def task_progress(self):
        """F3.5 - % công việc BTC đã xong, dùng cho thanh tiến độ."""
        tasks = self.tasks.all()
        if not tasks:
            return 0
        done = sum(1 for t in tasks if t.status == "DONE")
        return round(done * 100 / len(tasks))


class TicketType(models.Model):
    """
    F2.2 - Loại vé của một sự kiện. Giá 0 nghĩa là vé miễn phí.

    Cột `sold` lưu sẵn số vé đã bán thay vì COUNT bảng ticket mỗi lần.
    Nhờ vậy khi đặt vé chỉ cần khoá 1 dòng này (SELECT ... FOR UPDATE) là
    chặn được race condition.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE,
                              related_name="ticket_types", verbose_name="Sự kiện")
    name = models.CharField("Tên loại vé", max_length=100)
    price = models.PositiveIntegerField("Giá (VNĐ)", default=0)
    quota = models.PositiveIntegerField("Số lượng", default=50)
    sold = models.PositiveIntegerField("Đã bán", default=0)

    class Meta:
        verbose_name = "Loại vé"
        verbose_name_plural = "Loại vé"
        ordering = ["price", "id"]

    def __str__(self):
        return f"{self.name} - {self.event.name}"

    @property
    def is_free(self):
        return self.price == 0

    @property
    def remaining(self):
        return max(self.quota - self.sold, 0)

    @property
    def is_sold_out(self):
        return self.remaining == 0
