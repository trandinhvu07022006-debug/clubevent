"""
M4 + M5 - Đăng ký tham gia / vé và Check-in.

Máy trạng thái của vé:
    Chờ thanh toán -> Đã xác nhận -> Đã check-in
    Chờ thanh toán / Đã xác nhận -> Đã huỷ
Vé miễn phí được Đã xác nhận ngay khi đăng ký.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from events.models import Event, TicketType


class TicketStatus(models.TextChoices):
    PENDING = "PENDING", "Chờ thanh toán"
    CONFIRMED = "CONFIRMED", "Đã xác nhận"
    CHECKED_IN = "CHECKED_IN", "Đã check-in"
    CANCELLED = "CANCELLED", "Đã huỷ"


def make_ticket_code():
    """
    F4.2 - Mã vé ngẫu nhiên, KHÔNG dùng ID tăng dần.

    Nếu dùng ID tăng dần thì ai cũng đoán được mã vé của người khác rồi
    check-in hộ. UUID4 có 122 bit ngẫu nhiên nên không đoán được.
    Lấy 12 ký tự hoa cho dễ đọc và dễ nhập tay khi quét QR lỗi.
    """
    return uuid.uuid4().hex[:12].upper()


class Ticket(models.Model):
    """Một vé / một suất đăng ký tham gia."""

    code = models.CharField("Mã vé", max_length=12, unique=True,
                            default=make_ticket_code, db_index=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE,
                              related_name="tickets", verbose_name="Sự kiện")
    ticket_type = models.ForeignKey(TicketType, on_delete=models.PROTECT,
                                    related_name="tickets", verbose_name="Loại vé")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="tickets", verbose_name="Người đăng ký")
    status = models.CharField("Trạng thái", max_length=11,
                              choices=TicketStatus.choices,
                              default=TicketStatus.PENDING)
    price = models.PositiveIntegerField("Giá lúc đặt (VNĐ)", default=0)
    created_at = models.DateTimeField("Ngày đặt", auto_now_add=True)
    confirmed_at = models.DateTimeField("Xác nhận lúc", null=True, blank=True)
    checked_in_at = models.DateTimeField("Check-in lúc", null=True, blank=True)
    checked_in_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                      on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="checkins_done",
                                      verbose_name="Người check-in")

    class Meta:
        verbose_name = "Vé"
        verbose_name_plural = "Vé"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["event", "status"])]

    def __str__(self):
        return f"{self.code} - {self.user} - {self.event}"

    # --- Thuộc tính suy diễn ---
    @property
    def is_active(self):
        """Vé còn hiệu lực, tức là đang chiếm 1 chỗ."""
        return self.status in (TicketStatus.PENDING, TicketStatus.CONFIRMED,
                              TicketStatus.CHECKED_IN)

    @property
    def payment_deadline(self):
        """F4.5 - hạn thanh toán, 24h sau khi đặt. Không vượt quá giờ diễn ra."""
        if self.status != TicketStatus.PENDING:
            return None
        return min(
            self.created_at + timezone.timedelta(hours=settings.PAYMENT_DEADLINE_HOURS),
            self.event.starts_at
        )

    @property
    def is_payment_expired(self):
        deadline = self.payment_deadline
        return bool(deadline and timezone.now() > deadline)

    @property
    def can_cancel(self):
        """F4.3 - huỷ được nếu chưa check-in và còn hơn 24h tới giờ diễn ra."""
        if self.status not in (TicketStatus.PENDING, TicketStatus.CONFIRMED):
            return False
        limit = self.event.starts_at - timezone.timedelta(
            hours=settings.CANCEL_BEFORE_HOURS)
        return timezone.now() < limit
