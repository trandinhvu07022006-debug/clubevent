"""
Kiểm thử tự động Module 01 — Public Website (`/`) & API Liên hệ Công khai:
- Hiển thị trang chủ thương hiệu KMG Editorial Stage (`200 OK`).
- Cách ly tuyệt đối sự kiện `INTERNAL` & `DRAFT` khỏi khách vãng lai (`INT-01`) trên cả `/`, `/sukien/` và AI Chatbot.
- Không rò rỉ SĐT/Ngày sinh riêng tư của thành viên tiêu biểu ra trang công khai (`Data Privacy Rule 10`).
- Gửi form liên hệ, lọc spam Honeypot và giới hạn tần suất `429` trên `/api/v1/public/contact/`.
"""
from __future__ import annotations

from datetime import timedelta
import json

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, User, UserProfile
from events.models import Event, EventCategory, EventStatus, EventVisibility
from organization.models import ClubMembership, ClubMembershipStatus
from organization.services import approve_club_member, bootstrap_organization_catalog
from public_portal.models import ContactSubmission, ContactTopic


class PublicPortalAndEventIsolationTests(TestCase):
    def setUp(self):
        catalog = bootstrap_organization_catalog()
        self.dept_cm = catalog["departments"]["SPECIALTY"]
        now = timezone.now()

        # Tạo Chủ nhiệm và 1 thành viên tiêu biểu có SĐT riêng tư
        self.chair = User.objects.create_user(
            username="pub_chair",
            password="Password@123",
            full_name="Chủ nhiệm Minh Khôi",
            phone="0911222333",
            email="pub_chair@kmg.vn",
            account_status=AccountStatus.ACTIVE,
        )
        ClubMembership.objects.create(
            user=self.chair,
            member_code="KMG-2026-0001",
            status=ClubMembershipStatus.ACTIVE,
            is_featured=True,
            featured_title="Chủ nhiệm KMG",
        )
        UserProfile.objects.create(
            user=self.chair,
            privacy_show_phone=False,
            privacy_show_dob=False,
        )
        from organization.models import Appointment, PositionCode, ScopeType

        Appointment.objects.create(
            user=self.chair,
            position=catalog["positions"][PositionCode.CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.chair,
        )

        self.guest = User.objects.create_user(
            username="pub_guest",
            password="Password@123",
            full_name="Khách Yêu Nhạc",
            email="pub_guest@kmg.vn",
        )
        self.member = User.objects.create_user(
            username="pub_member",
            password="Password@123",
            full_name="Thành viên Chính thức",
            email="pub_member@kmg.vn",
        )
        approve_club_member(
            actor=self.chair, target_user=self.member, departments=[self.dept_cm]
        )

        self.public_event = Event.objects.create(
            name="Đêm Nhạc Công Khai KMG Open Stage",
            location="Sân khấu Khu A",
            category=EventCategory.MUSIC,
            starts_at=now + timedelta(days=7),
            register_deadline=now + timedelta(days=6),
            capacity=200,
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
            created_by=self.chair,
        )
        self.internal_event = Event.objects.create(
            name="Họp Chiến Lược Nội Bộ KMG Bí Mật",
            location="Phòng Họp Kín B302",
            category=EventCategory.MUSIC,
            starts_at=now + timedelta(days=3),
            register_deadline=now + timedelta(days=2),
            capacity=40,
            status=EventStatus.OPEN,
            visibility=EventVisibility.INTERNAL,
            created_by=self.chair,
        )
        self.draft_event = Event.objects.create(
            name="Sự Kiện Bản Nháp Chưa Duyệt",
            location="Hội trường B",
            category=EventCategory.MUSIC,
            starts_at=now + timedelta(days=10),
            register_deadline=now + timedelta(days=9),
            capacity=100,
            status=EventStatus.DRAFT,
            visibility=EventVisibility.PUBLIC,
            created_by=self.chair,
        )

    def test_public_home_renders_editorial_sections_and_protects_privacy_and_internal_events(self):
        """Trang chủ `/` hiển thị 3 Ban, sự kiện PUBLIC, ẩn sự kiện INTERNAL/DRAFT và ẩn SĐT cá nhân."""
        resp = Client().get(reverse("public_portal:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ban Truyền thông sự kiện")
        self.assertContains(resp, "Ban Chuyên môn")
        self.assertContains(resp, "Ban Kỹ thuật")
        self.assertContains(resp, self.public_event.name)
        self.assertNotContains(resp, self.internal_event.name)
        self.assertNotContains(resp, self.draft_event.name)
        # Tên hiển thị của thành viên tiêu biểu có xuất hiện, nhưng SĐT cá nhân tuyệt đối KHÔNG lộ
        self.assertContains(resp, "Chủ nhiệm Minh Khôi")
        self.assertNotContains(resp, "0911222333")

    def test_int01_internal_event_hidden_from_guest_and_chatbot_but_visible_to_active_member(self):
        """INT-01: Guest bị chặn xem sự kiện INTERNAL trên `/sukien/`, chi tiết, `.ics` và AI Chatbot."""
        guest_client = Client()
        guest_client.force_login(self.guest)

        list_resp = guest_client.get(reverse("events:list"))
        self.assertContains(list_resp, self.public_event.name)
        self.assertNotContains(list_resp, self.internal_event.name)

        # Guest truy cập trực tiếp URL chi tiết hoặc file .ics của sự kiện INTERNAL -> 404
        self.assertEqual(
            guest_client.get(
                reverse("events:detail", args=[self.internal_event.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            guest_client.get(
                reverse("events:ics", args=[self.internal_event.pk])
            ).status_code,
            404,
        )

        # AI Chatbot cũng không được tiết lộ sự kiện INTERNAL cho Guest
        chat_resp = guest_client.post(
            reverse("aiassist:chat_api"),
            data=json.dumps({"question": "Có những sự kiện nào đang mở?"}),
            content_type="application/json",
        )
        self.assertEqual(chat_resp.status_code, 200)
        self.assertNotIn(
            self.internal_event.name, chat_resp.json().get("answer", "")
        )

        # Ngược lại: Thành viên CLB đang ACTIVE xem được cả sự kiện PUBLIC lẫn INTERNAL
        member_client = Client()
        member_client.force_login(self.member)
        member_list = member_client.get(reverse("events:list"))
        self.assertContains(member_list, self.public_event.name)
        self.assertContains(member_list, self.internal_event.name)
        self.assertEqual(
            member_client.get(
                reverse("events:detail", args=[self.internal_event.pk])
            ).status_code,
            200,
        )

    def test_public_contact_api_and_honeypot_and_rate_limit(self):
        """API `/api/v1/public/contact/` lưu dữ liệu thật, chặn Honeypot bot và giới hạn 5 lần/10 phút."""
        api_url = reverse("api_v1:public_contact")
        client = Client()

        # 1. Gửi hợp lệ -> 201 Created
        ok_resp = client.post(
            api_url,
            data=json.dumps(
                {
                    "full_name": "Nguyễn Thảo Vy",
                    "email": "thaovy@example.com",
                    "phone": "0905111222",
                    "topic": ContactTopic.SPONSORSHIP,
                    "message": "Mình muốn trao đổi hợp tác tài trợ đêm nhạc mùa thu của KMG.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(ok_resp.status_code, 201)
        self.assertTrue(ok_resp.json()["ok"])
        self.assertEqual(ContactSubmission.objects.count(), 1)

        # 2. Bot điền trường ẩn `website` (Honeypot) -> 400 Bad Request, không lưu DB
        bot_resp = client.post(
            api_url,
            data=json.dumps(
                {
                    "full_name": "Spam Bot",
                    "email": "bot@spam.tld",
                    "message": "Buy cheap links now!",
                    "website": "https://spam.tld",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(bot_resp.status_code, 400)
        self.assertEqual(ContactSubmission.objects.count(), 1)

        # 3. Gửi vượt ngưỡng 5 lần trong cửa sổ 10 phút -> 429 RATE_LIMITED
        for _ in range(3):
            client.post(
                api_url,
                data=json.dumps(
                    {
                        "full_name": "Nguyễn Thảo Vy",
                        "email": "thaovy@example.com",
                        "message": "Tin nhắn bổ sung thông tin hợp tác.",
                    }
                ),
                content_type="application/json",
            )
        limited_resp = client.post(
            api_url,
            data=json.dumps(
                {
                    "full_name": "Nguyễn Thảo Vy",
                    "email": "thaovy@example.com",
                    "message": "Lượt thứ 6 vượt ngưỡng rate-limit.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(limited_resp.status_code, 429)
        self.assertEqual(limited_resp.json()["error"]["code"], "RATE_LIMITED")
