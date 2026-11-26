"""Phase 6 QA coverage tests for finance.views and finance.api_views."""
from __future__ import annotations

import json
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from finance.models import (
    AdjustmentDirection,
    FinancialTransaction,
    TransactionStatus,
    TransactionType,
)
from finance.services import create_financial_transaction, review_financial_transaction
from finance.test_phase5_finance import Phase5FinanceTests


class FinanceViewsAndApiCoverageTests(Phase5FinanceTests):
    def test_finance_hub_web_create_contribution_and_guards(self):
        self.client.force_login(self.chairman)
        resp = self.client.get(reverse("finance:hub"))
        self.assertEqual(resp.status_code, 200)

        # Create transaction via web POST
        png = SimpleUploadedFile("r.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, content_type="image/png")
        post_resp = self.client.post(
            reverse("finance:hub"),
            {
                "action": "create_transaction",
                "tx_type": TransactionType.EXPENSE,
                "category_id": self.cat_event.pk,
                "department_id": self.dept_cm.pk,
                "title": "Thuê loa hội trường",
                "amount": "450000",
                "transaction_date": date.today().isoformat(),
                "description": "Chi phí âm thanh",
                "receipt": png,
            },
        )
        self.assertEqual(post_resp.status_code, 302)
        tx = FinancialTransaction.objects.get(title="Thuê loa hội trường")
        self.assertEqual(tx.status, TransactionStatus.PENDING_APPROVAL)

        # Record contribution via web POST
        contrib_resp = self.client.post(
            reverse("finance:hub"),
            {
                "action": "record_contribution",
                "member_id": self.member.pk,
                "department_id": self.dept_cm.pk,
                "period_label": "2026-11",
                "title": "Quỹ tháng 11",
                "amount": "50000",
                "paid_on": date.today().isoformat(),
            },
        )
        self.assertEqual(contrib_resp.status_code, 302)

        # Advisor Hard Read-Only on web POST -> 403
        self.client.force_login(self.advisor)
        self.assertEqual(self.client.get(reverse("finance:hub")).status_code, 200)
        self.assertEqual(self.client.post(reverse("finance:hub"), {"action": "create_transaction"}).status_code, 403)

    def test_transaction_detail_review_adjust_receipt_and_csv_web(self):
        tx = create_financial_transaction(
            self.head_cm,
            tx_type=TransactionType.EXPENSE,
            category=self.cat_event,
            department=self.dept_cm,
            title="Mua dây đàn",
            amount=200000,
            receipt_file=SimpleUploadedFile("hd.png", b"\x89PNG\r\n\x1a\n" + b"x" * 20, content_type="image/png"),
        )
        # Checker (vice_chairman) approves
        self.client.force_login(self.vice_chairman)
        detail_url = reverse("finance:transaction_detail", args=[tx.pk])
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(self.client.post(detail_url, {"action": "approve"}).status_code, 302)
        tx.refresh_from_db()
        self.assertEqual(tx.status, TransactionStatus.CONFIRMED)

        # Receipt download headers
        rcp_resp = self.client.get(reverse("finance:transaction_receipt", args=[tx.pk]))
        self.assertEqual(rcp_resp.status_code, 200)
        self.assertEqual(rcp_resp["X-Content-Type-Options"], "nosniff")
        self.assertEqual(rcp_resp["Cache-Control"], "private, no-store")
        _ = b"".join(rcp_resp.streaming_content)

        # Adjustment via web POST
        adj_resp = self.client.post(
            detail_url,
            {"action": "adjust", "direction": AdjustmentDirection.DEBIT, "amount": "50000", "reason": "Bổ sung VAT"},
        )
        self.assertEqual(adj_resp.status_code, 302)

        # Ledger CSV export via web
        csv_resp = self.client.get(reverse("finance:ledger_csv"))
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("Mua dây đàn", csv_resp.content.decode("utf-8"))

        # Outsider member forbidden on transaction detail & receipt
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(detail_url).status_code, 403)
        self.assertEqual(self.client.get(reverse("finance:transaction_receipt", args=[tx.pk])).status_code, 403)

    def test_finance_json_api_endpoints(self):
        tx = create_financial_transaction(
            self.chairman,
            tx_type=TransactionType.INCOME,
            category=self.cat_sponsor,
            title="Tài trợ API Test",
            amount=1000000,
        )
        self.client.force_login(self.vice_chairman)

        summary = self.client.get(reverse("api_v1:finance_summary"))
        self.assertEqual(summary.status_code, 200)
        self.assertTrue(summary.json()["ok"])

        detail = self.client.get(reverse("api_v1:finance_transaction_detail", args=[tx.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["tx_code"], tx.tx_code)

        bad_decision = self.client.post(
            reverse("api_v1:finance_transaction_review", args=[tx.pk]),
            data=json.dumps({"decision": "MAYBE"}),
            content_type="application/json",
        )
        self.assertEqual(bad_decision.status_code, 400)

        approve = self.client.post(
            reverse("api_v1:finance_transaction_review", args=[tx.pk]),
            data=json.dumps({"decision": "APPROVE"}),
            content_type="application/json",
        )
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()["data"]["status"], TransactionStatus.CONFIRMED)

        adjust = self.client.post(
            reverse("api_v1:finance_transaction_adjust", args=[tx.pk]),
            data=json.dumps({"direction": AdjustmentDirection.CREDIT, "amount": 100000, "reason": "Thưởng thêm"}),
            content_type="application/json",
        )
        self.assertEqual(adjust.status_code, 201)

        contrib = self.client.post(
            reverse("api_v1:finance_contributions"),
            data=json.dumps({
                "member_id": self.member.pk,
                "department_id": self.dept_cm.pk,
                "period_label": "2026-12",
                "title": "Quỹ T12",
                "amount": 50000,
            }),
            content_type="application/json",
        )
        self.assertEqual(contrib.status_code, 201)

        csv_api = self.client.get(reverse("api_v1:finance_ledger_export"))
        self.assertEqual(csv_api.status_code, 200)

        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("api_v1:finance_summary")).status_code, 403)
        mine = self.client.get(reverse("api_v1:finance_my_contributions"))
        self.assertEqual(mine.status_code, 200)
        self.assertGreaterEqual(len(mine.json()["data"]), 1)
