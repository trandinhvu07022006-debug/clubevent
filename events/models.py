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


# Sự kiện không ghi giờ kết thúc thì coi như kéo dài 2 tiếng
DEFAULT_EVENT_HOURS = 2


class EventStatus(models.TextChoices):
    DRAFT = "DRAFT", "Đang chuẩn bị"
    OPEN = "OPEN", "Mở đăng ký"
    CLOSED = "CLOSED", "Đóng đăng ký"
    DONE = "DONE", "Đã diễn ra"
    CANCELLED = "CANCELLED", "Đã huỷ"


class EventCategory(models.TextChoices):
    """
    F2.5 - Danh mục sự kiện.

    Dùng TextChoices thay vì bảng riêng: CLB rất ít khi thêm danh mục, bảng
    riêng kéo theo CRUD và phân quyền không cần thiết.
    """
    MUSIC = "MUSIC", "Âm nhạc"
    ACADEMIC = "ACADEMIC", "Học thuật"
    VOLUNTEER = "VOLUNTEER", "Thiện nguyện"
    SPORT = "SPORT", "Thể thao"
    SOCIAL = "SOCIAL", "Giao lưu"
    OTHER = "OTHER", "Khác"


# Icon Bootstrap cho từng danh mục, dùng ở bộ lọc và thẻ sự kiện
CATEGORY_ICONS = {
    EventCategory.MUSIC: "bi-music-note-beamed",
    EventCategory.ACADEMIC: "bi-mortarboard",
    EventCategory.VOLUNTEER: "bi-heart",
    EventCategory.SPORT: "bi-trophy",
    EventCategory.SOCIAL: "bi-people",
    EventCategory.OTHER: "bi-stars",
}


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
    category = models.CharField("Danh mục", max_length=10,
                                choices=EventCategory.choices,
                                default=EventCategory.OTHER, db_index=True)
    starts_at = models.DateTimeField("Thời gian diễn ra")
    # B4 - giờ kết thúc, cần cho file lịch .ics và tính "đang diễn ra".
    # Để trống thì coi như sự kiện kéo dài DEFAULT_EVENT_HOURS giờ.
    ends_at = models.DateTimeField("Thời gian kết thúc", null=True, blank=True)
    register_deadline = models.DateTimeField("Hạn đăng ký")
    capacity = models.PositiveIntegerField("Sức chứa", default=100)
    budget = models.PositiveIntegerField("Ngân sách dự kiến (VNĐ)", default=0,
                                         help_text="Để 0 nếu chưa lập ngân sách.")
    cover = models.ImageField("Ảnh bìa", upload_to="events/", null=True, blank=True)
    status = models.CharField("Trạng thái", max_length=10,
                              choices=EventStatus.choices, default=EventStatus.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True,
                                   related_name="events_created",
                                   verbose_name="Người tạo")
    # F7.2 - đánh dấu đã gửi nhắc lịch, chặn gửi trùng khi lệnh chạy lại
    reminder_sent_at = models.DateTimeField("Đã nhắc lịch lúc", null=True, blank=True)
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
    def category_icon(self):
        return CATEGORY_ICONS.get(self.category, "bi-stars")

    @property
    def effective_ends_at(self):
        """Giờ kết thúc thực tế: ends_at, hoặc mặc định sau giờ bắt đầu 2 tiếng."""
        return self.ends_at or (self.starts_at + timezone.timedelta(
            hours=DEFAULT_EVENT_HOURS))

    @property
    def is_happening(self):
        """Đang diễn ra: đã tới giờ bắt đầu nhưng chưa tới giờ kết thúc."""
        now = timezone.now()
        return (self.status not in (EventStatus.CANCELLED, EventStatus.DRAFT)
                and self.starts_at <= now < self.effective_ends_at)

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
