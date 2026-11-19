"""
M1 - Tài khoản, Trạng thái kép, Quản lý Phiên thiết bị & Kiểm toán.

Bảo tồn 100% tương thích ngược với phân hệ sự kiện & đặt vé hiện có
(`User.role`, `is_staff_btc`, `is_lead`, `is_admin_role`, `is_locked`, `AuditLog.write`),
đồng thời nâng cấp lên kiến trúc KMG Club Management Platform:
- Tách `AccountStatus` (`UNVERIFIED`, `ACTIVE`, `LOCKED`) độc lập khỏi `ClubMembershipStatus`.
- `normalized_email` (`UNIQUE NULL`) thay thế partial unique constraint để hoạt động
  chuẩn xác ở tầng CSDL trên cả MySQL 8.4 và SQLite mà không sinh cảnh báo `models.W036`.
- `authz_version` phục vụ thu hồi quyền tức thời (`INV-06`).
- `UserProfile` (PII & cờ quyền riêng tư), `UserSession` (thiết bị & đăng xuất từ xa),
  `EmailVerificationToken`, `AccountStatusHistory`.
"""
from __future__ import annotations

import re

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

_PHONE_STRIP_RE = re.compile(r"[\s\-\.\(\)]+")


def normalize_phone_number(raw: str | None) -> str | None:
    """
    Chuẩn hoá số điện thoại về dạng chữ số thống nhất để chống trùng lặp trên MySQL 8.4:
    - `+84 901 234 567` hoặc `84901234567` -> `0901234567`.
    - Số quốc tế khác (ví dụ `+1 415 555 2671`) -> `+14155552671`.
    - Chuỗi rỗng -> `None` (cho phép `UNIQUE NULL` với tài khoản chỉ đăng ký bằng Email).
    """
    if not raw:
        return None
    cleaned = _PHONE_STRIP_RE.sub("", str(raw).strip())
    if not cleaned:
        return None
    if cleaned.startswith("+84") and cleaned[3:].isdigit():
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("84") and len(cleaned) in (11, 12) and cleaned.isdigit():
        cleaned = "0" + cleaned[2:]
    return cleaned or None


def is_valid_phone_number(raw: str | None) -> bool:
    """Kiểm tra định dạng số điện thoại di động Việt Nam hoặc số quốc tế chuẩn E.164."""
    norm = normalize_phone_number(raw)
    if not norm:
        return False
    digits = norm[1:] if norm.startswith("+") else norm
    if not digits.isdigit():
        return False
    if norm.startswith("0"):
        return len(norm) in (10, 11)
    return 9 <= len(digits) <= 15


class Role(models.TextChoices):
    """Admin > Trưởng BTC > TV BTC > Thành viên > Khách."""
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


GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def canonical_email(email: str) -> str:
    """F1.8 - Dạng chuẩn của email để phát hiện nhiều tài khoản cùng một hộp thư."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


class AccountStatus(models.TextChoices):
    """Trạng thái tài khoản kỹ thuật (độc lập với tư cách thành viên CLB)."""
    UNVERIFIED = "UNVERIFIED", "Chưa xác minh OTP"
    ACTIVE = "ACTIVE", "Hoạt động"
    LOCKED = "LOCKED", "Bị khoá"


class OtpChannel(models.TextChoices):
    """Kênh nhận mã xác minh OTP 6 chữ số."""
    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "Tin nhắn SMS (SĐT)"


class User(AbstractUser):
    """Người dùng hệ thống. Hỗ trợ đăng ký & đăng nhập qua Email, Số điện thoại hoặc Username."""

    affiliation = models.CharField("Đối tượng", max_length=6,
                                   choices=Affiliation.choices, default=Affiliation.KMA)
    mssv = models.CharField("MSSV", max_length=20, unique=True, null=True, blank=True)
    school = models.CharField("Trường / đơn vị", max_length=120, blank=True)
    full_name = models.CharField("Họ tên", max_length=120, blank=True)
    display_name = models.CharField("Tên hiển thị", max_length=120, blank=True)
    phone = models.CharField("Số điện thoại", max_length=20, blank=True)
    normalized_phone = models.CharField(
        "Số điện thoại chuẩn hoá",
        max_length=24,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    normalized_email = models.CharField(
        "Email chuẩn hoá",
        max_length=254,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    email_canonical = models.CharField(
        "Email dạng chuẩn",
        max_length=254,
        blank=True,
        db_index=True,
        editable=False,
    )
    role = models.CharField(
        "Vai trò sự kiện (BTC)",
        max_length=10,
        choices=Role.choices,
        default=Role.GUEST,
    )
    account_status = models.CharField(
        "Trạng thái tài khoản",
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.UNVERIFIED,
        db_index=True,
    )
    email_verified_at = models.DateTimeField("Xác minh email lúc", null=True, blank=True)
    phone_verified_at = models.DateTimeField("Xác minh SĐT lúc", null=True, blank=True)
    authz_version = models.PositiveIntegerField("Phiên bản phân quyền", default=1)
    avatar = models.ImageField("Ảnh đại diện", upload_to="avatars/", null=True, blank=True)
    is_locked = models.BooleanField("Bị khoá", default=False)
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)

    class Meta:
        verbose_name = "Người dùng"
        verbose_name_plural = "Người dùng"

    def __str__(self):
        return f"{self.public_name} ({self.get_role_display()})"

    def _compute_normalized_email(self) -> str | None:
        cleaned = (self.email or "").strip().lower()
        return cleaned or None

    def _compute_normalized_phone(self) -> str | None:
        return normalize_phone_number(self.phone)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_set = set(update_fields)
        else:
            update_set = None

        # Chuẩn hoá mssv rỗng thành None để UNIQUE NULL trên MySQL 8.4 không xung đột chuỗi ""
        if update_set is None or "mssv" in update_set:
            if self.mssv is not None and not str(self.mssv).strip():
                self.mssv = None

        # Đồng bộ normalized_email chống trùng email không phân biệt hoa/thường trên MySQL 8.4
        if update_set is None or "email" in update_set or "normalized_email" in update_set:
            self.normalized_email = self._compute_normalized_email()
            if update_set is not None:
                update_set.add("normalized_email")

        # Đồng bộ email_canonical F1.8
        if update_set is None or "email" in update_set or "email_canonical" in update_set:
            self.email_canonical = canonical_email(self.email)
            if update_set is not None:
                update_set.add("email_canonical")

        # Đồng bộ normalized_phone chống trùng SĐT giữa các dạng 09xx / +849xx / 849xx trên MySQL 8.4
        if update_set is None or "phone" in update_set or "normalized_phone" in update_set:
            self.normalized_phone = self._compute_normalized_phone()
            if update_set is not None:
                update_set.add("normalized_phone")

        # Đồng bộ hai chiều giữa is_locked (legacy) và account_status (KMG Platform)
        if update_set is not None and "account_status" in update_set and "is_locked" not in update_set:
            self.is_locked = self.account_status == AccountStatus.LOCKED
            update_set.add("is_locked")
        elif self.is_locked:
            if self.account_status != AccountStatus.LOCKED:
                self.account_status = AccountStatus.LOCKED
                if update_set is not None:
                    update_set.add("account_status")
        else:
            if self.account_status == AccountStatus.LOCKED:
                self.account_status = (
                    AccountStatus.ACTIVE
                    if (self.email_verified_at or self.phone_verified_at)
                    else AccountStatus.UNVERIFIED
                )
                if update_set is not None:
                    update_set.add("account_status")

        if update_set is not None and ("is_locked" in update_set or "account_status" in update_set):
            self.authz_version = (self.authz_version or 1) + 1
            update_set.add("authz_version")

        if update_set is not None:
            kwargs["update_fields"] = list(update_set)
        super().save(*args, **kwargs)

    def bump_authz_version(self) -> int:
        """Tăng phiên bản phân quyền tức thời khi đổi chức vụ, ủy quyền hoặc khóa (INV-06)."""
        self.authz_version = (self.authz_version or 1) + 1
        User.objects.filter(pk=self.pk).update(authz_version=self.authz_version)
        return self.authz_version

    @property
    def public_name(self) -> str:
        return self.display_name or self.full_name or self.username

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_phone_verified(self) -> bool:
        return self.phone_verified_at is not None

    @property
    def is_otp_verified(self) -> bool:
        return bool(self.email_verified_at or self.phone_verified_at)

    @property
    def is_kma_student(self):
        return self.affiliation == Affiliation.KMA

    @property
    def is_club_member(self):
        """Thành viên CHÍNH THỨC trở lên (đã qua đợt tuyển), không phải Khách."""
        return self.role != Role.GUEST

    @property
    def needs_email_verification(self):
        """Khách chưa xác minh email thì chưa được đặt vé."""
        from django.conf import settings
        req = getattr(settings, "REQUIRE_EMAIL_OTP", True)
        return bool(req and self.role == Role.GUEST and self.email_verified_at is None)

    # --- Các hàm kiểm tra quyền BTC sự kiện hiện có & Admin Server ---
    @property
    def is_staff_btc(self):
        """Là Thành viên BTC trở lên (TV BTC, Trưởng BTC, Admin)."""
        return self.role in (Role.STAFF, Role.LEAD, Role.ADMIN) or self.is_superuser

    @property
    def is_lead(self):
        """Là Trưởng BTC trở lên."""
        return self.role in (Role.LEAD, Role.ADMIN) or self.is_superuser

    @property
    def is_admin_role(self):
        return bool(self.role == Role.ADMIN or self.is_superuser)

    @property
    def is_server_admin(self) -> bool:
        """
        Admin Server (Quản trị hệ thống cao nhất — tách biệt với Chủ nhiệm CLB).
        Chỉ Admin Server mới được nâng cấp tài khoản đã đăng ký lên Chủ nhiệm, Phó CN, Trưởng ban.
        """
        return bool(
            self.pk
            and not self.is_locked
            and self.account_status != AccountStatus.LOCKED
            and (self.is_superuser or self.role == Role.ADMIN)
        )

    # --- Các thuộc tính nhận diện tư cách trên KMG Club Platform ---
    @property
    def club_membership_record(self):
        if not self.pk:
            return None
        try:
            return self.club_membership
        except Exception:
            return None

    @property
    def club_status(self) -> str:
        """Trả về trạng thái thành viên CLB (`ACTIVE`, `SUSPENDED`, `PENDING`...) hoặc `GUEST`."""
        cm = self.club_membership_record
        return cm.status if cm else "GUEST"

    @property
    def has_active_club_access(self) -> bool:
        """
        Người dùng được mở khoá Không gian Thành viên Nội bộ KMG khi và chỉ khi:
        - Là Admin Server, HOẶC
        - Đã được Chủ nhiệm / Phó chủ nhiệm nâng role Thành viên (`ClubMembership.status == ACTIVE`)
          VÀ đã được phân vào ít nhất 01 Ban đang hoạt động (`DepartmentMembership.status == ACTIVE`), HOẶC
        - Đang giữ chức vụ lãnh đạo / cố vấn đương nhiệm hợp lệ.
        (Tài khoản mới đăng ký dù đã xác minh OTP vẫn mặc định là Khách `GUEST` -> trả `False`!).
        """
        if not self.pk or self.is_locked or self.account_status == AccountStatus.LOCKED:
            return False
        if self.is_server_admin:
            return True
        cm = self.club_membership_record
        if cm and cm.status == "SUSPENDED":
            return False
        if cm and cm.status == "ACTIVE":
            if hasattr(self, "department_memberships"):
                if self.department_memberships.filter(
                    status="ACTIVE",
                    department__is_active=True,
                ).exists():
                    return True
            else:
                return True
        if hasattr(self, "appointments"):
            now = timezone.now()
            return self.appointments.filter(
                is_active=True,
                ended_at__isnull=True,
            ).filter(
                models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=now)
            ).exists()
        return False


class UserProfile(models.Model):
    """Hồ sơ cá nhân mở rộng & kiểm soát quyền riêng tư PII (Data Privacy)."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Người dùng",
    )
    stage_name = models.CharField("Nghệ danh sân khấu", max_length=80, blank=True)
    bio = models.TextField("Giới thiệu bản thân", max_length=1000, blank=True)
    faculty = models.CharField("Khoa / Viện", max_length=120, blank=True)
    cohort = models.CharField("Khoá / Niên khoá", max_length=40, blank=True)
    date_of_birth = models.DateField("Ngày sinh", null=True, blank=True)
    social_url = models.URLField("Liên kết mạng xã hội / Portfolio", blank=True)

    # Cờ quyền riêng tư: không cho phép thành viên/cán bộ chéo ban tự ý khai thác PII
    privacy_show_phone = models.BooleanField("Cho thành viên CLB xem SĐT", default=False)
    privacy_show_email = models.BooleanField("Cho thành viên CLB xem Email", default=True)
    privacy_show_dob = models.BooleanField("Cho thành viên CLB xem Ngày sinh", default=False)
    updated_at = models.DateTimeField("Cập nhật lúc", auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ mở rộng"
        verbose_name_plural = "Hồ sơ mở rộng"

    def __str__(self):
        return f"Hồ sơ {self.user.public_name}"


class UserSession(models.Model):
    """Quản lý phiên đăng nhập theo thiết bị & hỗ trợ đăng xuất từ xa."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="device_sessions",
        verbose_name="Người dùng",
    )
    session_key = models.CharField("Khoá phiên", max_length=64, db_index=True)
    device_label = models.CharField("Thiết bị / Trình duyệt", max_length=160, blank=True)
    ip_address = models.CharField("Địa chỉ IP", max_length=64, blank=True)
    user_agent = models.CharField("User-Agent", max_length=255, blank=True)
    created_at = models.DateTimeField("Đăng nhập lúc", auto_now_add=True)
    last_seen_at = models.DateTimeField("Hoạt động cuối", default=timezone.now)
    revoked_at = models.DateTimeField("Thu hồi lúc", null=True, blank=True)
    revoked_reason = models.CharField("Lý do thu hồi", max_length=160, blank=True)

    class Meta:
        verbose_name = "Phiên thiết bị"
        verbose_name_plural = "Phiên thiết bị"
        ordering = ["-last_seen_at", "-id"]
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
        ]

    @property
    def is_active_session(self) -> bool:
        return self.revoked_at is None

    def __str__(self):
        state = "Đang hoạt động" if self.is_active_session else "Đã thu hồi"
        return f"{self.user.username} - {self.device_label or 'Thiết bị'} ({state})"


class EmailVerificationToken(models.Model):
    """Mã xác minh địa chỉ email có thời hạn và chỉ dùng một lần."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="verification_tokens",
        verbose_name="Người dùng",
    )
    email = models.EmailField("Email xác minh")
    token_hash = models.CharField("Mã băm token", max_length=64, unique=True)
    expires_at = models.DateTimeField("Hết hạn lúc")
    used_at = models.DateTimeField("Đã xác minh lúc", null=True, blank=True)
    created_at = models.DateTimeField("Tạo lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Token xác minh email"
        verbose_name_plural = "Token xác minh email"
        ordering = ["-created_at"]

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at >= timezone.now()


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
        from django.conf import settings
        ttl = getattr(settings, "OTP_TTL_MINUTES", 10)
        return timezone.now() > self.created_at + timezone.timedelta(minutes=ttl)


class OTPVerificationChallenge(models.Model):
    """
    Mã xác minh OTP 6 chữ số qua Email hoặc SMS:
    - Chỉ lưu mã băm HMAC-SHA256 (`code_hash`), tuyệt đối không lưu mã OTP thô.
    - Giới hạn số lần nhập sai (`attempts` / `max_attempts`) chống brute-force 6 chữ số.
    - Xác minh thành công chỉ kích hoạt tài khoản kỹ thuật (`AccountStatus.ACTIVE`),
      giữ nguyên chế độ mặc định là Khách (`club_status == 'GUEST'`) cho đến khi
      được Chủ nhiệm / Phó chủ nhiệm nâng role & phân Ban (hoặc Admin Server bổ nhiệm lãnh đạo).
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="otp_challenges",
        verbose_name="Người dùng",
    )
    channel = models.CharField(
        "Kênh nhận OTP",
        max_length=10,
        choices=OtpChannel.choices,
        db_index=True,
    )
    destination = models.CharField("Đích nhận (Email/SĐT)", max_length=254)
    code_hash = models.CharField("Mã băm OTP (HMAC-SHA256)", max_length=64)
    attempts = models.PositiveSmallIntegerField("Số lần nhập sai", default=0)
    max_attempts = models.PositiveSmallIntegerField("Số lần thử tối đa", default=5)
    expires_at = models.DateTimeField("Hết hạn lúc")
    used_at = models.DateTimeField("Đã sử dụng lúc", null=True, blank=True)
    invalidated_at = models.DateTimeField("Đã vô hiệu hoá lúc", null=True, blank=True)
    created_at = models.DateTimeField("Tạo lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Mã xác minh OTP"
        verbose_name_plural = "Mã xác minh OTP"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "channel", "used_at"]),
        ]

    @property
    def is_usable(self) -> bool:
        return (
            self.used_at is None
            and self.invalidated_at is None
            and self.attempts < self.max_attempts
            and self.expires_at >= timezone.now()
        )

    def __str__(self) -> str:
        return f"OTP[{self.channel}] -> {self.destination} ({self.user.username})"


class AccountStatusHistory(models.Model):
    """Lịch sử thay đổi trạng thái tài khoản kỹ thuật (bất biến)."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Người dùng",
    )
    old_status = models.CharField("Trạng thái cũ", max_length=16, blank=True)
    new_status = models.CharField("Trạng thái mới", max_length=16)
    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Người thực hiện",
    )
    reason = models.CharField("Lý do", max_length=255, blank=True)
    created_at = models.DateTimeField("Thời gian", auto_now_add=True)

    class Meta:
        verbose_name = "Lịch sử trạng thái tài khoản"
        verbose_name_plural = "Lịch sử trạng thái tài khoản"
        ordering = ["-created_at", "-id"]


class AuditLog(models.Model):
    """
    F0.2 - Nhật ký thao tác quản trị & kiểm toán bảo mật.

    Giữ nguyên chữ ký `AuditLog.write(user, action, target="", note="")` cho toàn bộ
    hệ thống sự kiện cũ, đồng thời bổ sung `ip_address` và `metadata` JSON cho
    các quy trình quản trị CLB.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Người thực hiện",
    )
    action = models.CharField("Hành động", max_length=80, db_index=True)
    target = models.CharField("Đối tượng", max_length=200, blank=True)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    ip_address = models.CharField("Địa chỉ IP", max_length=64, blank=True)
    metadata = models.JSONField("Chi tiết kiểm toán", default=dict, blank=True)
    created_at = models.DateTimeField("Thời gian", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Nhật ký thao tác"
        verbose_name_plural = "Nhật ký thao tác"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"[{self.created_at:%d/%m %H:%M}] {self.user} - {self.action}"

    @classmethod
    def write(cls, user, action, target="", note="", ip_address="", metadata=None):
        """Hàm tiện dụng để ghi nhật ký kiểm toán từ bất kỳ service nào."""
        actor = user if getattr(user, "is_authenticated", False) else None
        return cls.objects.create(
            user=actor,
            action=str(action)[:80],
            target=str(target)[:200],
            note=str(note)[:255],
            ip_address=str(ip_address or "")[:64],
            metadata=metadata or {},
        )
