"""
Bộ kiểm thử Phase 5 — Quản lý Quỹ & Tài chính CLB Bất biến (`finance`).

Kiểm thử toàn diện:
- `WF22` & `INV-03`: Maker-Checker độc lập (chặn tự duyệt `created_by == approved_by`).
- Bất biến giao dịch `CONFIRMED`: chặn chỉnh sửa qua `.save()` và chặn `.delete()`, bắt buộc dùng `ADJUSTMENT`.
- `CM-03` Bridge: Khóa sửa/xoá trên `organizing.Expense` khi giao dịch liên kết đã `CONFIRMED`.
- `SEC-01`: Xác thực chứng từ hoá đơn (magic bytes, PDF/PNG, chặn script), lưu trữ mật.
- `PA-06`: Cán bộ Ban chỉ được đề xuất chi cho Ban mình, không được đề xuất chéo Ban.
- Thành viên `SUSPENDED` vẫn xem được đóng góp cá nhân tại `/taikhoan/trang-thai/` và `/api/v1/finance/my-contributions/`.
- `SEC-02`: Xuất CSV an toàn chống Formula Injection.
- `INV-04`: Cố vấn ở chế độ Hard Read-Only (xem được tổng quan, 403 trên mọi mutation).
"""
from __future__ import annotations

import io
from datetime import date, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventCategory, EventStatus, EventVisibility
from operations.models import ClubEventApprovalStatus, ClubEventProfile, ClubEventScope
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    Position,
    PositionCode,
)
from organization.services import (
    appoint_officer,
    approve_club_member,
    bootstrap_organization_catalog,
    grant_delegated_permissions,
)
from organizing.models import Expense, ExpenseCategory
from organizing.services import delete_expense, save_expense

from .models import (
    AdjustmentDirection,
    ContributionStatus,
    FinancialTransaction,
    FundCategory,
    FundCategoryType,
    MemberContribution,
    TransactionStatus,
    TransactionType,
)
from .services import (
    bootstrap_finance_categories,
    compute_club_fund_summary,
    create_adjustment_transaction,
    create_financial_transaction,
    export_ledger_csv,
    record_member_contribution,
    review_financial_transaction,
    sync_legacy_expense_to_ledger,
)


class Phase5FinanceTests(TestCase):
    def setUp(self):
        bootstrap_organization_catalog()
        bootstrap_finance_categories()

        self.cat_dues = FundCategory.objects.get(code="THU-QUY")
        self.cat_sponsor = FundCategory.objects.get(code="THU-TAI-TRO")
        self.cat_event = FundCategory.objects.get(code="CHI-SU-KIEN")

        self.dept_cm = Department.objects.get(code="SPECIALTY")
        self.dept_tt = Department.objects.get(code="MEDIA_EVENT")

        self.server_admin = User.objects.create_superuser(
            username="srv_admin_fin", email="admin@fin.kmg", full_name="Admin Server Fin"
        )
        self.chairman = self._make_user("cn_fin", "Chủ nhiệm Fin", Role.LEAD)
        self.vice_chairman = self._make_user("pcn_fin", "Phó CN Fin", Role.LEAD)
        self.advisor = self._make_user("advisor_fin", "Cố vấn Fin", Role.MEMBER)
        self.head_cm = self._make_user("head_cm_fin", "Trưởng ban CM Fin", Role.LEAD)
        self.head_tt = self._make_user("head_tt_fin", "Trưởng ban TT Fin", Role.LEAD)
        self.member = self._make_user("member_fin", "Thành viên Fin", Role.MEMBER)
        self.suspended_member = self._make_user("susp_fin", "Thành viên Khoá Fin", Role.MEMBER)

        pos_cn = Position.objects.get(code=PositionCode.CHAIRMAN)
        pos_pcn = Position.objects.get(code=PositionCode.VICE_CHAIRMAN)
        pos_adv = Position.objects.get(code=PositionCode.ADVISOR)
        pos_head = Position.objects.get(code=PositionCode.DEPT_HEAD)

        appoint_officer(self.server_admin, self.chairman, pos_cn)
        appt_pcn = appoint_officer(self.server_admin, self.vice_chairman, pos_pcn)
        grant_delegated_permissions(
            self.chairman, appt_pcn, GrantBundleCode.PORTFOLIO_FINANCE_DOC, reason="Phụ trách tài chính"
        )
        appoint_officer(self.server_admin, self.advisor, pos_adv)
        appoint_officer(self.server_admin, self.head_cm, pos_head, department=self.dept_cm)
        appoint_officer(self.server_admin, self.head_tt, pos_head, department=self.dept_tt)

        for u, depts in [
            (self.chairman, [self.dept_cm, self.dept_tt]),
            (self.vice_chairman, [self.dept_tt]),
            (self.head_cm, [self.dept_cm]),
            (self.head_tt, [self.dept_tt]),
            (self.member, [self.dept_cm]),
        ]:
            approve_club_member(self.server_admin, u, departments=depts)

        approve_club_member(self.server_admin, self.suspended_member, departments=[self.dept_cm])
        cm_rec = self.suspended_member.club_membership_record
        cm_rec.status = ClubMembershipStatus.SUSPENDED
        cm_rec.save(update_fields=["status"])

    def _make_user(self, username: str, full_name: str, role: str) -> User:
        return User.objects.create_user(
            username=username,
            email=f"{username}@kmg.vn",
            full_name=full_name,
            role=role,
            password="password123",
            email_verified_at=timezone.now(),
        )

    def test_maker_checker_inv03_rejects_self_approval(self):
        """INV-03: Người lập phiếu (Maker) không được phép tự duyệt phiếu của chính mình."""
        tx = create_financial_transaction(
            self.chairman,
            tx_type=TransactionType.INCOME,
            category=self.cat_sponsor,
            title="Tài trợ Minishow Mùa Xuân",
            amount=5000000,
        )
        self.assertEqual(tx.status, TransactionStatus.PENDING_APPROVAL)

        # Chủ nhiệm cố tự duyệt -> Bị chặn INV-03
        with self.assertRaises(PermissionDenied):
            review_financial_transaction(self.chairman, tx, approve=True)

        # Phó chủ nhiệm có PORTFOLIO_FINANCE_DOC duyệt độc lập -> Hợp lệ
        reviewed = review_financial_transaction(self.vice_chairman, tx, approve=True)
        self.assertEqual(reviewed.status, TransactionStatus.CONFIRMED)
        self.assertEqual(reviewed.approved_by, self.vice_chairman)

    def test_confirmed_transaction_immutability(self):
        """Bất biến sổ cái: Giao dịch CONFIRMED không thể sửa đổi hoặc xoá; phải dùng ADJUSTMENT."""
        tx = create_financial_transaction(
            self.chairman,
            tx_type=TransactionType.INCOME,
            category=self.cat_sponsor,
            title="Tài trợ Đêm nhạc",
            amount=10000000,
        )
        review_financial_transaction(self.vice_chairman, tx, approve=True)
        tx.refresh_from_db()
        self.assertEqual(tx.status, TransactionStatus.CONFIRMED)

        # Thử sửa amount qua ORM -> Bị chặn ValidationError
        tx.amount = 12000000
        with self.assertRaises(ValidationError):
            tx.save()

        # Thử xoá -> Bị chặn ValidationError
        with self.assertRaises(ValidationError):
            tx.delete()

        # Lập bút toán điều chỉnh bổ sung 2 triệu
        adj = create_adjustment_transaction(
            self.chairman,
            tx,
            direction=AdjustmentDirection.CREDIT,
            amount=2000000,
            reason="Nhà tài trợ chuyển bổ sung phần kinh phí phát sinh",
        )
        self.assertEqual(adj.status, TransactionStatus.PENDING_APPROVAL)
        self.assertEqual(adj.adjusted_from, tx)

        review_financial_transaction(self.vice_chairman, adj, approve=True)
        summary = compute_club_fund_summary()
        self.assertEqual(summary["confirmed_income"], 12000000)

    def test_cm03_bridge_locks_legacy_expense_after_confirmation(self):
        """CM-03 Bridge: Khoản chi organizing.Expense bị khoá sửa/xoá khi phiếu sổ cái đã CONFIRMED."""
        ev = Event.objects.create(
            name="Đêm nhạc Acoustics",
            category=EventCategory.MUSIC,
            starts_at=timezone.now() + timedelta(days=10),
            ends_at=timezone.now() + timedelta(days=10, hours=3),
            register_deadline=timezone.now() + timedelta(days=9),
            location="Hội trường A",
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        legacy_exp = Expense.objects.create(
            event=ev,
            title="Thuê loa đài sân khấu",
            amount=1500000,
            category=ExpenseCategory.EQUIPMENT,
            spent_on=date(2026, 5, 1),
            created_by=self.chairman,
        )

        # Khi chưa kết chuyển hoặc chưa CONFIRMED, sửa bình thường
        legacy_exp.title = "Thuê loa đài sân khấu lớn"
        save_expense(self.chairman, legacy_exp, is_new=False)

        # Kết chuyển lên sổ cái quỹ
        tx_bridge = sync_legacy_expense_to_ledger(self.chairman, legacy_exp)
        self.assertEqual(tx_bridge.status, TransactionStatus.PENDING_APPROVAL)

        # Checker duyệt CONFIRMED
        review_financial_transaction(self.vice_chairman, tx_bridge, approve=True)
        legacy_exp.refresh_from_db()

        # Thử sửa hoặc xoá -> PermissionDenied (CM-03)
        with self.assertRaises(PermissionDenied):
            save_expense(self.chairman, legacy_exp, is_new=False)
        with self.assertRaises(PermissionDenied):
            delete_expense(self.chairman, legacy_exp)

    def test_pa06_dept_head_expense_proposal_isolation(self):
        """PA-06: Trưởng ban CM được đề xuất chi cho Ban CM, nhưng bị chặn khi đề xuất cho Ban TT."""
        # Trưởng ban CM đề xuất cho Ban CM -> Hợp lệ
        tx_cm = create_financial_transaction(
            self.head_cm,
            tx_type=TransactionType.EXPENSE,
            category=self.cat_event,
            title="Dây đàn guitar dự phòng",
            amount=300000,
            department=self.dept_cm,
        )
        self.assertEqual(tx_cm.department, self.dept_cm)

        # Trưởng ban CM cố đề xuất chi cho Ban Truyền thông -> Bị chặn PA-06
        with self.assertRaises(PermissionDenied):
            create_financial_transaction(
                self.head_cm,
                tx_type=TransactionType.EXPENSE,
                category=self.cat_event,
                title="In poster truyền thông",
                amount=500000,
                department=self.dept_tt,
            )

    def test_suspended_member_can_view_own_contributions(self):
        """Thành viên SUSPENDED xem được đóng góp của mình tại /taikhoan/trang-thai/ và API /my-contributions/."""
        contrib = record_member_contribution(
            self.chairman,
            member=self.suspended_member,
            period_label="2026-HK1",
            title="Quỹ kỳ 1",
            amount=200000,
            department=self.dept_cm,
        )
        review_financial_transaction(self.vice_chairman, contrib.ledger_transaction, approve=True)

        c = Client()
        c.force_login(self.suspended_member)

        # Web portal /taikhoan/trang-thai/
        resp_web = c.get(reverse("accounts:membership_status"))
        self.assertEqual(resp_web.status_code, 200)
        self.assertContains(resp_web, "200000")

        # API /api/v1/finance/my-contributions/
        resp_api = c.get(reverse("api_v1:finance_my_contributions"))
        self.assertEqual(resp_api.status_code, 200)
        data = resp_api.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["amount"], 200000)

    def test_sec01_receipt_file_validation(self):
        """SEC-01: Chặn tải lên tệp chứng từ giả mạo HTML/SVG/script hoặc sai magic bytes."""
        fake_html_as_pdf = SimpleUploadedFile("fake.pdf", b"<html><script>alert(1)</script></html>", content_type="application/pdf")
        with self.assertRaises(Exception):
            create_financial_transaction(
                self.chairman,
                tx_type=TransactionType.INCOME,
                category=self.cat_sponsor,
                title="Thu tài trợ",
                amount=1000000,
                receipt_file=fake_html_as_pdf,
            )

        valid_pdf = SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 valid test pdf content here", content_type="application/pdf")
        tx_valid = create_financial_transaction(
            self.chairman,
            tx_type=TransactionType.INCOME,
            category=self.cat_sponsor,
            title="Thu tài trợ chuẩn",
            amount=1000000,
            receipt_file=valid_pdf,
        )
        self.assertTrue(bool(tx_valid.receipt))

    def test_sec02_csv_formula_injection_prevention(self):
        """SEC-02: Các ký tự công thức nguy hiểm (=, +, -, @) được bọc nháy đơn an toàn."""
        create_financial_transaction(
            self.chairman,
            tx_type=TransactionType.INCOME,
            category=self.cat_sponsor,
            title="=cmd|' /C calc'!A0",
            amount=1000000,
        )
        csv_text = export_ledger_csv(self.chairman)
        self.assertIn("'=cmd|", csv_text)

    def test_inv04_advisor_hard_read_only(self):
        """INV-04: Cố vấn xem được báo cáo tổng hợp & xuất CSV, nhưng 403 trên mọi thao tác ghi."""
        self.assertFalse(self.advisor.has_perm("finance.add_financialtransaction"))
        c = Client()
        c.force_login(self.advisor)

        # Xem tổng quan -> 200 OK
        resp_hub = c.get(reverse("finance:hub"))
        self.assertEqual(resp_hub.status_code, 200)
        self.assertContains(resp_hub, "INV-04")

        # Cố lập phiếu qua Web POST -> 403
        resp_create = c.post(
            reverse("finance:hub"),
            {"action": "create_transaction", "title": "Chi trái phép", "amount": 1000000},
        )
        self.assertEqual(resp_create.status_code, 403)

        # Cố lập phiếu qua REST API -> 403
        resp_api = c.post(
            reverse("api_v1:finance_transactions"),
            data='{"tx_type": "INCOME", "category": "THU-QUY", "title": "Test", "amount": 1000}',
            content_type="application/json",
        )
        self.assertEqual(resp_api.status_code, 403)
