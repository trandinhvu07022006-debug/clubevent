"""
M4 + M5 - Đăng ký tham gia / vé và Check-in.

Máy trạng thái của vé:
    Chờ thanh toán -> Đã xác nhận -> Đã check-in
    Chờ thanh toán / Đã xác nhận -> Đã huỷ
Vé miễn phí được Đã xác nhận ngay khi đăng ký.
"""
import secrets
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


# Bỏ các ký tự dễ nhầm khi đọc/gõ: 0/O, 1/I/L
BOOKING_REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def make_booking_ref():
    """
    F4.7 - Mã giao dịch cho MỘT lần đặt (có thể gồm tới 4 vé).

    Người dùng chuyển khoản một lần cho cả nhóm vé, nội dung CK ngân hàng
    chỉ ~25 ký tự không dấu nên không nhét nổi 4 mã vé 12 ký tự. Mã 8 ký tự
    gom cả nhóm lại: nội dung CK là "KMG <mã>".
    """
    return "".join(secrets.choice(BOOKING_REF_ALPHABET) for _ in range(8))


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
    booking_ref = models.CharField("Mã giao dịch", max_length=8, blank=True,
                                   db_index=True)
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


class WaitlistStatus(models.TextChoices):
    WAITING = "WAITING", "Đang chờ"
    PROMOTED = "PROMOTED", "Đã có vé"
    SKIPPED = "SKIPPED", "Bỏ qua"          # tới lượt nhưng không đủ điều kiện
    CANCELLED = "CANCELLED", "Đã rời"
    EXPIRED = "EXPIRED", "Hết hạn"         # sự kiện kết thúc/đóng mà chưa tới lượt


class WaitlistEntry(models.Model):
    """
    F4.8 - Một lượt chờ = 1 vé.

    Không dùng UniqueConstraint(condition=...) để chặn chờ trùng vì MySQL bỏ
    qua loại ràng buộc này. Việc chặn làm ở service, dưới khoá dòng TicketType.
    """

    ticket_type = models.ForeignKey(TicketType, on_delete=models.CASCADE,
                                    related_name="waitlist", verbose_name="Loại vé")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="waitlist_entries", verbose_name="Người chờ")
    status = models.CharField("Trạng thái", max_length=10,
                              choices=WaitlistStatus.choices,
                              default=WaitlistStatus.WAITING)
    ticket = models.OneToOneField(Ticket, on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name="waitlist_entry",
                                  verbose_name="Vé được cấp")
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField("Vào hàng lúc", auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField("Kết thúc lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Lượt chờ"
        verbose_name_plural = "Danh sách chờ"
        ordering = ["created_at", "id"]   # id phá thế hoà khi created_at trùng

    def __str__(self):
        return f"{self.user} chờ {self.ticket_type}"

    @property
    def position(self):
        """Vị trí hiện tại trong hàng (1 = đầu hàng). Chỉ có nghĩa khi WAITING."""
        if self.status != WaitlistStatus.WAITING:
            return None
        ahead = WaitlistEntry.objects.filter(
            ticket_type_id=self.ticket_type_id, status=WaitlistStatus.WAITING,
        ).filter(
            models.Q(created_at__lt=self.created_at)
            | models.Q(created_at=self.created_at, id__lt=self.id)
        ).count()
        return ahead + 1


class TicketTransfer(models.Model):
    """
    F4.10 - Lịch sử chuyển nhượng vé.

    Mỗi lần chuyển, vé được cấp MÃ MỚI: ảnh QR cũ người bán đã gửi đi không
    còn dùng được. Giữ lại mã cũ để quầy check-in báo đúng lý do khi có
    người mang mã cũ tới.
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE,
                               related_name="transfers", verbose_name="Vé")
    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="tickets_given", verbose_name="Người chuyển")
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="tickets_received", verbose_name="Người nhận")
    old_code = models.CharField("Mã vé cũ", max_length=12, db_index=True)
    created_at = models.DateTimeField("Chuyển lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Chuyển nhượng vé"
        verbose_name_plural = "Chuyển nhượng vé"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.old_code}: {self.from_user} -> {self.to_user}"
