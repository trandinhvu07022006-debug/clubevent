"""Pilot 100-student simulation: concurrent booking invariants, QR check-in race safety, and chat burst latency."""
from concurrent.futures import ThreadPoolExecutor
import json
import time

from django.contrib.auth import get_user_model
from django.db import OperationalError, close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, Role
from events.models import Event, EventStatus, EventVisibility, TicketType
from registrations.models import Ticket, TicketStatus
from registrations.services import BookingError, CHECKIN_OK, CHECKIN_USED, book_tickets, check_in

User = get_user_model()


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(round((pct / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


class Pilot100LoadTests(TransactionTestCase):
    def _make_users(self, count: int, prefix: str):
        now = timezone.now()
        users = [
            User(
                username=f"{prefix}_{i}",
                email=f"{prefix}_{i}@example.com",
                full_name=f"Sinh vien {i}",
                role=Role.GUEST,
                account_status=AccountStatus.ACTIVE,
                email_verified_at=now,
            )
            for i in range(count)
        ]
        User.objects.bulk_create(users)
        return list(User.objects.filter(username__startswith=f"{prefix}_").order_by("pk"))

    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_100_users_competing_for_60_tickets_never_oversells(self):
        now = timezone.now()
        event = Event.objects.create(
            name="Pilot Acoustic 100SV",
            location="Hội trường KMA",
            capacity=60,
            starts_at=now + timezone.timedelta(days=7),
            register_deadline=now + timezone.timedelta(days=5),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        tt = TicketType.objects.create(event=event, name="Vé Pilot", price=0, quota=60)
        students = self._make_users(100, "pilot_book")

        # SQLite needs generous busy_timeout when threads contend on write locks
        if connection.vendor == "sqlite":
            with connection.cursor() as cur:
                cur.execute("PRAGMA busy_timeout = 10000;")

        def attempt_book(student):
            t0 = time.perf_counter()
            try:
                if connection.vendor == "sqlite":
                    with connection.cursor() as cur:
                        cur.execute("PRAGMA busy_timeout = 10000;")
                for retry in range(5):
                    try:
                        tickets = book_tickets(student, tt.pk, 1, event_id=event.pk)
                        return ("ok", (time.perf_counter() - t0) * 1000.0, len(tickets))
                    except OperationalError:
                        if retry == 4:
                            raise
                        time.sleep(0.02 * (retry + 1))
            except BookingError:
                return ("rejected", (time.perf_counter() - t0) * 1000.0, 0)
            finally:
                connection.close()
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt_book, students))

        statuses = [r[0] for r in results]
        latencies = [r[1] for r in results]
        tt.refresh_from_db()
        confirmed_count = Ticket.objects.filter(event=event, status=TicketStatus.CONFIRMED).count()

        self.assertLessEqual(confirmed_count, 60)
        self.assertEqual(tt.sold, confirmed_count)
        self.assertGreater(statuses.count("ok"), 0)
        self.assertGreaterEqual(statuses.count("rejected"), 40)
        p95_ms = _percentile(latencies, 95)
        print(
            f"\n[PILOT-BOOK-100] ok={statuses.count('ok')}, rejected={statuses.count('rejected')}, "
            f"sold={tt.sold}/60, p95={p95_ms:.1f}ms"
        )

    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_100_ticket_checkins_and_concurrent_duplicate_scan(self):
        now = timezone.now()
        staff = User.objects.create_user(
            username="pilot_staff",
            email="staff@example.com",
            password="x",
            role=Role.STAFF,
            account_status=AccountStatus.ACTIVE,
            email_verified_at=now,
        )
        event = Event.objects.create(
            name="Pilot Check-in 100",
            location="Sân trường",
            capacity=120,
            starts_at=now + timezone.timedelta(days=2),
            register_deadline=now + timezone.timedelta(days=1),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        tt = TicketType.objects.create(event=event, name="Vé Thường", price=0, quota=100)
        students = self._make_users(100, "pilot_ci")

        tickets = [book_tickets(u, tt.pk, 1, event_id=event.pk)[0] for u in students]
        race_ticket = tickets[0]

        def concurrent_scan(_):
            try:
                if connection.vendor == "sqlite":
                    with connection.cursor() as cur:
                        cur.execute("PRAGMA busy_timeout = 10000;")
                for retry in range(5):
                    try:
                        status, _, _ = check_in(staff, race_ticket.code, event=event)
                        return status
                    except OperationalError:
                        if retry == 4:
                            raise
                        time.sleep(0.02 * (retry + 1))
            finally:
                connection.close()
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as pool:
            race_results = list(pool.map(concurrent_scan, range(10)))

        self.assertEqual(race_results.count(CHECKIN_OK), 1)
        self.assertEqual(race_results.count(CHECKIN_USED), 9)

        latencies = []
        for t in tickets[1:]:
            t0 = time.perf_counter()
            status, _, _ = check_in(staff, t.code, event=event)
            latencies.append((time.perf_counter() - t0) * 1000.0)
            self.assertEqual(status, CHECKIN_OK)

        checked_total = Ticket.objects.filter(event=event, status=TicketStatus.CHECKED_IN).count()
        self.assertEqual(checked_total, 100)
        print(f"\n[PILOT-CHECKIN-100] checked_in={checked_total}/100, p95={_percentile(latencies, 95):.1f}ms")

    def test_100_chat_requests_rule_burst_latency(self):
        url = reverse("aiassist:chat_api")
        latencies = []
        for i in range(100):
            t0 = time.perf_counter()
            resp = self.client.post(
                url,
                data=json.dumps({"question": "Đăng ký thế nào?" if i % 2 == 0 else "Còn vé không?"}),
                content_type="application/json",
                REMOTE_ADDR=f"198.51.100.{(i % 200) + 1}",
            )
            latencies.append((time.perf_counter() - t0) * 1000.0)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["source"], "rules")
        print(f"\n[PILOT-CHAT-100] ok=100/100, p95={_percentile(latencies, 95):.1f}ms")
