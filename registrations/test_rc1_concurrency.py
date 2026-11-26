"""
RC1 Concurrency & Lock Ordering Stress Tests (AUD-008):
Covers concurrent bookings across ticket types, cancellation + waitlist promotion,
payment confirmation, webhook auto-confirm idempotency, check-in race,
symmetric opposite-direction transfers (no AB-BA deadlock), expired release,
and deadlock retry behavior.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

from django.contrib.auth import get_user_model
from django.db import OperationalError, close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import AccountStatus, Role
from events.models import Event, EventStatus, EventVisibility, TicketType
from registrations.models import Ticket, TicketStatus, WaitlistEntry, WaitlistStatus
from registrations.services import (
    CHECKIN_OK,
    CHECKIN_USED,
    BookingError,
    _run_atomic_with_retry,
    auto_confirm_transfer,
    book_tickets,
    cancel_ticket,
    check_in,
    confirm_payment,
    join_waitlist,
    release_expired_tickets,
    transfer_ticket,
)

User = get_user_model()


def _verified_user(username: str, role: str = Role.GUEST) -> User:
    return User.objects.create_user(
        username=username,
        password="x",
        role=role,
        account_status=AccountStatus.ACTIVE,
        email=f"{username}@example.com",
        email_verified_at=timezone.now(),
    )


class RegistrationsConcurrencyTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.staff = _verified_user("conc_staff", role=Role.STAFF)
        self.event = Event.objects.create(
            name="Concurrency Show",
            location="Hội trường A",
            capacity=100,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        self.tt_free = TicketType.objects.create(event=self.event, name="Free", price=0, quota=5)
        self.tt_vip = TicketType.objects.create(event=self.event, name="VIP", price=50000, quota=10)

    @staticmethod
    def _run_parallel(tasks):
        barrier = threading.Barrier(len(tasks))

        def runner(fn):
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                return ("ok", fn())
            except Exception as exc:
                return ("err", exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            return list(pool.map(runner, tasks))

    def test_concurrent_bookings_never_oversell_or_exceed_cap(self):
        u1 = _verified_user("conc_u1")
        # 6 concurrent attempts across Free (tt_free) and VIP (tt_vip) -> max 4 total
        tasks = [
            (lambda: book_tickets(u1, self.tt_free.pk, 2)),
            (lambda: book_tickets(u1, self.tt_vip.pk, 2)),
            (lambda: book_tickets(u1, self.tt_free.pk, 2)),
            (lambda: book_tickets(u1, self.tt_vip.pk, 2)),
        ]
        results = self._run_parallel(tasks)
        success_tickets = sum(len(res) for kind, res in results if kind == "ok")
        self.assertLessEqual(success_tickets, 4)
        self.assertEqual(
            Ticket.objects.filter(user=u1, event=self.event).exclude(status=TicketStatus.CANCELLED).count(),
            success_tickets,
        )

    def test_concurrent_cancel_and_waitlist_promotion_keeps_sold_consistent(self):
        tt = TicketType.objects.create(event=self.event, name="Single", price=0, quota=2)
        u_a = _verified_user("wait_a")
        u_b = _verified_user("wait_b")
        u_c = _verified_user("wait_c")
        u_d = _verified_user("wait_d")
        t_a = book_tickets(u_a, tt.pk, 1)[0]
        t_b = book_tickets(u_b, tt.pk, 1)[0]
        join_waitlist(u_c, tt.pk)
        join_waitlist(u_d, tt.pk)

        results = self._run_parallel([
            lambda: cancel_ticket(u_a, t_a.pk),
            lambda: cancel_ticket(u_b, t_b.pk),
        ])
        self.assertEqual(sum(1 for k, _ in results if k == "ok"), 2)
        tt.refresh_from_db()
        active = Ticket.objects.filter(ticket_type=tt).exclude(status=TicketStatus.CANCELLED).count()
        self.assertEqual(tt.sold, active)
        self.assertEqual(active, 2)
        self.assertEqual(
            WaitlistEntry.objects.filter(ticket_type=tt, status=WaitlistStatus.PROMOTED).count(),
            2,
        )

    def test_concurrent_confirm_payment_single_winner(self):
        buyer = _verified_user("pay_buyer")
        ticket = book_tickets(buyer, self.tt_vip.pk, 1)[0]
        self.assertEqual(ticket.status, TicketStatus.PENDING)

        staff2 = _verified_user("conc_staff2", role=Role.STAFF)
        results = self._run_parallel([
            lambda: confirm_payment(self.staff, ticket.pk),
            lambda: confirm_payment(staff2, ticket.pk),
        ])
        wins = [r for k, r in results if k == "ok"]
        fails = [r for k, r in results if k == "err"]
        self.assertEqual(len(wins), 1)
        self.assertEqual(len(fails), 1)
        self.assertIsInstance(fails[0], BookingError)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.CONFIRMED)

    def test_concurrent_auto_confirm_transfer_idempotent(self):
        buyer = _verified_user("wh_buyer")
        tickets = book_tickets(buyer, self.tt_vip.pk, 2)
        ref = tickets[0].booking_ref

        results = self._run_parallel([
            lambda: auto_confirm_transfer(f"CK KMG {ref}", 100000),
            lambda: auto_confirm_transfer(f"CK KMG {ref}", 100000),
            lambda: auto_confirm_transfer(f"CK KMG {ref}", 100000),
        ])
        ok_flags = [res[0] for kind, res in results if kind == "ok"]
        self.assertEqual(ok_flags.count(True), 1)
        self.assertEqual(
            Ticket.objects.filter(booking_ref=ref, status=TicketStatus.CONFIRMED).count(),
            2,
        )

    def test_concurrent_check_in_single_winner(self):
        buyer = _verified_user("ci_buyer")
        ticket = book_tickets(buyer, self.tt_free.pk, 1)[0]
        results = self._run_parallel([
            lambda: check_in(self.staff, ticket.code, event=self.event),
            lambda: check_in(self.staff, ticket.code, event=self.event),
        ])
        statuses = [res[0] for kind, res in results if kind == "ok"]
        self.assertEqual(statuses.count(CHECKIN_OK), 1)
        self.assertEqual(statuses.count(CHECKIN_USED), 1)

    def test_concurrent_reciprocal_transfers_no_deadlock(self):
        user_a = _verified_user("xfer_a")
        user_b = _verified_user("xfer_b")
        t_a = book_tickets(user_a, self.tt_free.pk, 1)[0]
        t_b = book_tickets(user_b, self.tt_free.pk, 1)[0]

        results = self._run_parallel([
            lambda: transfer_ticket(user_a, t_a.pk, user_b.username),
            lambda: transfer_ticket(user_b, t_b.pk, user_a.username),
        ])
        self.assertEqual([k for k, _ in results], ["ok", "ok"])
        t_a.refresh_from_db()
        t_b.refresh_from_db()
        self.assertEqual(t_a.user_id, user_b.pk)
        self.assertEqual(t_b.user_id, user_a.pk)

    def test_concurrent_release_expired_and_deadlock_retry(self):
        old_time = timezone.now() - timezone.timedelta(hours=48)
        buyer = _verified_user("exp_buyer")
        tickets = book_tickets(buyer, self.tt_vip.pk, 2)
        Ticket.objects.filter(pk__in=[t.pk for t in tickets]).update(created_at=old_time)

        results = self._run_parallel([
            release_expired_tickets,
            release_expired_tickets,
        ])
        self.assertTrue(all(k == "ok" for k, _ in results))
        self.assertEqual(sum(r for _, r in results), 2)
        self.tt_vip.refresh_from_db()
        self.assertEqual(self.tt_vip.sold, 0)

        # Verify retry helper recovers from simulated MySQL 1213 deadlock & SQLite locked
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationalError(1213, "Deadlock found when trying to get lock; try restarting transaction")
            if calls["n"] == 2:
                raise OperationalError("database is locked")
            return "recovered"

        self.assertEqual(_run_atomic_with_retry(flaky, max_attempts=4), "recovered")
        self.assertEqual(calls["n"], 3)
