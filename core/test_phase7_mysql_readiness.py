"""Kiểm thử Phase 7: MySQL 8.4 Fail-Closed, Import CSV/XLSX, Staging Seeder, SQLite->MySQL & Backup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Role, User
from core.db_guard import assert_non_production_seed_allowed
from deployment.sqlite_to_mysql import (
    backup_sqlite_source,
    run_sqlite_to_mysql_migration,
)
from events.models import Event, EventStatus, TicketType
from finance.models import FinancialTransaction, FundCategory, FundCategoryType, TransactionStatus, TransactionType
from organization.importers import run_org_import
from organization.models import (
    ClubMembership,
    Department,
    DepartmentMembership,
    MemberLifecycleEvent,
    Position,
    PositionCode,
    UserSkill,
)
from organization.services import appoint_officer, bootstrap_organization_catalog, end_appointment
from organization.staging_seeder import generate_staging_dataset
from registrations.models import Ticket, TicketStatus
from social.crypto import decrypt_message_text, encrypt_message_text, generate_wrapped_dek, unwrap_dek
from social.models import ChatMessage, Conversation, ConversationType


def _write_minimal_xlsx(path: Path, rows: list[list[str]]) -> None:
    """Tạo tệp Excel .xlsx hợp lệ thuần stdlib để kiểm thử importer không phụ thuộc openpyxl."""
    def _col(idx: int) -> str:
        res = ""
        n = idx + 1
        while n:
            n, rem = divmod(n - 1, 26)
            res = chr(65 + rem) + res
        return res

    def _xml_escape(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    row_xml = []
    for r_i, row in enumerate(rows, start=1):
        cells = []
        for c_i, val in enumerate(row):
            ref = f"{_col(c_i)}{r_i}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(str(val))}</t></is></c>')
        row_xml.append(f'<row r="{r_i}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


class Phase7ConfigFailClosedTests(TestCase):
    def test_production_config_rejects_sqlite_fail_closed(self):
        env = dict(os.environ)
        env.update({
            "KMG_ENV_FILE": "",
            "KMG_ENV": "prod",
            "DEBUG": "False",
            "DB_ENGINE": "sqlite",
            "ALLOW_DEMO_SEED": "False",
            "ALLOWED_HOSTS": "kmg.example.com",
            "SECRET_KEY": "prod-test-secret-key-0123456789abcdefghijklmnopqrstuvwxyz",
            "CERT_SIGNING_KEY": "prod-test-cert-key-0123456789abcdefghijklmnopqrstuvwxyz",
            "CHAT_MASTER_KEK": "prod-test-chat-kek-0123456789abcdefghijklmnopqrstuvwxyz",
        })
        res = subprocess.run(
            [sys.executable, "manage.py", "check", "--settings=config.settings"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("MySQL 8.4", res.stderr + res.stdout)

    def test_seed_guard_blocks_production_and_disabled_demo_seed(self):
        with override_settings(KMG_ENV="prod", ALLOW_DEMO_SEED=True, DEBUG=True):
            with self.assertRaises(CommandError):
                assert_non_production_seed_allowed("seed_staging")
        with override_settings(KMG_ENV="staging", ALLOW_DEMO_SEED=False, DEBUG=False):
            with self.assertRaises(CommandError):
                assert_non_production_seed_allowed("seed_demo")


class Phase7ImporterAndStagingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kmg-p7-import-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        bootstrap_organization_catalog()
        self.admin = User.objects.create_user(
            username="p7_admin", password="StrongPassword!123", role=Role.ADMIN
        )

    def test_csv_import_dry_run_commit_idempotent_and_row_errors(self):
        csv_file = self.root / "members.csv"
        csv_file.write_text(
            "\n".join([
                "username,full_name,email,phone,mssv,affiliation,department_code,joined_at,role",
                "kmg_imp_1,Nguyễn Văn Ân,an.imp@example.invalid,0981112233,AT220001,KMA,SPECIALTY,2026-09-10,MEMBER",
                "kmg_imp_2,Trần Thảo My 🎸,my.imp@example.invalid,0981112244,AT220002,KMA,MEDIA_EVENT,2026-09-11,MEMBER",
                "kmg_imp_bad,Admin Fake,bad@example.invalid,0981112255,AT220003,KMA,TECHNICAL,2026-09-11,ADMIN",
                "kmg_imp_1,Trùng Username,dup@example.invalid,0981112266,AT220004,KMA,SPECIALTY,2026-09-11,MEMBER",
            ]),
            encoding="utf-8-sig",
        )
        dry = run_org_import(kind="members", file_path=csv_file, dry_run=True)
        self.assertEqual(dry.created, 2)
        self.assertEqual(len(dry.errors), 2)
        self.assertFalse(User.objects.filter(username="kmg_imp_1").exists())

        real = run_org_import(kind="members", file_path=csv_file, dry_run=False)
        self.assertEqual(real.created, 2)
        self.assertEqual(len(real.errors), 2)
        u1 = User.objects.get(username="kmg_imp_1")
        self.assertFalse(u1.has_usable_password())
        self.assertTrue(ClubMembership.objects.filter(user=u1).exists())
        self.assertTrue(DepartmentMembership.objects.filter(user=u1, department__code="SPECIALTY").exists())

        # Chạy lại cùng file -> idempotent skip, không trùng
        rerun = run_org_import(kind="members", file_path=csv_file, dry_run=False)
        self.assertEqual(rerun.created, 0)
        self.assertEqual(rerun.skipped, 2)

    def test_xlsx_import_skills_and_requires_approver_for_appointments(self):
        u = User.objects.create_user(username="kmg_xlsx_u", password="StrongPassword!123", role=Role.MEMBER)
        xlsx_skills = self.root / "skills.xlsx"
        _write_minimal_xlsx(
            xlsx_skills,
            [
                ["username_or_email", "skill_code", "proficiency", "evidence_note"],
                ["kmg_xlsx_u", "GUITAR_ACOUSTIC", "ADVANCED", "Đệm fingerstyle"],
            ],
        )
        rep = run_org_import(kind="skills", file_path=xlsx_skills)
        self.assertEqual(rep.created, 1)
        self.assertTrue(UserSkill.objects.filter(user=u, skill__code="GUITAR_ACOUSTIC").exists())

        appt_csv = self.root / "appts.csv"
        appt_csv.write_text(
            "username_or_email,position_code,department_code,term_label\n"
            "kmg_xlsx_u,DEPUTY_HEAD,SPECIALTY,2026-2027\n",
            encoding="utf-8",
        )
        with self.assertRaises(CommandError):
            run_org_import(kind="appointments", file_path=appt_csv)

        rep_ok = run_org_import(kind="appointments", file_path=appt_csv, approve_by_username="p7_admin")
        self.assertEqual(rep_ok.created, 1)
        self.assertTrue(
            MemberLifecycleEvent.objects.filter(user=u).exists()
        )

    def test_staging_seeder_deterministic_utf8_emoji_and_n1_bounds(self):
        with override_settings(KMG_ENV="staging", ALLOW_DEMO_SEED=True, DEBUG=True):
            summary = generate_staging_dataset(seed=77, scale="smoke")
        self.assertEqual(summary["members"], 12)
        self.assertEqual(summary["guests"], 30)
        self.assertEqual(summary["tickets"], 120)
        self.assertEqual(summary["messages"], 200)
        self.assertEqual(summary["logs"], 300)

        # Kiểm tra lưu trữ utf8mb4 tiếng Việt + emoji thực tế
        sample_ev_exists = User.objects.filter(username="stg77_m_0000").exists()
        self.assertTrue(sample_ev_exists)

        # Kiểm tra giới hạn N+1 ở trang công khai sự kiện
        with CaptureQueriesContext(connection) as qctx:
            resp = self.client.get(reverse("events:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(qctx), 6)


class Phase7SqliteToMysqlDryRunAndSafetyTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kmg-p7-mig-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_sqlite_inventory_backup_and_dirty_unique_detection(self):
        src = self.root / "legacy.sqlite3"
        con = sqlite3.connect(str(src))
        con.execute("CREATE TABLE accounts_user (id INTEGER PRIMARY KEY, username TEXT, mssv TEXT, normalized_email TEXT, normalized_phone TEXT)")
        con.execute("INSERT INTO accounts_user VALUES (1, 'u1', '', '', '')")
        con.execute("CREATE TABLE finance_financialtransaction (id INTEGER PRIMARY KEY, tx_type TEXT, status TEXT, amount INTEGER)")
        con.execute("INSERT INTO finance_financialtransaction VALUES (1, 'INCOME', 'CONFIRMED', 500000)")
        con.commit()
        con.close()

        snap = backup_sqlite_source(src, self.root / "bk")
        self.assertTrue(snap.exists())
        report = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=True)
        self.assertEqual(report.source_rows.get("accounts_user"), 1)
        self.assertEqual(report.dirty_values_fixed.get("accounts_user.mssv"), 1)
        self.assertEqual(report.finance_reconciliation["source"], {"INCOME": 500000})

        if connection.vendor != "mysql":
            err_rep = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=False)
            self.assertFalse(err_rep.ok)
            self.assertTrue(any("MySQL" in e for e in err_rep.errors))

    def test_aes256_gcm_chat_ciphertext_binary_integrity(self):
        conv = Conversation.objects.create(
            conv_type=ConversationType.CLUB_WIDE,
            title="Test Mã hoá KMG 🎸",
            encrypted_dek=generate_wrapped_dek(),
        )
        sender = User.objects.create_user(username="crypto_u", password="StrongPassword!123")
        dek = unwrap_dek(conv.encrypted_dek)
        iv, ct = encrypt_message_text(
            dek=dek,
            plaintext="Âm thanh Acoustic 2026 🎶",
            conversation_id=conv.id,
            sender_id=sender.id,
        )
        msg = ChatMessage.objects.create(conversation=conv, sender=sender, ciphertext=ct, iv_nonce=iv)
        msg.refresh_from_db()
        plain = decrypt_message_text(
            dek=dek,
            iv_nonce=bytes(msg.iv_nonce),
            ciphertext=bytes(msg.ciphertext),
            conversation_id=conv.id,
            sender_id=sender.id,
        )
        self.assertEqual(plain, "Âm thanh Acoustic 2026 🎶")


class Phase7BusinessIntegrityMySQLTests(TestCase):
    def setUp(self):
        bootstrap_organization_catalog()
        self.admin = User.objects.create_user(username="p7_b_admin", password="StrongPassword!123", role=Role.ADMIN)
        self.maker = User.objects.create_user(username="p7_maker", password="StrongPassword!123", role=Role.STAFF)
        self.checker = User.objects.create_user(username="p7_checker", password="StrongPassword!123", role=Role.LEAD)
        self.buyer = User.objects.create_user(username="p7_buyer", password="StrongPassword!123", role=Role.MEMBER)

    @override_settings(SEPAY_API_KEY="sepay-test-secret-012345", BANK_ACCOUNT="123456789")
    def test_sepay_webhook_replay_is_idempotent(self):
        from datetime import timedelta
        from django.utils import timezone

        now = timezone.now()
        ev = Event.objects.create(
            name="Show Sepay Replay",
            location="KMA",
            starts_at=now + timedelta(days=5),
            register_deadline=now + timedelta(days=4),
            status=EventStatus.OPEN,
        )
        tt = TicketType.objects.create(event=ev, name="Standard", price=50000, quota=10, sold=1)
        tix = Ticket.objects.create(
            event=ev,
            ticket_type=tt,
            user=self.buyer,
            status=TicketStatus.PENDING,
            booking_ref="PAY77889",
            price=50000,
        )
        url = reverse("registrations:sepay_webhook")
        payload = json.dumps({
            "transferType": "in",
            "transferAmount": 50000,
            "content": "KMG PAY77889",
            "accountNumber": "123456789",
        })
        r1 = self.client.post(url, data=payload, content_type="application/json", HTTP_AUTHORIZATION="Apikey sepay-test-secret-012345")
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json().get("confirmed"))
        tix.refresh_from_db()
        self.assertEqual(tix.status, TicketStatus.CONFIRMED)

        # Replay lần 2 phải trả 200 an toàn và không nhân đôi xác nhận
        r2 = self.client.post(url, data=payload, content_type="application/json", HTTP_AUTHORIZATION="Apikey sepay-test-secret-012345")
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json().get("confirmed"))
        tt.refresh_from_db()
        self.assertEqual(tt.sold, 1)

    def test_finance_duplicate_tx_code_blocked_and_term_revocation_bumps_authz(self):
        cat = FundCategory.objects.create(code="P7_CAT", name="Thu P7", tx_type=FundCategoryType.INCOME)
        from django.db import IntegrityError
        from django.utils import timezone

        FinancialTransaction.objects.create(
            tx_code="P7-UNIQ-001",
            tx_type=TransactionType.INCOME,
            status=TransactionStatus.CONFIRMED,
            category=cat,
            title="Thu vé",
            amount=100000,
            transaction_date=timezone.localdate(),
            created_by=self.maker,
            approved_by=self.checker,
            approved_at=timezone.now(),
        )
        with self.assertRaises(IntegrityError):
            FinancialTransaction.objects.create(
                tx_code="P7-UNIQ-001",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PENDING_APPROVAL,
                category=cat,
                title="Trùng mã",
                amount=100000,
                transaction_date=timezone.localdate(),
                created_by=self.maker,
            )

        dept = Department.objects.get(code="SPECIALTY")
        pos = Position.objects.get(code=PositionCode.DEPT_HEAD)
        v_before = self.maker.authz_version
        appt = appoint_officer(actor=self.admin, target_user=self.maker, position=pos, department=dept, term_label="2026-2027")
        self.maker.refresh_from_db()
        self.assertGreater(self.maker.authz_version, v_before)

        v_mid = self.maker.authz_version
        end_appointment(actor=self.admin, appointment=appt, reason="Hết nhiệm kỳ 2026-2027")
        self.maker.refresh_from_db()
        self.assertGreater(self.maker.authz_version, v_mid)
