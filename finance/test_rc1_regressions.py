"""
RC1 Finance & Permission Regression Suite (AUD-009):
- Concurrent approvals (single winner, immutable balance)
- SePay duplicate webhook idempotency
- Mid-flight permission revocation (Appointment/PermissionGrant)
- Department scope enforcement (Web & /api/v1/)
- Private Vault receipt ACL + nosniff/no-store headers
- Advisor INV-04 strict Read-Only & out-of-scope API object IDs
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import shutil
import tempfile
import threading

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, Role
from events.models import Event, EventStatus, EventVisibility, TicketType
from finance.models import FinancialTransaction, FundCategory, TransactionStatus, TransactionType
from finance.services import (
    bootstrap_finance_categories,
    compute_club_fund_summary,
    create_financial_transaction,
    review_financial_transaction,
)
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    PermissionGrant,
    Position,
    PositionCode,
    ScopeType,
)
from organization.services import GovernanceError
from registrations.models import Ticket, TicketStatus
from registrations.services import book_tickets

User = get_user_model()


def _setup_roles(owner):
    defs = {
        PositionCode.CHAIRMAN: ("Chủ nhiệm CLB", ScopeType.CLUB, True, True, False),
        PositionCode.VICE_CHAIRMAN: ("Phó chủ nhiệm CLB", ScopeType.CLUB, True, False, False),
        PositionCode.ADVISOR: ("Cố vấn CLB", ScopeType.CLUB, False, False, True),
        PositionCode.DEPT_HEAD: ("Trưởng ban", ScopeType.DEPARTMENT, True, True, False),
    }
    positions = {}
    for code, (name, scope, officer, singleton, ro) in defs.items():
        positions[code], _ = Position.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "scope_type": scope,
                "is_officer": officer,
                "is_singleton": singleton,
                "is_read_only": ro,
            },
        )
    return positions


class FinanceAndRBACRegressionTests(TransactionTestCase):
    def setUp(self):
        self.vault_dir = tempfile.mkdtemp(prefix="kmg-fin-vault-")
        self.addCleanup(shutil.rmtree, self.vault_dir, ignore_errors=True)
        self.dept_a = Department.objects.create(code="FIN_A", name="Ban Hậu cần", slug="fin-a", is_active=True)
        self.dept_b = Department.objects.create(code="FIN_B", name="Ban Truyền thông", slug="fin-b", is_active=True)
        self.positions = _setup_roles(None)
        bootstrap_finance_categories()
        self.cat = FundCategory.objects.filter(tx_type=TransactionType.EXPENSE).first()

        self.chair = User.objects.create_user(
            "fin_chair", password="x", role=Role.MEMBER, account_status=AccountStatus.ACTIVE
        )
        Appointment.objects.create(
            user=self.chair, position=self.positions[PositionCode.CHAIRMAN], scope_type=ScopeType.CLUB, is_active=True
        )

        self.vc_fin = User.objects.create_user(
            "fin_vc", password="x", role=Role.MEMBER, account_status=AccountStatus.ACTIVE
        )
        self.vc_appt = Appointment.objects.create(
            user=self.vc_fin,
            position=self.positions[PositionCode.VICE_CHAIRMAN],
            scope_type=ScopeType.CLUB,
            is_active=True,
        )
        self.vc_grant = PermissionGrant.objects.create(
            grantee=self.vc_fin,
            bound_appointment=self.vc_appt,
            scope_type=ScopeType.CLUB,
            bundle_code=GrantBundleCode.PORTFOLIO_FINANCE_DOC,
            granted_by=self.chair,
            reason="Phụ trách tài chính",
        )

        self.vc_fin2 = User.objects.create_user(
            "fin_vc2", password="x", role=Role.MEMBER, account_status=AccountStatus.ACTIVE
        )
        vc2_appt = Appointment.objects.create(
            user=self.vc_fin2,
            position=self.positions[PositionCode.VICE_CHAIRMAN],
            scope_type=ScopeType.CLUB,
            is_active=True,
        )
        PermissionGrant.objects.create(
            grantee=self.vc_fin2,
            bound_appointment=vc2_appt,
            scope_type=ScopeType.CLUB,
            bundle_code=GrantBundleCode.PORTFOLIO_FINANCE_DOC,
            granted_by=self.chair,
            reason="Checker 2",
        )

        self.advisor = User.objects.create_user(
            "fin_advisor", password="x", role=Role.MEMBER, account_status=AccountStatus.ACTIVE
        )
        Appointment.objects.create(
            user=self.advisor, position=self.positions[PositionCode.ADVISOR], scope_type=ScopeType.CLUB, is_active=True
        )

        self.head_a = User.objects.create_user(
            "fin_head_a", password="x", role=Role.MEMBER, account_status=AccountStatus.ACTIVE
        )
        ClubMembership.objects.create(user=self.head_a, member_code="KMG-2026-F001", status=ClubMembershipStatus.ACTIVE)
        DepartmentMembership.objects.create(
            user=self.head_a, department=self.dept_a, status=DeptMembershipStatus.ACTIVE
        )
        Appointment.objects.create(
            user=self.head_a,
            position=self.positions[PositionCode.DEPT_HEAD],
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept_a,
            is_active=True,
        )

        self.head_b = User.objects.create_user(
            "fin_head_b", password="x", role=Role.MEMBER, account_status=AccountStatus.ACTIVE
        )
        ClubMembership.objects.create(user=self.head_b, member_code="KMG-2026-F002", status=ClubMembershipStatus.ACTIVE)
        DepartmentMembership.objects.create(
            user=self.head_b, department=self.dept_b, status=DeptMembershipStatus.ACTIVE
        )
        Appointment.objects.create(
            user=self.head_b,
            position=self.positions[PositionCode.DEPT_HEAD],
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept_b,
            is_active=True,
        )

    def test_concurrent_approvals_single_winner_and_consistent_balance(self):
        tx = create_financial_transaction(
            self.head_a,
            tx_type=TransactionType.EXPENSE,
            category=self.cat,
            title="Thuê loa kẹo kéo",
            amount=350000,
            transaction_date=datetime.date.today(),
            department=self.dept_a,
        )
        barrier = threading.Barrier(2)

        def review(checker):
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                return ("ok", review_financial_transaction(checker, tx, approve=True))
            except Exception as exc:
                return ("err", exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(review, [self.chair, self.vc_fin]))

        wins = [r for k, r in results if k == "ok"]
        fails = [r for k, r in results if k == "err"]
        self.assertEqual(len(wins), 1)
        self.assertEqual(len(fails), 1)
        self.assertIsInstance(fails[0], GovernanceError)
        tx.refresh_from_db()
        self.assertEqual(tx.status, TransactionStatus.CONFIRMED)
        summary = compute_club_fund_summary()
        self.assertEqual(summary["confirmed_expense"], 350000)

    @override_settings(SEPAY_API_KEY="rc1-sepay-secret-key")
    def test_duplicate_sepay_webhook_idempotency(self):
        now = timezone.now()
        ev = Event.objects.create(
            name="Paid Concert",
            location="Sảnh B",
            capacity=50,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        tt = TicketType.objects.create(event=ev, name="Standard", price=80000, quota=10)
        buyer = User.objects.create_user(
            "wh_user", password="x", email="wh@example.com", email_verified_at=now
        )
        tickets = book_tickets(buyer, tt.pk, 2)
        ref = tickets[0].booking_ref

        url = reverse("registrations:sepay_webhook")
        payload = json.dumps({
            "transferType": "in",
            "transferAmount": 160000,
            "content": f"KMG {ref}",
            "accountNumber": "",
        })
        r1 = self.client.post(url, data=payload, content_type="application/json", HTTP_AUTHORIZATION="Apikey rc1-sepay-secret-key")
        r2 = self.client.post(url, data=payload, content_type="application/json", HTTP_AUTHORIZATION="Apikey rc1-sepay-secret-key")
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()["confirmed"])
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()["confirmed"])
        self.assertEqual(Ticket.objects.filter(booking_ref=ref, status=TicketStatus.CONFIRMED).count(), 2)

    def test_mid_flight_permission_revocation_blocks_maker_and_checker(self):
        tx = create_financial_transaction(
            self.head_a,
            tx_type=TransactionType.EXPENSE,
            category=self.cat,
            title="Dây đàn dự phòng",
            amount=120000,
            transaction_date=datetime.date.today(),
            department=self.dept_a,
        )
        # Revoke vc_fin's finance grant mid-flight
        self.vc_grant.is_active = False
        self.vc_grant.revoked_at = timezone.now()
        self.vc_grant.save(update_fields=["is_active", "revoked_at"])

        self.client.force_login(self.vc_fin)
        resp = self.client.post(
            reverse("api_v1:finance_transaction_review", args=[tx.pk]),
            data=json.dumps({"decision": "APPROVE"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        tx.refresh_from_db()
        self.assertEqual(tx.status, TransactionStatus.PENDING_APPROVAL)

    def test_department_scope_private_vault_acl_and_advisor_readonly(self):
        with override_settings(PRIVATE_VAULT_ROOT=self.vault_dir):
            receipt = SimpleUploadedFile("bill.pdf", b"%PDF-1.4\nhoa-don-hop-le", content_type="application/pdf")
            tx_a = create_financial_transaction(
                self.head_a,
                tx_type=TransactionType.EXPENSE,
                category=self.cat,
                title="Đạo cụ Ban Hậu cần",
                amount=200000,
                transaction_date=datetime.date.today(),
                department=self.dept_a,
                receipt_file=receipt,
            )

            # Wrong-department head cannot propose for dept_a, cannot view detail API, cannot download receipt
            with self.assertRaises(PermissionDenied):
                create_financial_transaction(
                    self.head_b,
                    tx_type=TransactionType.EXPENSE,
                    category=self.cat,
                    title="Đề xuất chéo ban",
                    amount=50000,
                    transaction_date=datetime.date.today(),
                    department=self.dept_a,
                )
            self.client.force_login(self.head_b)
            self.assertEqual(
                self.client.get(reverse("api_v1:finance_transaction_detail", args=[tx_a.pk])).status_code,
                403,
            )
            self.assertEqual(
                self.client.get(reverse("finance:transaction_receipt", args=[tx_a.pk])).status_code,
                403,
            )
            # Out-of-scope nonexistent API ID returns 404 without leakage
            self.assertEqual(
                self.client.get(reverse("api_v1:finance_transaction_detail", args=[999999])).status_code,
                404,
            )

            # Authorized maker/chairman can download private vault receipt with security headers
            self.client.force_login(self.chair)
            dl = self.client.get(reverse("finance:transaction_receipt", args=[tx_a.pk]))
            self.assertEqual(dl.status_code, 200)
            self.assertEqual(dl["X-Content-Type-Options"], "nosniff")
            self.assertEqual(dl["Cache-Control"], "private, no-store")
            self.assertEqual(b"".join(dl.streaming_content), b"%PDF-1.4\nhoa-don-hop-le")

            # Advisor INV-04: allowed read summary/hub, blocked on all mutations
            self.client.force_login(self.advisor)
            self.assertEqual(self.client.get(reverse("api_v1:finance_summary")).status_code, 200)
            self.assertEqual(self.client.get(reverse("finance:hub")).status_code, 200)
            self.assertEqual(
                self.client.post(
                    reverse("api_v1:finance_transaction_review", args=[tx_a.pk]),
                    data=json.dumps({"decision": "APPROVE"}),
                    content_type="application/json",
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.post(
                    reverse("api_v1:finance_transactions"),
                    data=json.dumps({
                        "tx_type": TransactionType.EXPENSE,
                        "category": self.cat.code,
                        "title": "Advisor thử chi",
                        "amount": 10000,
                        "transaction_date": str(datetime.date.today()),
                    }),
                    content_type="application/json",
                ).status_code,
                403,
            )
