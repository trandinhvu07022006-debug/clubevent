"""Security boundary tests for INTERNAL event booking, waitlist, and page leaks."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, EventVisibility, TicketType
from organization.models import Appointment, PositionCode, ScopeType
from organization.services import approve_club_member, bootstrap_organization_catalog
from pages.services import club_numbers, personal_space, public_events

from .models import Ticket, WaitlistEntry
from .services import BookingError, book_tickets, join_waitlist


class InternalEventIsolationTests(TestCase):
    def setUp(self):
        now = timezone.now()
        catalog = bootstrap_organization_catalog()
        self.dept = catalog["departments"]["SPECIALTY"]
        self.chair = User.objects.create_user(
            username="sec_chair",
            password="x",
            full_name="Chủ nhiệm",
            role=Role.LEAD,
            email="chair@kmg.vn",
            email_verified_at=now,
        )
        Appointment.objects.create(
            user=self.chair,
            position=catalog["positions"][PositionCode.CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.chair,
        )
        self.guest = User.objects.create_user(
            username="sec_guest",
            password="x",
            full_name="Khách ngoài",
            role=Role.GUEST,
            email="guest@kmg.vn",
            email_verified_at=now,
        )
        self.member = User.objects.create_user(
            username="sec_club_member",
            password="x",
            full_name="Thành viên CLB",
            role=Role.GUEST,
            email="member@kmg.vn",
            email_verified_at=now,
        )
        approve_club_member(
            actor=self.chair, target_user=self.member, departments=[self.dept]
        )

        self.public_event = Event.objects.create(
            name="Đêm nhạc công khai",
            location="Sảnh A",
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4),
            capacity=50,
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
            created_by=self.chair,
        )
        self.public_tt = TicketType.objects.create(
            event=self.public_event, name="Vé công khai", price=0, quota=10
        )

        self.internal_event = Event.objects.create(
            name="Sinh hoạt nội bộ bí mật",
            location="Phòng Kín",
            starts_at=now + timezone.timedelta(days=3),
            register_deadline=now + timezone.timedelta(days=2),
            capacity=30,
            status=EventStatus.OPEN,
            visibility=EventVisibility.INTERNAL,
            created_by=self.chair,
        )
        self.internal_tt = TicketType.objects.create(
            event=self.internal_event, name="Vé nội bộ", price=0, quota=10
        )
        self.internal_sold_out_tt = TicketType.objects.create(
            event=self.internal_event, name="Vé nội bộ hết", price=0, quota=1, sold=1
        )

    def test_guest_cannot_book_internal_event_via_service_or_view(self):
        with self.assertRaisesMessage(BookingError, "nội bộ"):
            book_tickets(self.guest, self.internal_tt.pk, 1)

        self.client.force_login(self.guest)
        # Direct POST to internal event
        resp = self.client.post(
            reverse("registrations:book", args=[self.internal_event.pk]),
            {"ticket_type": self.internal_tt.pk, "quantity": 1},
        )
        self.assertEqual(resp.status_code, 404)

        # Parameter swap: POST public event URL with internal ticket_type_id
        swap_resp = self.client.post(
            reverse("registrations:book", args=[self.public_event.pk]),
            {"ticket_type": self.internal_tt.pk, "quantity": 1},
        )
        self.assertEqual(swap_resp.status_code, 302)
        self.assertEqual(Ticket.objects.filter(user=self.guest).count(), 0)

    def test_guest_cannot_join_internal_waitlist(self):
        with self.assertRaisesMessage(BookingError, "nội bộ"):
            join_waitlist(self.guest, self.internal_sold_out_tt.pk)

        self.client.force_login(self.guest)
        resp = self.client.post(
            reverse("registrations:waitlist_join", args=[self.internal_sold_out_tt.pk])
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(WaitlistEntry.objects.filter(user=self.guest).count(), 0)

    def test_locked_user_cannot_book_or_waitlist(self):
        self.member.is_locked = True
        self.member.save(update_fields=["is_locked"])
        with self.assertRaisesMessage(BookingError, "khoá"):
            book_tickets(self.member, self.public_tt.pk, 1)
        with self.assertRaisesMessage(BookingError, "khoá"):
            join_waitlist(self.member, self.internal_sold_out_tt.pk)

    def test_active_club_member_can_book_and_waitlist_internal_event(self):
        tickets = book_tickets(
            self.member, self.internal_tt.pk, 1, event_id=self.internal_event.pk
        )
        self.assertEqual(len(tickets), 1)
        entry = join_waitlist(self.member, self.internal_sold_out_tt.pk)
        self.assertEqual(entry.ticket_type_id, self.internal_sold_out_tt.pk)

    def test_public_pages_and_guest_suggestions_hide_internal_events(self):
        self.assertEqual([e.pk for e in public_events(limit=10)], [self.public_event.pk])
        nums = club_numbers()
        self.assertEqual(nums["events_total"], 1)

        guest_suggestions = [e.pk for e in personal_space(self.guest)["suggestions"]]
        self.assertEqual(guest_suggestions, [self.public_event.pk])

        member_suggestions = [e.pk for e in personal_space(self.member)["suggestions"]]
        self.assertIn(self.internal_event.pk, member_suggestions)

        self.client.force_login(self.guest)
        home_resp = self.client.get(reverse("pages:home") + "?xem=1")
        self.assertContains(home_resp, self.public_event.name)
        self.assertNotContains(home_resp, self.internal_event.name)
