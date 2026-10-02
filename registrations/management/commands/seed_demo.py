"""
Nạp dữ liệu mẫu cho buổi demo.

Chạy:  python manage.py seed_demo
Xoá hết rồi nạp lại:  python manage.py seed_demo --reset

Dữ liệu được thiết kế để demo đúng kịch bản trong báo cáo:
  - Sự kiện A: đang mở bán, còn nhiều chỗ -> demo đặt vé bình thường
  - Sự kiện B: CHỈ CÒN 1 CHỖ -> demo hết chỗ và race condition
  - Sự kiện C: đã diễn ra, có vé + check-in + phản hồi -> demo thống kê
             + giấy chứng nhận (tài khoản thanhvien đã check-in)
  - Sự kiện D: HẾT VÉ, có sẵn danh sách chờ -> demo F4.8
Kèm: khoản chi (ngân sách), thông báo mẫu, mã giao dịch nhóm.
"""
import random

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventCategory, EventStatus, TicketType
from feedback.models import Feedback
from notifications.models import Notification, NotificationKind
from organizing.models import Department, Expense, Task, TaskStatus
from pages.models import ClubOfficer
from recruitment.models import Application, RecruitmentRound
from registrations.models import (Ticket, TicketStatus, WaitlistEntry,
                                  make_booking_ref)

PASSWORD = "demo1234"

# Tài khoản demo, mỗi vai trò ít nhất một cái. Ban Quản trị nhiệm kỳ
# 2026 - 2027 dùng tên thật để trang Giới thiệu khớp với tài khoản:
#   admin = Chủ nhiệm, truongbtc = Phó chủ nhiệm,
#   btc1 = Trưởng ban Chuyên môn, btc2 = Trưởng ban Truyền thông & Sự kiện.
# (MSSV là số giả, chỉ để demo.)
ACCOUNTS = [
    ("admin", "Trần Nhật Hoàng", "AT000001", Role.ADMIN),
    ("truongbtc", "Trần Đình Vũ", "AT180001", Role.LEAD),
    ("btc1", "Lưu Nhật Linh", "AT180002", Role.STAFF),
    ("btc2", "Phan Tiến Đạt", "AT180003", Role.STAFF),
    ("thanhvien", "Hoàng Thị Mai", "AT190001", Role.MEMBER),
    ("thanhvien2", "Đỗ Văn Nam", "AT190002", Role.MEMBER),
    ("khach", "Phan Gia Huy", "AT210001", Role.GUEST),
]

# Đơn ứng tuyển mẫu: (username, họ tên, MSSV, Ban, thế mạnh, trình độ, trạng thái)
APPLICANTS = [
    ("khach", None, None, "chuyen-mon", "Guitar đệm hát", "BASIC", "PENDING"),
    ("ungvien1", "Ngô Bảo Châu", "AT210002", "chuyen-mon", "Vocal, piano cơ bản",
     "GOOD", "INTERVIEW"),
    ("ungvien2", "Đặng Thu Hà", "AT210003", "truyen-thong-su-kien",
     "Thiết kế poster, chụp ảnh", "STAGE", "PENDING"),
    ("ungvien3", "Vũ Minh Khang", "AT210004", "truyen-thong-su-kien",
     "Dẫn chương trình, viết bài", "NEW", "PENDING"),
]

# Tên thật cho 35 thành viên mẫu (username vẫn là sv00..sv34) để các bảng
# danh sách dễ phân biệt hơn "Sinh viên 01..35".
MEMBER_NAMES = [
    "Nguyễn Minh Anh", "Trần Quốc Bảo", "Lê Thu Trang", "Phạm Đức Huy",
    "Vũ Ngọc Lan", "Đặng Hoàng Long", "Bùi Khánh Linh", "Đỗ Tuấn Kiệt",
    "Hồ Phương Thảo", "Ngô Gia Hân", "Dương Văn Khoa", "Lý Thanh Tâm",
    "Mai Anh Tuấn", "Phan Thị Hồng", "Trịnh Công Sơn", "Đinh Bảo Ngọc",
    "Lương Minh Đức", "Tạ Thu Hà", "Võ Nhật Nam", "Cao Mỹ Duyên",
    "Hà Quang Vinh", "Chu Thị Yến", "Kiều Đức Thịnh", "Lâm Hải Yến",
    "Tô Minh Châu", "Quách Gia Bảo", "Thái Hữu Phúc", "Viên Thảo Vy",
    "Nguyễn Hữu Đạt", "Trần Thị Mơ", "Lê Hoàng Phúc", "Phạm Thanh Bình",
    "Vũ Hải Đăng", "Đoàn Kim Ngân", "Hoàng Văn Toàn",
]

FEEDBACK_SAMPLES = [
    (5, "Chương trình rất hay, các tiết mục acoustic nghe rất tình cảm."),
    (5, "Âm thanh tốt, MC dẫn dắt tự nhiên. Mong CLB tổ chức thêm."),
    (4, "Nội dung ổn nhưng bắt đầu muộn khoảng 20 phút."),
    (4, "Thích không gian quán, chỉ hơi chật lúc đông người."),
    (3, "Phần giao lưu hơi dài, một số bạn phía sau không nghe rõ."),
    (5, "Check-in nhanh, không phải xếp hàng lâu như lần trước."),
    (2, "Micro bị rè ở tiết mục thứ ba, khá tiếc."),
    (4, "Ban tổ chức nhiệt tình, hỗ trợ nhanh."),
]


class Command(BaseCommand):
    help = "Nạp dữ liệu mẫu để demo đồ án"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Xoá toàn bộ dữ liệu cũ trước khi nạp")

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)  # kết quả giống nhau mỗi lần chạy, dễ kiểm tra

        if options["reset"]:
            self.stdout.write("Đang xoá dữ liệu cũ...")
            Feedback.objects.all().delete()
            WaitlistEntry.objects.all().delete()
            Notification.objects.all().delete()
            Expense.objects.all().delete()
            Ticket.objects.all().delete()
            Task.objects.all().delete()
            Application.objects.all().delete()
            RecruitmentRound.objects.all().delete()
            Department.objects.all().delete()
            TicketType.objects.all().delete()
            Event.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()

        users = self._create_users()
        lead = users["truongbtc"]
        # Pool thành viên dùng chung cho cả 3 sự kiện. Tạo một lần ở đây để
        # số vé trong bảng ticket_types KHỚP với số bản ghi Ticket thật -
        # nếu lệch thì trang thống kê và trang sự kiện báo hai con số khác
        # nhau, giảng viên nhìn ra ngay.
        pool = self._create_member_pool(35)

        event_a = self._event_open_many_seats(lead, pool)
        event_b = self._event_one_seat_left(lead, pool)
        event_c = self._event_done_with_stats(lead, pool)

        event_d = self._event_sold_out_with_waitlist(lead, pool, users)

        self._create_tasks(event_a, users)
        self._create_club_tasks(users)
        depts = self._create_departments(users, event_a)
        self._link_officers(users, depts)
        self._create_recruitment(users, depts)
        self._demo_member_tickets(users, event_a, event_c)
        self._create_expenses(event_a, event_c, users)
        self._create_notifications(users, event_a, event_c)

        self.stdout.write(self.style.SUCCESS("\nDa nap xong du lieu demo.\n"))
        self.stdout.write(f"  Mật khẩu chung cho mọi tài khoản: {PASSWORD}\n")
        for username, full_name, _, role in ACCOUNTS:
            self.stdout.write(f"  {username:12} {Role(role).label:16} {full_name}")
        self.stdout.write("\nSự kiện:")
        self.stdout.write(f"  A. {event_a.name} - mở bán, còn nhiều chỗ")
        self.stdout.write(f"  B. {event_b.name} - CHỈ CÒN 1 CHỖ (demo race condition)")
        self.stdout.write(f"  C. {event_c.name} - đã diễn ra, có thống kê + chứng nhận")
        self.stdout.write(f"  D. {event_d.name} - HẾT VÉ, có danh sách chờ\n")
        self.stdout.write("Các Ban: " + ", ".join(
            Department.objects.values_list("name", flat=True)))
        self.stdout.write("  btc1 = Trưởng ban Chuyên môn, btc2 = Trưởng ban Truyền thông & Sự kiện;")
        self.stdout.write("  mỗi Ban có việc 'chờ nhận' để demo nút Nhận việc.")
        self.stdout.write("Tuyển thành viên: 1 đợt đang mở, 4 đơn mẫu; 'khach' là tài khoản Khách.\n")

    # ------------------------------------------------------------------
    def _create_users(self):
        users = {}
        for username, full_name, mssv, role in ACCOUNTS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"full_name": full_name, "mssv": mssv, "role": role,
                          "email": f"{username}@example.com",
                          # Tài khoản demo coi như đã xác minh để đặt vé ngay;
                          # muốn demo OTP thì tự tạo tài khoản mới.
                          "email_verified_at": timezone.now()},
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            users[username] = user
        return users

    def _create_member_pool(self, count):
        """Tạo sẵn danh sách thành viên để gán vé cho các sự kiện."""
        pool = []
        for i in range(count):
            user, created = User.objects.get_or_create(
                username=f"sv{i:02d}",
                defaults={"full_name": MEMBER_NAMES[i],
                          "mssv": f"AT2000{i:02d}",
                          "email": f"sv{i:02d}@example.com",
                          "role": Role.MEMBER},
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            pool.append(user)
        return pool

    def _issue_tickets(self, event, ticket_type, users, status, checked_by=None,
                       booking_ref=None, booked_hours_ago=0):
        """
        Tạo vé thật cho một nhóm người, đồng thời cập nhật cột `sold`.

        Luôn đi qua hàm này thay vì gán tay `sold`, để số vé đã bán và số bản
        ghi Ticket không bao giờ lệch nhau. Truyền `booking_ref` để các vé
        chung một mã giao dịch (1 người đặt nhiều vé).
        """
        now = timezone.now()
        made = []
        for user in users:
            made.append(Ticket.objects.create(
                event=event, ticket_type=ticket_type, user=user,
                booking_ref=booking_ref or make_booking_ref(),
                price=ticket_type.price, status=status,
                confirmed_at=None if status == TicketStatus.PENDING else now,
                checked_in_at=event.starts_at
                    if status == TicketStatus.CHECKED_IN else None,
                checked_in_by=checked_by
                    if status == TicketStatus.CHECKED_IN else None,
            ))
        if booked_hours_ago:
            # created_at là auto_now_add nên phải sửa sau khi tạo
            Ticket.objects.filter(pk__in=[t.pk for t in made]).update(
                created_at=now - timezone.timedelta(hours=booked_hours_ago))
        ticket_type.sold = ticket_type.tickets.exclude(
            status=TicketStatus.CANCELLED).count()
        ticket_type.save(update_fields=["sold"])
        return made

    def _event_open_many_seats(self, lead, pool):
        """Sự kiện A - mở bán, còn nhiều chỗ."""
        now = timezone.now()
        event, _ = Event.objects.get_or_create(
            name="Acoustic Night #5 - Đêm nhạc mùa thu",
            defaults={
                "description": "Đêm nhạc acoustic của CLB Guitar với các tiết "
                               "mục do thành viên biểu diễn. Có giao lưu và "
                               "hướng dẫn chơi guitar cơ bản cho người mới.",
                "location": "Hội trường A2, Học viện",
                "category": EventCategory.MUSIC,
                "starts_at": now + timezone.timedelta(days=14),
                "ends_at": now + timezone.timedelta(days=14, hours=3),
                "register_deadline": now + timezone.timedelta(days=12),
                "capacity": 150,
                "budget": 5_000_000,
                "status": EventStatus.OPEN,
                "created_by": lead,
            },
        )
        free_type, made_free = TicketType.objects.get_or_create(
            event=event, name="Vé thành viên CLB",
            defaults={"price": 0, "quota": 60})
        paid_type, made_paid = TicketType.objects.get_or_create(
            event=event, name="Vé khách mời",
            defaults={"price": 50000, "quota": 80})

        if made_free and made_paid:
            # 12 vé miễn phí -> xác nhận ngay (đúng quy tắc F4.1)
            self._issue_tickets(event, free_type, pool[:12],
                                TicketStatus.CONFIRMED)
            # Vé có phí đã thanh toán
            self._issue_tickets(event, paid_type, pool[12:28] + pool[30:35],
                                TicketStatus.CONFIRMED)
            # Chỉ 2 giao dịch chờ thanh toán cho trang Xác nhận TT đỡ rối:
            # 1 nhóm 2 vé sắp hết hạn (đặt 20h trước) và 1 vé vừa đặt.
            self._issue_tickets(event, paid_type, [pool[28]] * 2,
                                TicketStatus.PENDING,
                                booking_ref=make_booking_ref(), booked_hours_ago=20)
            self._issue_tickets(event, paid_type, [pool[29]],
                                TicketStatus.PENDING, booked_hours_ago=2)
        return event

    def _event_one_seat_left(self, lead, pool):
        """
        Sự kiện B - chỉ còn 1 chỗ.

        Dùng cho bước demo quan trọng nhất: mở 2 trình duyệt cùng đặt chỗ
        cuối, chỉ 1 người thành công.
        """
        now = timezone.now()
        event, _ = Event.objects.get_or_create(
            name="Workshop Guitar cho người mới (còn 1 chỗ)",
            defaults={
                "description": "Buổi workshop nhỏ, giới hạn số lượng để mỗi "
                               "người đều được hướng dẫn trực tiếp.",
                "location": "Phòng B301",
                "category": EventCategory.ACADEMIC,
                "starts_at": now + timezone.timedelta(days=7),
                "register_deadline": now + timezone.timedelta(days=5),
                "capacity": 20,
                "status": EventStatus.OPEN,
                "created_by": lead,
            },
        )
        ticket_type, created = TicketType.objects.get_or_create(
            event=event, name="Vé workshop",
            defaults={"price": 30000, "quota": 20})
        if created:
            # 19/20 chỗ đã có người giữ -> còn ĐÚNG 1 chỗ cuối cùng
            self._issue_tickets(event, ticket_type, pool[:19],
                                TicketStatus.CONFIRMED)
        return event

    def _event_done_with_stats(self, lead, pool):
        """Sự kiện C - đã diễn ra, có vé, check-in và phản hồi để demo thống kê."""
        now = timezone.now()
        event, created = Event.objects.get_or_create(
            name="Minishow Tròn - Đêm nhạc kỷ niệm",
            defaults={
                "description": "Minishow kỷ niệm của CLB tại quán cà phê, "
                               "không gian ấm cúng.",
                "location": "An Hội An Cà Phê, Hà Đông",
                "category": EventCategory.MUSIC,
                "budget": 2_000_000,
                "starts_at": now - timezone.timedelta(days=3),
                "ends_at": now - timezone.timedelta(days=3) + timezone.timedelta(hours=3),
                "register_deadline": now - timezone.timedelta(days=5),
                "capacity": 100,
                "status": EventStatus.DONE,
                "created_by": lead,
            },
        )
        if not created:
            return event
        # Ảnh bìa gốc của minishow; media/ không lên Git nên chỉ gắn khi có file
        if (settings.MEDIA_ROOT / "events" / "minishow_tron.jpg").exists():
            event.cover = "events/minishow_tron.jpg"
            event.save(update_fields=["cover"])

        ticket_type = TicketType.objects.create(
            event=event, name="Vé tham dự", price=59000, quota=100)

        # 28/35 người đã check-in, tức tỉ lệ 80% - con số nhìn thật
        attended = pool[:28]
        self._issue_tickets(event, ticket_type, attended,
                            TicketStatus.CHECKED_IN, checked_by=lead)
        self._issue_tickets(event, ticket_type, pool[28:35],
                            TicketStatus.CONFIRMED)

        # Phản hồi: chỉ người ĐÃ CHECK-IN mới gửi được (đúng quy tắc F6.1)
        for user, (rating, content) in zip(attended, FEEDBACK_SAMPLES):
            Feedback.objects.create(event=event, user=user,
                                    rating=rating, content=content)

        # Công việc BTC đã xong, để demo tỉ lệ hoàn thành đúng hạn
        done_tasks = [
            ("Liên hệ và chốt quán", 10), ("Thiết kế poster", 8),
            ("Mở đăng ký và truyền thông", 7), ("Chuẩn bị âm thanh", 3),
            ("Tổng duyệt tiết mục", 2), ("Setup địa điểm", 1),
        ]
        for title, days_before in done_tasks:
            deadline = event.starts_at - timezone.timedelta(days=days_before)
            Task.objects.create(
                event=event, title=title, assignee=lead, deadline=deadline,
                status=TaskStatus.DONE,
                # 1 task xong muộn để tỉ lệ đúng hạn không phải 100%
                done_at=deadline + timezone.timedelta(
                    hours=5 if title == "Chuẩn bị âm thanh" else -3),
            )
        return event

    def _create_tasks(self, event, users):
        """Công việc BTC cho sự kiện A, đang làm dở để demo cập nhật tiến độ."""
        if event.tasks.exists():
            return
        rows = [
            ("Chốt danh sách tiết mục", 10, TaskStatus.DONE, "btc1"),
            ("Thiết kế poster và ảnh bìa", 8, TaskStatus.DOING, "btc2"),
            ("In poster và treo tại sảnh", 6, TaskStatus.TODO, "btc1"),
            ("Đăng bài truyền thông fanpage", 6, TaskStatus.TODO, "btc2"),
            ("Kiểm tra âm thanh hội trường", 3, TaskStatus.TODO, "btc1"),
            ("Phân công nhân sự ngày diễn ra", 2, TaskStatus.TODO, "btc2"),
        ]
        for title, days_before, status, assignee_key in rows:
            deadline = event.starts_at - timezone.timedelta(days=days_before)
            Task.objects.create(
                event=event, title=title, assignee=users[assignee_key],
                deadline=deadline, status=status,
                done_at=deadline - timezone.timedelta(hours=6)
                        if status == TaskStatus.DONE else None,
            )


    # ------------------------------------------------------------------
    # Dữ liệu cho các chức năng Sprint 3-5
    # ------------------------------------------------------------------
    def _event_sold_out_with_waitlist(self, lead, pool, users):
        """Sự kiện D - hết vé, đã có 3 người chờ. Tài khoản thanhvien vào chờ để demo."""
        now = timezone.now()
        event, created = Event.objects.get_or_create(
            name="Giao lưu Guitar liên CLB (đã hết vé)",
            defaults={
                "description": "Buổi giao lưu với CLB Guitar các trường bạn. "
                               "Vé đã hết - hãy vào danh sách chờ, có người huỷ "
                               "hệ thống sẽ tự cấp vé cho bạn.",
                "location": "Sân khấu ngoài trời, Khu B",
                "category": EventCategory.SOCIAL,
                "starts_at": now + timezone.timedelta(days=10),
                "ends_at": now + timezone.timedelta(days=10, hours=2),
                "register_deadline": now + timezone.timedelta(days=9),
                "capacity": 10,
                "status": EventStatus.OPEN,
                "created_by": lead,
            },
        )
        if not created:
            return event
        ticket_type = TicketType.objects.create(
            event=event, name="Vé giao lưu", price=0, quota=10)
        self._issue_tickets(event, ticket_type, pool[:10], TicketStatus.CONFIRMED)
        for user in [users["thanhvien2"], pool[20], pool[21]]:
            WaitlistEntry.objects.create(ticket_type=ticket_type, user=user)
        return event

    def _demo_member_tickets(self, users, event_a, event_c):
        """thanhvien: có vé sắp tới (sự kiện A) và đã check-in sự kiện C (chứng nhận)."""
        member = users["thanhvien"]
        if not Ticket.objects.filter(user=member, event=event_a).exists():
            tt = event_a.ticket_types.get(price=0)
            self._issue_tickets(event_a, tt, [member], TicketStatus.CONFIRMED)
        if not Ticket.objects.filter(user=member, event=event_c).exists():
            tt = event_c.ticket_types.first()
            self._issue_tickets(event_c, tt, [member], TicketStatus.CHECKED_IN,
                                checked_by=users["btc1"])

    def _create_expenses(self, event_a, event_c, users):
        if Expense.objects.exists():
            return
        rows = [
            (event_c, "Thuê quán cà phê", "VENUE", 800000, "truongbtc", 6),
            (event_c, "In poster, standee", "PRINT", 350000, "btc2", 8),
            (event_c, "Nước uống cho BTC", "FOOD", 240000, "btc1", 3),
            (event_c, "Thuê loa, micro", "EQUIP", 600000, "btc1", 3),
            (event_a, "Đặt cọc âm thanh ánh sáng", "EQUIP", 1500000, "truongbtc", -2),
            (event_a, "In vé mời và poster", "PRINT", 420000, "btc2", -1),
        ]
        today = timezone.localdate()
        for event, title, cat, amount, who, days_ago in rows:
            Expense.objects.create(
                event=event, title=title, category=cat, amount=amount,
                paid_by=users[who], created_by=users["truongbtc"],
                spent_on=today - timezone.timedelta(days=max(days_ago, 0)))

    def _create_notifications(self, users, event_a, event_c):
        member = users["thanhvien"]
        if member.notifications.exists():
            return
        Notification.objects.bulk_create([
            Notification(user=member, kind=NotificationKind.TICKET_CONFIRMED,
                         title=f"Đăng ký thành công: {event_a.name}",
                         message="Bạn đã đăng ký 1 vé. Mang mã QR tới cửa để check-in.",
                         url="/ve/cua-toi/"),
            Notification(user=member, kind=NotificationKind.EVENT_REMINDER,
                         title=f"Cảm ơn bạn đã tham gia: {event_c.name}",
                         message="Giấy chứng nhận tham gia đã sẵn sàng trong trang hồ sơ.",
                         url="/taikhoan/hoso/", is_read=True),
        ])
        Notification.objects.create(
            user=users["btc1"], kind=NotificationKind.TASK_ASSIGNED,
            title="Việc mới: Kiểm tra âm thanh hội trường",
            message=f"Trưởng BTC giao cho bạn việc của sự kiện {event_a.name}.",
            url="/congviec/viec-cua-toi/")

    def _create_club_tasks(self, users):
        """Việc chung của CLB do Ban chủ nhiệm giao - có việc giao cho chính Ban chủ nhiệm."""
        if Task.objects.filter(event__isnull=True).exists():
            return
        now = timezone.now()
        rows = [
            ("Họp Ban chủ nhiệm tháng này", "truongbtc", "admin", "HIGH", 3, TaskStatus.TODO),
            ("Lên kế hoạch tuyển thành viên khoá mới", "truongbtc", "admin", "NORMAL", 10, TaskStatus.DOING),
            ("Quyết toán quỹ CLB học kỳ", "admin", "truongbtc", "URGENT", 2, TaskStatus.TODO),
            ("Cập nhật danh sách thành viên", "btc1", "truongbtc", "NORMAL", 5, TaskStatus.TODO),
            ("Dọn dẹp phòng tập", "btc2", "truongbtc", "LOW", -1, TaskStatus.TODO),
        ]
        for title, to, by, prio, days, status in rows:
            Task.objects.create(title=title, assignee=users[to], created_by=users[by],
                                priority=prio, status=status,
                                deadline=now + timezone.timedelta(days=days))

    def _create_departments(self, users, event_a):
        """
        2 Ban lớn của KMG + gắn việc sự kiện A vào Ban + vài việc "chờ nhận".
        Demo: btc1 (Trưởng ban Chuyên môn) giao việc trong Ban mình; btc2 bấm
        "Nhận việc"; việc micro đến hạn trong 24h để demo lệnh nhắc hạn
        (python manage.py run_periodic).
        """
        rows = [
            ("Ban Truyền thông & Sự kiện", "truyen-thong-su-kien", "bi-megaphone",
             "Truyền thông fanpage, thiết kế ấn phẩm, chụp ảnh – quay video; lên kế "
             "hoạch, hậu cần và vận hành các show, sự kiện của CLB.",
             "btc2", ["btc2", "truongbtc", "thanhvien2"]),
            ("Ban Chuyên môn", "chuyen-mon", "bi-music-note-beamed",
             "Biểu diễn, tập luyện và dàn dựng tiết mục; hướng dẫn guitar, thanh nhạc "
             "cho thành viên mới; phụ trách âm thanh trên sân khấu.",
             "btc1", ["btc1", "admin", "thanhvien"]),
        ]
        depts = {}
        for i, (name, slug, icon, desc, lead, members) in enumerate(rows):
            d, created = Department.objects.get_or_create(
                slug=slug, defaults={"name": name, "icon": icon, "description": desc,
                                     "lead": users[lead], "order": i})
            if created:
                d.members.set([users[m] for m in members])
            depts[slug] = d
        if Task.objects.filter(department__isnull=False).exists():
            return depts

        # Gắn việc có sẵn của sự kiện A vào Ban phù hợp
        mapping = {
            "Thiết kế poster": "truyen-thong-su-kien",
            "Đăng bài truyền thông": "truyen-thong-su-kien",
            "In poster": "truyen-thong-su-kien",
            "Phân công nhân sự": "truyen-thong-su-kien",
            "Kiểm tra âm thanh": "chuyen-mon",
            "Chốt danh sách tiết mục": "chuyen-mon",
        }
        for task in event_a.tasks.all():
            for key, slug in mapping.items():
                if task.title.startswith(key):
                    task.department = depts[slug]
                    task.save(update_fields=["department"])

        # Việc giao cho CẢ BAN, chưa ai nhận -> demo "Nhận việc" + badge sidebar
        now = timezone.now()
        for title, slug, hours, prio in [
            ("Mượn thêm 2 micro không dây", "truyen-thong-su-kien", 20, "URGENT"),
            ("Viết caption & lên lịch 3 bài teaser", "truyen-thong-su-kien", 72, "HIGH"),
            ("Quay video recap đêm nhạc", "truyen-thong-su-kien", 15 * 24, "NORMAL"),
            ("Tập dượt tiết mục mở màn", "chuyen-mon", 5 * 24, "HIGH"),
            ("Soạn hợp âm bài song ca cho buổi tập", "chuyen-mon", 7 * 24, "NORMAL"),
        ]:
            Task.objects.create(event=event_a, department=depts[slug], title=title,
                                created_by=users["truongbtc"], priority=prio,
                                deadline=now + timezone.timedelta(hours=hours))
        return depts

    def _link_officers(self, users, depts):
        """Gắn Ban Quản trị (nạp sẵn bằng migration) với tài khoản demo và Ban."""
        links = {"Trần Nhật Hoàng": ("admin", None),
                 "Trần Đình Vũ": ("truongbtc", None),
                 "Lưu Nhật Linh": ("btc1", "chuyen-mon"),
                 "Phan Tiến Đạt": ("btc2", "truyen-thong-su-kien")}
        for officer in ClubOfficer.objects.filter(name__in=links, user__isnull=True):
            username, slug = links[officer.name]
            if ClubOfficer.objects.filter(user=users[username]).exists():
                continue
            officer.user = users[username]
            officer.department = depts.get(slug) if slug else None
            officer.save(update_fields=["user", "department"])

    def _create_recruitment(self, users, depts):
        """Một đợt tuyển đang mở + đơn mẫu ở các trạng thái khác nhau."""
        if RecruitmentRound.objects.exists():
            return
        now = timezone.now()
        rnd = RecruitmentRound.objects.create(
            name="Tuyển thành viên học kỳ 1 năm học 2026 - 2027",
            description=("Không yêu cầu biết chơi nhạc cụ. Ban Chuyên môn casting "
                         "ngắn (hát hoặc đàn 1 đoạn bất kỳ); Ban Truyền thông & Sự "
                         "kiện trò chuyện về sở thích và sản phẩm đã làm (nếu có)."),
            opens_at=now - timezone.timedelta(days=3),
            closes_at=now + timezone.timedelta(days=11),
            created_by=users["truongbtc"])
        for username, full_name, mssv, slug, strengths, level, status in APPLICANTS:
            user = users.get(username)
            if user is None:
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={"full_name": full_name, "mssv": mssv, "role": Role.GUEST,
                              "email": f"{username}@example.com",
                              "email_verified_at": timezone.now()})
                if created:
                    user.set_password(PASSWORD)
                    user.save()
            interview = status == "INTERVIEW"
            Application.objects.create(
                round=rnd, user=user, department=depts[slug], strengths=strengths,
                level=level, status=status,
                motivation="Mình muốn có một nơi để chơi nhạc cùng mọi người và học "
                           "thêm kỹ năng tổ chức sự kiện.",
                interview_at=now + timezone.timedelta(days=2, hours=3) if interview else None,
                review_note="Casting tại phòng sinh hoạt CLB, nhớ mang đàn nếu có."
                if interview else "",
                reviewer=users["btc1"] if interview else None)
