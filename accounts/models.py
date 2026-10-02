"""
M1 - Tài khoản & phân quyền.

Dùng custom user model thay cho User mặc định của Django để thêm MSSV và
role. Phải khai báo AUTH_USER_MODEL ngay từ đầu dự án, đổi về sau rất mệt.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    """
    Admin > Trưởng BTC > TV BTC > Thành viên > Khách.

    KHÁCH: ai cũng tự tạo tài khoản online được - để đặt vé, xem sự kiện.
    THÀNH VIÊN chính thức chỉ có qua ĐỢT TUYỂN (app recruitment): nộp đơn,
    casting/phỏng vấn, được nhận mới lên Thành viên và vào Ban. Nhờ vậy danh
    sách thành viên không bị "loãng" bởi người chỉ đăng ký để mua vé.
    """
    GUEST = "GUEST", "Khách"
    MEMBER = "MEMBER", "Thành viên"
    STAFF = "STAFF", "Thành viên BTC"
    LEAD = "LEAD", "Trưởng BTC"
    ADMIN = "ADMIN", "Admin"


class Affiliation(models.TextChoices):
    """
    Người dùng là ai. Show của CLB mở cho cả người ngoài (sinh viên trường
    khác, người đi làm, phụ huynh...), nên MSSV KHÔNG bắt buộc với mọi người:
    chỉ sinh viên Học viện mới phải khai MSSV.
    """
    KMA = "KMA", "Sinh viên Học viện Kỹ thuật Mật mã"
    OTHER_SCHOOL = "OTHER", "Sinh viên trường khác"
    PUBLIC = "PUBLIC", "Không phải sinh viên"


# Gmail coi các tên miền này là một, và bỏ qua dấu chấm trong phần tên
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def canonical_email(email: str) -> str:
    """
    F1.8 - Dạng chuẩn của email để phát hiện nhiều tài khoản cùng một hộp thư.

    Gmail (và đa số nhà cung cấp) giao thư cho "abc+1@x" và "abc+2@x" vào cùng
    hộp "abc@x"; riêng Gmail còn bỏ qua dấu chấm: "a.b.c@gmail.com" = "abc@gmail.com".
    Không chuẩn hoá thì một người dùng một hộp thư tạo được vô số tài khoản,
    xác minh OTP cũng không chặn được việc gom vé.
    Chỉ dùng để so trùng; email thật của user vẫn giữ nguyên để gửi thư.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


class User(AbstractUser):
    """Người dùng hệ thống. Đăng nhập bằng username, hiển thị theo họ tên."""

    affiliation = models.CharField("Đối tượng", max_length=6,
                                   choices=Affiliation.choices, default=Affiliation.KMA)
    # Để trống thì lưu NULL, KHÔNG lưu "": cột unique cho phép nhiều NULL
    # nhưng chỉ một chuỗi rỗng -> người thứ hai bỏ trống sẽ bị báo trùng.
    mssv = models.CharField("MSSV", max_length=20, unique=True, null=True, blank=True)
    school = models.CharField("Trường / đơn vị", max_length=120, blank=True)
    full_name = models.CharField("Họ tên", max_length=120, blank=True)
    phone = models.CharField("Số điện thoại", max_length=20, blank=True)
    role = models.CharField("Vai trò", max_length=10,
                            choices=Role.choices, default=Role.GUEST)
    avatar = models.ImageField("Ảnh đại diện", upload_to="avatars/",
                               null=True, blank=True)
    is_locked = models.BooleanField("Bị khoá", default=False)
    email_verified_at = models.DateTimeField("Xác minh email lúc", null=True, blank=True)
    email_canonical = models.CharField("Email dạng chuẩn", max_length=254,
                                       blank=True, db_index=True, editable=False)
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)

    class Meta:
        verbose_name = "Người dùng"
        verbose_name_plural = "Người dùng"
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("email"),
                name="uniq_user_email_ci",
                condition=~models.Q(email="")
            )
        ]

    def __str__(self):
        return f"{self.full_name or self.username} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        # Tự cập nhật ở mọi nơi tạo/sửa user (form, admin, seed_demo...)
        self.email_canonical = canonical_email(self.email)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "email" in update_fields:
            kwargs["update_fields"] = {*update_fields, "email_canonical"}
        super().save(*args, **kwargs)

    # --- Các hàm kiểm tra quyền, dùng chung cho view và template ---
    @property
    def is_kma_student(self):
        return self.affiliation == Affiliation.KMA

    @property
    def is_club_member(self):
        """Thành viên CHÍNH THỨC trở lên (đã qua đợt tuyển), không phải Khách."""
        return self.role != Role.GUEST

    @property
    def is_staff_btc(self):
        """Là Thành viên BTC trở lên (TV BTC, Trưởng BTC, Admin)."""
        return self.role in (Role.STAFF, Role.LEAD, Role.ADMIN)

    @property
    def is_lead(self):
        """Là Trưởng BTC trở lên."""
        return self.role in (Role.LEAD, Role.ADMIN)

    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN

    @property
    def needs_email_verification(self):
        """
        F1.7 - Khách chưa xác minh email thì chưa được đặt vé. Thành viên trở
        lên đã qua đợt tuyển (biết rõ là ai) nên không cần.
        """
        return (settings.REQUIRE_EMAIL_OTP and self.role == Role.GUEST
                and self.email_verified_at is None)


class EmailOTP(models.Model):
    """
    F1.7 - Mã OTP 6 số gửi qua email để xác minh tài khoản Khách.

    Chỉ lưu bản băm của mã (giống mật khẩu): lộ CSDL cũng không đọc được mã
    đang còn hạn. Mỗi lần gửi mã mới thì các mã cũ của user bị vô hiệu.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="email_otps", verbose_name="Người dùng")
    code_hash = models.CharField("Mã (đã băm)", max_length=64)
    attempts = models.PositiveSmallIntegerField("Số lần nhập sai", default=0)
    created_at = models.DateTimeField("Gửi lúc", auto_now_add=True, db_index=True)
    used_at = models.DateTimeField("Dùng lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Mã OTP email"
        verbose_name_plural = "Mã OTP email"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"OTP {self.user} {self.created_at:%d/%m %H:%M}"

    @property
    def is_expired(self):
        return timezone.now() > self.created_at + timezone.timedelta(
            minutes=settings.OTP_TTL_MINUTES)


class AuditLog(models.Model):
    """
    F0.2 - Nhật ký thao tác.

    Ghi lại các hành động quan trọng: gán role, huỷ sự kiện, xác nhận thanh
    toán, check-in. Dùng để truy vết khi có tranh chấp.
    """
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                            verbose_name="Người thực hiện")
    action = models.CharField("Hành động", max_length=60)
    target = models.CharField("Đối tượng", max_length=200, blank=True)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField("Thời gian", auto_now_add=True)

    class Meta:
        verbose_name = "Nhật ký thao tác"
        verbose_name_plural = "Nhật ký thao tác"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%d/%m %H:%M}] {self.user} - {self.action}"

    @classmethod
    def write(cls, user, action, target="", note=""):
        """Hàm tiện dụng để ghi log từ bất kỳ service nào."""
        return cls.objects.create(user=user, action=action,
                                  target=str(target)[:200], note=note[:255])
