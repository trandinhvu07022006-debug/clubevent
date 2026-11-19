"""Regression tests for the ORM and Django Admin paths around the ledger."""
from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Event
from organizing.models import Expense
from organizing.services import is_legacy_expense_locked

from .models import (
    FinancialTransaction, FundCategory, MemberContribution,
    TransactionStatus, TransactionType,
)


class LedgerSafetyTests(TestCase):
    def setUp(self):
        self.maker = User.objects.create_superuser("ledger_admin", "maker@example.test")
        self.checker = User.objects.create_user("ledger_checker", email="checker@example.test")
        self.category = FundCategory.objects.create(code="LEDGER-TEST", name="Test", tx_type="EXPENSE")
        self.event = Event.objects.create(
            name="Ledger event", starts_at=timezone.now() + timedelta(days=2),
            register_deadline=timezone.now() + timedelta(days=1), location="Test",
        )
        self.expense = Expense.objects.create(event=self.event, title="Sound", amount=100, created_by=self.maker)
        self.tx = FinancialTransaction.objects.create(
            tx_code="LEDGER-001", tx_type=TransactionType.EXPENSE, category=self.category,
            title="Sound", amount=100, legacy_expense=self.expense, created_by=self.maker,
        )
        self.stale_tx = FinancialTransaction.objects.get(pk=self.tx.pk)
        self.tx.status = TransactionStatus.CONFIRMED
        self.tx.approved_by = self.checker
        self.tx.approved_at = timezone.now()
        self.tx.save()

    def test_confirmed_queryset_update_and_bulk_update_are_rejected(self):
        with self.assertRaises(ValidationError):
            FinancialTransaction.objects.filter(pk=self.tx.pk).update(amount=200)
        self.tx.amount = 300
        with self.assertRaises(ValidationError):
            FinancialTransaction.objects.bulk_update([self.tx], ["amount"])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.amount, 100)

    def test_confirmed_queryset_and_stale_instance_delete_are_rejected(self):
        with self.assertRaises(ValidationError):
            FinancialTransaction.objects.filter(pk=self.tx.pk).delete()
        with self.assertRaises(ValidationError):
            self.stale_tx.delete()
        self.assertTrue(FinancialTransaction.objects.filter(pk=self.tx.pk).exists())

    def test_confirmed_expense_all_orm_mutations_are_rejected(self):
        self.expense.amount = 999
        for mutation in (
            lambda: self.expense.save(),
            lambda: self.expense.delete(),
            lambda: Expense.objects.filter(pk=self.expense.pk).update(amount=999),
            lambda: Expense.objects.bulk_update([self.expense], ["amount"]),
            lambda: Expense.objects.filter(pk=self.expense.pk).delete(),
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                mutation()
        self.expense.refresh_from_db()
        self.assertEqual(self.expense.amount, 100)

    def test_event_cascade_cannot_remove_confirmed_expense(self):
        with self.assertRaises(ValidationError):
            # Collector dùng atomic(savepoint=False); giữ savepoint ngoài để
            # kiểm tra dữ liệu còn nguyên sau khi cascade bị từ chối.
            with transaction.atomic():
                self.event.delete()
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.legacy_expense_id, self.expense.pk)

    def test_stale_reverse_relation_does_not_hide_confirmed_ledger(self):
        self.expense._state.fields_cache["ledger_transaction"] = self.stale_tx
        self.assertTrue(is_legacy_expense_locked(self.expense))

    def test_admin_is_read_only_even_for_superuser(self):
        request = RequestFactory().get("/admin/")
        request.user = self.maker
        for model, instance in ((FinancialTransaction, self.tx), (MemberContribution, None), (Expense, self.expense)):
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertTrue(model_admin.has_view_permission(request, instance))
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request, instance))
                self.assertFalse(model_admin.has_delete_permission(request, instance))
                self.assertFalse(model_admin.has_delete_permission(request))
                self.assertNotIn("delete_selected", model_admin.get_actions(request))

    def test_admin_posts_cannot_forge_approval_or_delete_ledger(self):
        self.client.force_login(self.maker)
        url = reverse("admin:finance_financialtransaction_change", args=[self.tx.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"status": "CONFIRMED", "approved_by": self.maker.pk}).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:finance_financialtransaction_add"), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:finance_financialtransaction_delete", args=[self.tx.pk]), {"post": "yes"}).status_code, 403)
        self.client.post(reverse("admin:finance_financialtransaction_changelist"), {
            "action": "delete_selected", "_selected_action": [self.tx.pk], "post": "yes",
        })
        self.assertTrue(FinancialTransaction.objects.filter(pk=self.tx.pk).exists())

    def test_model_rejects_self_approval_and_missing_checker(self):
        for checker in (None, self.maker):
            with self.subTest(checker=checker), self.assertRaises(ValidationError):
                FinancialTransaction.objects.create(
                    tx_code="BAD-APPROVAL", tx_type="EXPENSE", category=self.category,
                    title="Invalid", amount=100, created_by=self.maker,
                    status=TransactionStatus.CONFIRMED, approved_by=checker, approved_at=timezone.now(),
                )

    def test_bulk_creation_cannot_skip_approval_validation(self):
        tx = FinancialTransaction(
            tx_code="BAD-BULK", tx_type="EXPENSE", category=self.category,
            title="Invalid", amount=100, created_by=self.maker,
            status=TransactionStatus.CONFIRMED, approved_by=self.maker, approved_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            FinancialTransaction.objects.bulk_create([tx])

    def test_database_constraint_blocks_forged_checker(self):
        # Dùng QuerySet gốc để thực sự kiểm tra CHECK của DB, không chỉ guard Python.
        for update in ({"approved_by_id": self.maker.pk}, {"approved_by_id": None}, {"approved_at": None}):
            with self.subTest(update=update), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    models.QuerySet(model=FinancialTransaction).filter(pk=self.tx.pk).update(**update)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.approved_by_id, self.checker.pk)

    def test_pending_ledger_can_be_edited_and_deleted_normally(self):
        draft = FinancialTransaction.objects.create(
            tx_code="LEDGER-DRAFT", tx_type=TransactionType.EXPENSE, category=self.category,
            title="Draft", amount=50, created_by=self.maker,
        )
        draft.amount = 60
        draft.save(update_fields=["amount"])
        draft.refresh_from_db()
        self.assertEqual(draft.amount, 60)
        draft.delete()
        self.assertFalse(FinancialTransaction.objects.filter(tx_code="LEDGER-DRAFT").exists())

    def test_changed_source_requires_reconciliation_before_confirmation(self):
        expense = Expense.objects.create(event=self.event, title="Draft source", amount=50)
        draft = FinancialTransaction.objects.create(
            tx_code="LEDGER-SOURCE", tx_type=TransactionType.EXPENSE, category=self.category,
            title="Draft source", amount=50, legacy_expense=expense, created_by=self.maker,
        )
        Expense.objects.filter(pk=expense.pk).update(amount=60)
        draft.status = TransactionStatus.CONFIRMED
        draft.approved_by = self.checker
        draft.approved_at = timezone.now()
        with self.assertRaises(ValidationError):
            draft.save()
        draft.refresh_from_db()
        self.assertEqual(draft.status, TransactionStatus.PENDING_APPROVAL)

    def test_pending_records_still_allow_normal_edits_and_delete(self):
        expense = Expense.objects.create(event=self.event, title="Pending", amount=50)
        Expense.objects.filter(pk=expense.pk).update(amount=60)
        expense.refresh_from_db()
        self.assertEqual(expense.amount, 60)
        expense.amount = 70
        Expense.objects.bulk_update([expense], ["amount"])
        expense.delete()
        self.assertFalse(Expense.objects.filter(pk=expense.pk).exists())
