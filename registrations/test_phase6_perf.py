"""Phase 6 performance & multi-tier load tests (50 / 200 users) and N+1 query bounds."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import time

from django.contrib.auth import get_user_model
from django.db import OperationalError, close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, Role
from events.models import Event, EventStatus, EventVisibility, TicketType
from registrations.models import Ticket, TicketStatus
from registrations.services import BookingError, CHECKIN_OK, book_tickets, check_in
from registrations.test_pilot_load import _percentile

User = get_user_model()


class MultiTierLoadTests(TransactionTestCase):
    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_50_users_concurrent_booking_and_200_chat_burst(self):
        now = timezone.now()
        event = Event.objects.create(
            name="Tier Load Concert",
            location="Hội trường KMA",
            capacity=30,
            starts_at=now + timezone.timedelta(days=7),
            register_deadline=now + timezone.timedelta(days=5),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        tt = TicketType.objects.create(event=event, name="Standard", price=0, quota=30)
        students = [
            User(
                username=f"load50_{i}",
                email=f"load50_{i}@example.com",
                role=Role.GUEST,
                account_status=AccountStatus.ACTIVE,
                email_verified_at=now,
            )
            for i in range(50)
        ]
        User.objects.bulk_create(students)
        students = list(User.objects.filter(username__startswith="load50_").order_by("pk"))

        def book(u):
            t0 = time.perf_counter()
            try:
                if connection.vendor == "sqlite":
                    with connection.cursor() as cur:
                        cur.execute("PRAGMA busy_timeout = 10000;")
                for retry in range(5):
                    try:
                        book_tickets(u, tt.pk, 1, event_id=event.pk)
                        return ("ok", (time.perf_counter() - t0) * 1000.0)
                    except OperationalError:
                        if retry == 4:
                            raise
                        time.sleep(0.02 * (retry + 1))
            except BookingError:
                return ("rejected", (time.perf_counter() - t0) * 1000.0)
            finally:
                connection.close()
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as pool:
            res50 = list(pool.map(book, students))

        tt.refresh_from_db()
        self.assertEqual(tt.sold, 30)
        self.assertEqual([r[0] for r in res50].count("ok"), 30)
        print(f"\n[LOAD-50-BOOK] ok=30/30, p95={_percentile([r[1] for r in res50], 95):.1f}ms")

        # 200 distinct-IP chat requests burst
        chat_url = reverse("aiassist:chat_api")
        chat_lat = []
        for i in range(200):
            t0 = time.perf_counter()
            resp = self.client.post(
                chat_url,
                data=json.dumps({"question": "Còn vé không?" if i % 2 == 0 else "Check-in thế nào?"}),
                content_type="application/json",
                REMOTE_ADDR=f"203.0.113.{(i % 200) + 1}",
            )
            chat_lat.append((time.perf_counter() - t0) * 1000.0)
            self.assertEqual(resp.status_code, 200)
        print(f"\n[LOAD-200-CHAT] ok=200/200, p95={_percentile(chat_lat, 95):.1f}ms")

    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_200_ticket_checkins_throughput(self):
        now = timezone.now()
        staff = User.objects.create_user(
            username="staff_ci200", email="ci200s@e.com", password="x",
            role=Role.STAFF, account_status=AccountStatus.ACTIVE, email_verified_at=now,
        )
        ev = Event.objects.create(
            name="200 Checkins Event", location="A", capacity=200,
            starts_at=now + timezone.timedelta(days=2),
            register_deadline=now + timezone.timedelta(days=1),
            status=EventStatus.OPEN, visibility=EventVisibility.PUBLIC,
        )
        tt = TicketType.objects.create(event=ev, name="GA", price=0, quota=200)
        users = [
            User(
                username=f"ci200_{i}", email=f"ci200_{i}@e.com", role=Role.GUEST,
                account_status=AccountStatus.ACTIVE, email_verified_at=now,
            )
            for i in range(200)
        ]
        User.objects.bulk_create(users)
        users = list(User.objects.filter(username__startswith="ci200_").order_by("pk"))
        self.assertEqual(len(users), 200)
        tickets = [book_tickets(u, tt.pk, 1, event_id=ev.pk)[0] for u in users]

        latencies = []
        for t in tickets:
            t0 = time.perf_counter()
            status, _, _ = check_in(staff, t.code, event=ev)
            latencies.append((time.perf_counter() - t0) * 1000.0)
            self.assertEqual(status, CHECKIN_OK)
        self.assertEqual(Ticket.objects.filter(event=ev, status=TicketStatus.CHECKED_IN).count(), 200)
        print(f"\n[LOAD-200-CHECKIN] checked_in=200/200, p95={_percentile(latencies, 95):.1f}ms")


class QueryOptimizationTests(TestCase):
    def test_public_event_list_and_portal_bounded_queries(self):
        now = timezone.now()
        for i in range(12):
            ev = Event.objects.create(
                name=f"Bounded Query Show {i}",
                location="Hội trường A",
                capacity=50,
                starts_at=now + timezone.timedelta(days=i + 1),
                register_deadline=now + timezone.timedelta(days=i + 1),
                status=EventStatus.OPEN,
                visibility=EventVisibility.PUBLIC,
            )
            TicketType.objects.create(event=ev, name="Vé Thường", price=0, quota=50)

        with self.assertNumQueries(4):
            r = self.client.get(reverse("events:list"))
        self.assertEqual(r.status_code, 200)
