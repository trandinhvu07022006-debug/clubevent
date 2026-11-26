"""Phase 3 business logic regression tests: multi-ticket-type concurrency, waitlist consistency, and public metrics."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError, close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import AccountStatus, Role
from events.models import Event, EventStatus, EventVisibility, TicketType
from organization.models import ClubMembership, ClubMembershipStatus
from pages.services import club_numbers
from registrations.models import Ticket, TicketStatus, WaitlistStatus
from registrations.services import (
    BookingError,
    book_tickets,
    cancel_ticket,
    join_waitlist,
    release_expired_tickets,
)

User = get_user_model()


class MultiTicketTypeConcurrencyTests(TransactionTestCase):
    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_same_user_racing_two_ticket_types_cannot_exceed_per_event_limit(self):
        now = timezone.now()
        user = User.objects.create_user(
            username="race_user",
            email="race@example.com",
            password="x",
            role=Role.GUEST,
            account_status=AccountStatus.ACTIVE,
            email_verified_at=now,
        )
        event = Event.objects.create(
            name="Multi Tier Show",
            location="Sân khấu KMA",
            capacity=100,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=3),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        tt_vip = TicketType.objects.create(event=event, name="VIP", price=0, quota=50)
        tt_std = TicketType.objects.create(event=event, name="Standard", price=0, quota=50)

        def book_one(tt_id: int):
            try:
                if connection.vendor == "sqlite":
                    with connection.cursor() as cur:
                        cur.execute("PRAGMA busy_timeout = 10000;")
                for retry in range(6):
                    try:
                        book_tickets(user, tt_id, 2, event_id=event.pk)
                        return "ok"
                    except OperationalError:
                        if retry == 5:
                            raise
                        time.sleep(0.02 * (retry + 1))
            except BookingError:
                return "rejected"
            finally:
                connection.close()
                close_old_connections()

        targets = [tt_vip.pk, tt_std.pk, tt_vip.pk, tt_std.pk, tt_vip.pk, tt_std.pk]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(book_one, targets))

        total_tickets = Ticket.objects.filter(
            user=user, event=event, status=TicketStatus.CONFIRMED
        ).count()
        self.assertLessEqual(total_tickets, settings.MAX_TICKETS_PER_USER_PER_EVENT)
        self.assertEqual(results.count("ok") * 2, total_tickets)

    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_multiple_students_across_two_ticket_types_never_oversell(self):
        now = timezone.now()
        event = Event.objects.create(
            name="Split Tier Concert",
            location="Hội trường A",
            capacity=60,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=3),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        tt_a = TicketType.objects.create(event=event, name="Hạng A", price=0, quota=30)
        tt_b = TicketType.objects.create(event=event, name="Hạng B", price=0, quota=30)
        users = [
            User(
                username=f"multi_u_{i}",
                email=f"multi_u_{i}@example.com",
                role=Role.GUEST,
                account_status=AccountStatus.ACTIVE,
                email_verified_at=now,
            )
            for i in range(90)
        ]
        User.objects.bulk_create(users)
        saved_users = list(User.objects.filter(username__startswith="multi_u_").order_by("pk"))

        def book_pair(idx_and_user):
            idx, u = idx_and_user
            tt_id = tt_a.pk if idx % 2 == 0 else tt_b.pk
            try:
                if connection.vendor == "sqlite":
                    with connection.cursor() as cur:
                        cur.execute("PRAGMA busy_timeout = 10000;")
                for retry in range(6):
                    try:
                        book_tickets(u, tt_id, 1, event_id=event.pk)
                        return "ok"
                    except OperationalError:
                        if retry == 5:
                            raise
                        time.sleep(0.02 * (retry + 1))
            except BookingError:
                return "rejected"
            finally:
                connection.close()
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(book_pair, enumerate(saved_users)))

        tt_a.refresh_from_db()
        tt_b.refresh_from_db()
        self.assertEqual(tt_a.sold, 30)
        self.assertEqual(tt_b.sold, 30)
        self.assertEqual(Ticket.objects.filter(event=event, status=TicketStatus.CONFIRMED).count(), 60)


class PublicNumbersAndWaitlistConsistencyTests(TestCase):
    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_club_numbers_excludes_guests_and_internal_checkins(self):
        now = timezone.now()
        guest = User.objects.create_user("guest_only", email="g@example.com", password="x", role=Role.GUEST)
        member = User.objects.create_user("real_member", email="m@example.com", password="x", role=Role.MEMBER)
        ClubMembership.objects.create(user=member, member_code="KMG-2026-8801", status=ClubMembershipStatus.ACTIVE)

        pub_ev = Event.objects.create(
            name="Public Show", location="A", capacity=20,
            starts_at=now + timezone.timedelta(days=2),
            register_deadline=now + timezone.timedelta(days=1),
            status=EventStatus.OPEN, visibility=EventVisibility.PUBLIC,
        )
        priv_ev = Event.objects.create(
            name="Internal Rehearsal", location="B", capacity=20,
            starts_at=now + timezone.timedelta(days=2),
            register_deadline=now + timezone.timedelta(days=1),
            status=EventStatus.OPEN, visibility=EventVisibility.INTERNAL,
        )
        tt_pub = TicketType.objects.create(event=pub_ev, name="Pub", price=0, quota=10)
        tt_priv = TicketType.objects.create(event=priv_ev, name="Priv", price=0, quota=10)
        Ticket.objects.create(user=guest, event=pub_ev, ticket_type=tt_pub, status=TicketStatus.CHECKED_IN)
        Ticket.objects.create(user=member, event=priv_ev, ticket_type=tt_priv, status=TicketStatus.CHECKED_IN)

        nums = club_numbers()
        self.assertEqual(nums["members"], 1)
        self.assertEqual(nums["checkins"], 1)

    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_waitlist_promotion_consistency_with_expiry_and_cancel(self):
        now = timezone.now()
        u1 = User.objects.create_user("wl_u1", email="w1@e.com", password="x", account_status=AccountStatus.ACTIVE, email_verified_at=now)
        u2 = User.objects.create_user("wl_u2", email="w2@e.com", password="x", account_status=AccountStatus.ACTIVE, email_verified_at=now)
        ev = Event.objects.create(
            name="Paid Concert", location="A", capacity=10,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=3),
            status=EventStatus.OPEN, visibility=EventVisibility.PUBLIC,
        )
        tt = TicketType.objects.create(event=ev, name="Paid", price=50000, quota=1)
        [t1] = book_tickets(u1, tt.pk, 1, event_id=ev.pk)
        Ticket.objects.filter(pk=t1.pk).update(created_at=now - timezone.timedelta(hours=30))
        wl = join_waitlist(u2, tt.pk)

        released = release_expired_tickets()
        self.assertEqual(released, 1)
        wl.refresh_from_db()
        tt.refresh_from_db()
        self.assertEqual(wl.status, WaitlistStatus.PROMOTED)
        self.assertEqual(tt.sold, 1)

        cancel_ticket(u2, wl.ticket_id)
        tt.refresh_from_db()
        self.assertEqual(tt.sold, 0)
