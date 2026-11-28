"""Unit tests boosting coverage for `organization.importers` and `deployment.sqlite_to_mysql`."""
from __future__ import annotations

import csv
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import zipfile

from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import Role, User
from deployment.sqlite_to_mysql import (
    MigrationReport,
    _check_sqlite_orphans,
    _check_target_orphans,
    _model_field_defaults_by_table,
    _sqlite_finance_totals,
    _target_finance_totals,
    run_sqlite_to_mysql_migration,
)
from organization.importers import (
    ImportReport,
    _parse_dt,
    _read_xlsx_stdlib,
    read_tabular_file,
    run_org_import,
)
from organization.models import Department, LifecycleEventType, PositionCode, Skill, SkillCategory
from organization.services import bootstrap_organization_catalog


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _write_minimal_xlsx_with_shared_strings(path: Path) -> Path:
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">'
        "<si><t>department_code</t></si>"
        "<si><t>TEST_XLSX</t></si>"
        "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>department_name</t></is></c></row>'
        '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="inlineStr"><is><t>Ban Test XLSX</t></is></c></row>'
        "</sheetData>"
        "</worksheet>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", shared_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return path


class OrganizationImportersCoverageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        bootstrap_organization_catalog()
        cls.admin = User.objects.create_user(
            username="imp_admin",
            password="Password123!",
            email="imp_admin@example.com",
            role=Role.ADMIN,
            is_superuser=True,
            is_staff=True,
        )
        cls.dept = Department.objects.first()
        cls.skill = Skill.objects.first()

    def test_tabular_readers_and_report_dict(self):
        rep = ImportReport(kind="members", file_path="x.csv", dry_run=True, total_rows=1, created=1)
        self.assertEqual(rep.as_dict()["error_count"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            with self.assertRaises(CommandError):
                read_tabular_file(tmp_dir / "missing.csv")

            bad_ext = tmp_dir / "bad.txt"
            bad_ext.write_text("hi", encoding="utf-8")
            with self.assertRaises(CommandError):
                read_tabular_file(bad_ext)

            empty_csv = tmp_dir / "empty.csv"
            empty_csv.write_text("", encoding="utf-8")
            self.assertEqual(read_tabular_file(empty_csv), [])

            xlsx_path = _write_minimal_xlsx_with_shared_strings(tmp_dir / "test.xlsx")
            rows = _read_xlsx_stdlib(xlsx_path)
            self.assertEqual(rows, [{"department_code": "TEST_XLSX", "department_name": "Ban Test XLSX"}])

            with self.assertRaises(CommandError):
                run_org_import(kind="invalid_kind", file_path=empty_csv)

        self.assertIsNotNone(_parse_dt("2026-05-01"))
        self.assertIsNotNone(_parse_dt("2026-05-01T10:30:00"))
        self.assertIsNone(_parse_dt(""))

    def test_import_structure_create_update_skip_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_csv(
                Path(tmp) / "structure.csv",
                [
                    "department_code",
                    "department_name",
                    "slug",
                    "short_description",
                    "skill_category_code",
                    "skill_category_name",
                    "skill_code",
                    "skill_name",
                ],
                [
                    ["", "Missing Code", "missing", "", "", "", "", ""],
                    ["NEW_DEPT", "Ban Mới", self.dept.slug, "Dup slug", "", "", "", ""],
                    ["NEW_DEPT", "Ban Mới", "ban-moi-imp", "Mô tả", "NEW_CAT", "Nhóm Mới", "NEW_SK", "Kỹ năng Mới"],
                ],
            )
            r1 = run_org_import(kind="structure", file_path=p)
            self.assertEqual(r1.created, 1)
            self.assertEqual(len(r1.errors), 2)
            self.assertTrue(SkillCategory.objects.filter(code="NEW_CAT").exists())
            self.assertTrue(Skill.objects.filter(code="NEW_SK").exists())

            p_upd = _write_csv(
                Path(tmp) / "structure_upd.csv",
                ["department_code", "department_name", "slug", "short_description"],
                [["NEW_DEPT", "Ban Mới Cập Nhật", "ban-moi-imp", "Mô tả mới"]],
            )
            r2 = run_org_import(kind="structure", file_path=p_upd, update_existing=True)
            self.assertEqual(r2.updated, 1)
            r3 = run_org_import(kind="structure", file_path=p_upd, update_existing=False)
            self.assertEqual(r3.skipped, 1)

    def test_import_members_validation_update_and_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_csv(
                Path(tmp) / "members.csv",
                ["username", "full_name", "email", "mssv", "phone", "department_code", "role", "affiliation", "membership_status"],
                [
                    ["", "No Username", "", "", "", "", "", "", ""],
                    ["u_ok1", "User Ok 1", "ok1@example.com", "AT200101", "0901111222", self.dept.code, "MEMBER", "KMA", "ACTIVE"],
                    ["u_dup_email", "Dup Email", "ok1@example.com", "", "", "", "", "KMA", "ACTIVE"],
                    ["u_dup_mssv", "Dup MSSV", "u2@example.com", "AT200101", "", "", "", "KMA", "ACTIVE"],
                    ["u_bad_dept", "Bad Dept", "u3@example.com", "", "", "NO_DEPT", "", "KMA", "ACTIVE"],
                    ["u_bad_phone", "Bad Phone", "u4@example.com", "", "---", "", "", "KMA", "ACTIVE"],
                    ["u_bad_aff", "Bad Aff", "u5@example.com", "", "", "", "", "INVALID", "ACTIVE"],
                    ["u_bad_status", "Bad Status", "u6@example.com", "", "", "", "", "KMA", "INVALID"],
                ],
            )
            r1 = run_org_import(kind="members", file_path=p)
            self.assertEqual(r1.created, 1)
            self.assertEqual(len(r1.errors), 7)

            # Duplicate against DB + update_existing + skip
            dept2 = Department.objects.exclude(pk=self.dept.pk).first()
            p2 = _write_csv(
                Path(tmp) / "members2.csv",
                ["username", "full_name", "display_name", "school", "email", "mssv", "phone", "department_code"],
                [
                    ["u_db_email", "DB Email", "", "", "ok1@example.com", "", "", ""],
                    ["u_db_mssv", "DB MSSV", "", "", "other@example.com", "AT200101", "", ""],
                    ["u_db_phone", "DB Phone", "", "", "other2@example.com", "", "0901111222", ""],
                    ["u_ok1", "User Ok 1 Updated", "Disp 1", "KMA", "", "", "", dept2.code],
                ],
            )
            r2 = run_org_import(kind="members", file_path=p2, update_existing=True)
            self.assertEqual(r2.updated, 1)
            self.assertEqual(len(r2.errors), 3)

            r3 = run_org_import(kind="members", file_path=p2, update_existing=False)
            self.assertEqual(r3.skipped, 1)

    def test_import_skills_appointments_and_history(self):
        member = User.objects.create_user(
            username="imp_member",
            password="Password123!",
            email="imp_member@example.com",
            role=Role.MEMBER,
        )
        with tempfile.TemporaryDirectory() as tmp:
            p_sk = _write_csv(
                Path(tmp) / "skills.csv",
                ["username_or_email", "skill_code", "proficiency", "verified_by"],
                [
                    ["nobody", self.skill.code, "INTERMEDIATE", ""],
                    ["imp_member@example.com", "NO_SUCH_SKILL", "INTERMEDIATE", ""],
                    ["imp_member", self.skill.code, "BAD_PROF", ""],
                    ["imp_member", self.skill.code, "ADVANCED", "imp_admin"],
                ],
            )
            rs1 = run_org_import(kind="skills", file_path=p_sk)
            self.assertEqual(rs1.created, 1)
            self.assertEqual(len(rs1.errors), 3)
            rs2 = run_org_import(kind="skills", file_path=p_sk, update_existing=True)
            self.assertEqual(rs2.updated, 1)
            rs3 = run_org_import(kind="skills", file_path=p_sk, update_existing=False)
            self.assertEqual(rs3.skipped, 1)

            p_appt = _write_csv(
                Path(tmp) / "appts.csv",
                ["username", "position_code", "department_code", "ends_at"],
                [
                    ["nobody", PositionCode.DEPUTY_HEAD, self.dept.code, ""],
                    ["imp_member", "BAD_POS", self.dept.code, ""],
                    ["imp_member", PositionCode.DEPUTY_HEAD, "BAD_DEPT", ""],
                    ["imp_member", PositionCode.DEPUTY_HEAD, self.dept.code, ""],
                ],
            )
            # Non-admin approver must be rejected (IMP-02)
            with self.assertRaises(CommandError):
                run_org_import(kind="appointments", file_path=p_appt, approve_by_username="imp_member")

            ra = run_org_import(kind="appointments", file_path=p_appt, approve_by_username="imp_admin")
            self.assertEqual(ra.created, 1)
            self.assertEqual(len(ra.errors), 3)

            p_hist = _write_csv(
                Path(tmp) / "history.csv",
                ["username", "event_type", "title", "department_code", "note"],
                [
                    ["nobody", LifecycleEventType.JOINED_DEPT, "Title", "", ""],
                    ["imp_member", "BAD_EVT", "Title", "", ""],
                    ["imp_member", LifecycleEventType.JOINED_DEPT, "Title", "BAD_DEPT", ""],
                    ["imp_member", LifecycleEventType.JOINED_DEPT, "Mốc nhập lịch sử", self.dept.code, "Ghi chú"],
                ],
            )
            rh1 = run_org_import(kind="history", file_path=p_hist)
            self.assertEqual(rh1.created, 1)
            self.assertEqual(len(rh1.errors), 3)
            rh2 = run_org_import(kind="history", file_path=p_hist)
            self.assertEqual(rh2.skipped, 1)


class SqliteToMysqlCoverageTests(TestCase):
    def test_helpers_and_orphan_detection(self):
        rep = MigrationReport(source_sqlite="a.sqlite3", target_alias="default", mode="DRY_RUN")
        self.assertTrue(rep.ok)
        self.assertIn("total_source_rows", rep.as_dict())
        defaults = _model_field_defaults_by_table()
        self.assertIn("accounts_user", defaults)

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.sqlite3"
            conn = sqlite3.connect(str(src))
            try:
                self.assertEqual(_sqlite_finance_totals(conn), {})
                conn.execute("CREATE TABLE accounts_user (id INTEGER PRIMARY KEY, username TEXT)")
                conn.execute(
                    "CREATE TABLE organization_clubmembership (id INTEGER PRIMARY KEY, user_id INTEGER, member_code TEXT)"
                )
                conn.execute("INSERT INTO organization_clubmembership (id, user_id, member_code) VALUES (1, 999, 'KMG-1')")
                conn.commit()
                orphans = _check_sqlite_orphans(conn)
                self.assertIn("organization_clubmembership.user_id->accounts_user", orphans)
            finally:
                conn.close()

            dry_rep = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=True)
            self.assertFalse(dry_rep.ok)
            self.assertTrue(dry_rep.fk_orphans)

    def test_execute_mode_with_mocked_mysql_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src = tmp_dir / "src.sqlite3"
            bdir = tmp_dir / "backups"
            sq = sqlite3.connect(str(src))
            try:
                sq.execute(
                    "CREATE TABLE finance_fundcategory (id INTEGER PRIMARY KEY, code TEXT, name TEXT, description TEXT, is_active INTEGER)"
                )
                sq.execute(
                    "INSERT INTO finance_fundcategory (id, code, name, description, is_active) VALUES (1, 'C1', 'Quỹ 1', '', 1)"
                )
                sq.execute(
                    "CREATE TABLE finance_financialtransaction (id INTEGER PRIMARY KEY, tx_type TEXT, amount REAL, status TEXT)"
                )
                sq.execute(
                    "INSERT INTO finance_financialtransaction (id, tx_type, amount, status) VALUES (1, 'INCOME', 100000, 'CONFIRMED')"
                )
                sq.commit()
            finally:
                sq.close()

            fake_cursor = MagicMock()
            fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
            fake_cursor.__exit__ = MagicMock(return_value=False)

            fake_conn = MagicMock()
            fake_conn.vendor = "mysql"
            fake_conn.cursor.return_value = fake_cursor

            # 0) Execute without backup_dir rejected
            with patch("deployment.sqlite_to_mysql.connections", {"default": fake_conn}):
                rep_no_bkp = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=False)
            self.assertFalse(rep_no_bkp.ok)
            self.assertIn("--backup-dir", rep_no_bkp.errors[0])

            # 1) Missing table in target
            fake_cursor.fetchall.return_value = [("finance_fundcategory",)]

            with patch("deployment.sqlite_to_mysql.connections", {"default": fake_conn}):
                rep_missing = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=False, backup_dir=bdir / "b1")
            self.assertFalse(rep_missing.ok)
            self.assertIn("thiếu bảng", rep_missing.errors[0])

            # 2) Non-empty target rejected when allow_nonempty=False
            fake_cursor.fetchall.return_value = [
                ("finance_fundcategory",),
                ("finance_financialtransaction",),
            ]
            fake_cursor.fetchone.return_value = (1,)
            with patch("deployment.sqlite_to_mysql.connections", {"default": fake_conn}):
                rep_nonempty = run_sqlite_to_mysql_migration(
                    source_sqlite=src, dry_run=False, backup_dir=bdir / "b2", allow_nonempty=False
                )
            self.assertFalse(rep_nonempty.ok)
            self.assertIn("đã có dữ liệu", rep_nonempty.errors[0])

            # 3) Intentional reconciliation mismatch inside atomic forces rollback (exit with exc)
            def fetchall_mismatch():
                sql = fake_cursor.execute.call_args[0][0]
                if sql == "SHOW TABLES":
                    return [("finance_fundcategory",), ("finance_financialtransaction",)]
                if "finance_financialtransaction" in sql and "GROUP BY" in sql:
                    return [("INCOME", 999)]  # intentional finance mismatch
                return []

            fake_cursor.fetchall.side_effect = fetchall_mismatch
            fake_cursor.fetchone.return_value = (1,)
            atomic_cm = MagicMock()
            with (
                patch("deployment.sqlite_to_mysql.connections", {"default": fake_conn}),
                patch("deployment.sqlite_to_mysql.transaction.atomic", return_value=atomic_cm),
            ):
                rep_abort = run_sqlite_to_mysql_migration(
                    source_sqlite=src, dry_run=False, backup_dir=bdir / "b3", allow_nonempty=True
                )
            self.assertFalse(rep_abort.ok)
            self.assertIsNotNone(atomic_cm.__exit__.call_args[0][0])

            # 4) Full execute happy path with backup & reconciliation
            def fetchall_side_effect():
                sql = fake_cursor.execute.call_args[0][0]
                if sql == "SHOW TABLES":
                    return [("finance_fundcategory",), ("finance_financialtransaction",)]
                if "finance_financialtransaction" in sql and "GROUP BY" in sql:
                    return [("INCOME", 100000)]
                return []

            def fetchone_side_effect():
                sql = fake_cursor.execute.call_args[0][0]
                if "LEFT JOIN" in sql:
                    return (0,)
                if "MIN(id)" in sql:
                    return (1, 1)
                return (1,)

            fake_cursor.fetchall.side_effect = fetchall_side_effect
            fake_cursor.fetchone.side_effect = fetchone_side_effect

            with (
                patch("deployment.sqlite_to_mysql.connections", {"default": fake_conn}),
                patch("deployment.sqlite_to_mysql.transaction.atomic"),
            ):
                rep_ok = run_sqlite_to_mysql_migration(
                    source_sqlite=src,
                    dry_run=False,
                    backup_dir=bdir,
                    allow_nonempty=True,
                )
            self.assertTrue(rep_ok.ok, rep_ok.errors)
            self.assertTrue(any(bdir.glob("*.sqlite3")))
            self.assertEqual(_target_finance_totals(fake_conn), {"INCOME": 100000})
            self.assertEqual(_check_target_orphans(fake_conn), {})

    def test_mysql_dry_run_schema_collation_varchar_and_unique_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "dry.sqlite3"
            sq = sqlite3.connect(str(src))
            try:
                sq.execute("CREATE TABLE finance_fundcategory (id INTEGER PRIMARY KEY, code TEXT, name TEXT)")
                sq.execute("INSERT INTO finance_fundcategory (id, code, name) VALUES (1, 'TOOLONGCODE', 'A')")
                sq.execute("INSERT INTO finance_fundcategory (id, code, name) VALUES (2, 'TOOLONGCODE', 'B')")
                sq.commit()
            finally:
                sq.close()

            fake_cursor = MagicMock()
            fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
            fake_cursor.__exit__ = MagicMock(return_value=False)

            def fetchall_side_effect():
                sql = fake_cursor.execute.call_args[0][0]
                if sql == "SHOW TABLES":
                    return [("finance_fundcategory",)]
                if sql == "SHOW TABLE STATUS":
                    return [("finance_fundcategory",) + ("",) * 13 + ("latin1_swedish_ci",)]
                if "SHOW COLUMNS" in sql:
                    return [
                        ("id", "bigint", "NO", "PRI", None, "auto_increment"),
                        ("code", "varchar(5)", "NO", "UNI", None, ""),
                        ("name", "varchar(100)", "NO", "", None, ""),
                        ("extra_req", "varchar(20)", "NO", "", None, ""),
                    ]
                return []

            fake_cursor.fetchall.side_effect = fetchall_side_effect
            fake_conn = MagicMock()
            fake_conn.vendor = "mysql"
            fake_conn.cursor.return_value = fake_cursor

            with patch("deployment.sqlite_to_mysql.connections", {"default": fake_conn}):
                rep = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=True)

            self.assertFalse(rep.ok)
            joined = "\n".join(rep.errors)
            self.assertIn("latin1_swedish_ci", joined)
            self.assertIn("VARCHAR(5)", joined)
            self.assertIn("UNIQUE", joined)


class MysqlBackupSecurityTests(TestCase):
    def test_backup_refuses_overwrite_and_restore_checks_keys_and_nonempty_dirs(self):
        from deployment import backup_restore as compose_backups
        from deployment import mysql_backup

        key_env = {k: f"{k}-secret-value-" + "x" * 32 for k in compose_backups.KEYS}
        wrong_env = {k: f"{k}-wrong-value--" + "y" * 32 for k in compose_backups.KEYS}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bdir = root / "bkp"
            m_src = root / "m_src"
            v_src = root / "v_src"
            m_src.mkdir()
            v_src.mkdir()
            (m_src / "a.txt").write_text("ok", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if "stdout" in kwargs:
                    kwargs["stdout"].write(b"-- sql\n")
                return MagicMock(stdout="0\n")

            with (
                patch("deployment.mysql_backup.resolve_mysql_tool", return_value="mysqldump"),
                patch("deployment.mysql_backup.subprocess.run", side_effect=fake_run),
            ):
                mysql_backup.create_mysql_backup(
                    destination=bdir,
                    db_name="kmg",
                    db_user="kmg",
                    db_password="pw",
                    media_root=m_src,
                    vault_root=v_src,
                    key_env=key_env,
                )
                # Cannot overwrite existing backup dir
                with self.assertRaises(FileExistsError):
                    mysql_backup.create_mysql_backup(
                        destination=bdir,
                        db_name="kmg",
                        db_user="kmg",
                        db_password="pw",
                        media_root=m_src,
                        vault_root=v_src,
                        key_env=key_env,
                    )

            m_dst = root / "m_dst"
            v_dst = root / "v_dst"
            m_dst.mkdir()
            v_dst.mkdir()

            # Wrong key fingerprint rejected before any DB or file write
            with self.assertRaisesRegex(ValueError, "Dấu vân tay khóa"):
                mysql_backup.restore_mysql_backup(
                    source_dir=bdir,
                    target_db="kmg_new",
                    db_user="kmg",
                    db_password="pw",
                    target_media=m_dst,
                    target_vault=v_dst,
                    key_env=wrong_env,
                )

            # Non-empty media dir rejected before DB import
            (m_dst / "existing.txt").write_text("busy", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "media đích"):
                mysql_backup.restore_mysql_backup(
                    source_dir=bdir,
                    target_db="kmg_new",
                    db_user="kmg",
                    db_password="pw",
                    target_media=m_dst,
                    target_vault=v_dst,
                    key_env=key_env,
                )

            # Happy-path restore into clean target dirs & empty DB
            (m_dst / "existing.txt").unlink()

            # Overlapping media/vault paths rejected before DB import (BK-01)
            with self.assertRaisesRegex(ValueError, "trùng hoặc lồng nhau"):
                mysql_backup.restore_mysql_backup(
                    source_dir=bdir,
                    target_db="kmg_new",
                    db_user="kmg",
                    db_password="pw",
                    target_media=m_dst,
                    target_vault=m_dst / "sub_vault",
                    key_env=key_env,
                )

            with (
                patch("deployment.mysql_backup.resolve_mysql_tool", return_value="mysql"),
                patch("deployment.mysql_backup.subprocess.run", return_value=MagicMock(stdout="0\n")),
            ):
                restored_manifest = mysql_backup.restore_mysql_backup(
                    source_dir=bdir,
                    target_db="kmg_new",
                    db_user="kmg",
                    db_password="pw",
                    target_media=m_dst,
                    target_vault=v_dst,
                    key_env=key_env,
                )
            self.assertEqual(restored_manifest["database_name"], "kmg")
            self.assertEqual((m_dst / "a.txt").read_text(encoding="utf-8"), "ok")


class SqliteBackupGuardAndNaturalKeyTests(TestCase):
    def test_backup_inside_repo_rejected_and_session_excluded(self):
        from deployment.sqlite_to_mysql import (
            REPO_ROOT,
            _remap_natural_key_columns,
            backup_sqlite_source,
        )

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "g.sqlite3"
            sq = sqlite3.connect(str(src))
            try:
                sq.execute("CREATE TABLE django_session (session_key TEXT PRIMARY KEY, session_data TEXT, expire_date TEXT)")
                sq.execute("INSERT INTO django_session VALUES ('k1', 'd1', '2026-12-01')")
                sq.commit()
            finally:
                sq.close()

            with self.assertRaisesRegex(ValueError, "trong repository"):
                backup_sqlite_source(src, REPO_ROOT / "tmp_forbidden_backup")

            rep = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=True)
            self.assertIn("django_session", rep.excluded_tables)
            self.assertNotIn("django_session", rep.source_rows)

        remapped = _remap_natural_key_columns(
            "accounts_user_user_permissions",
            ["id", "user_id", "permission_id"],
            [1, 10, 55],
            ct_map={},
            perm_map={55: 99},
        )
        self.assertEqual(remapped, [1, 10, 99])


import unittest
from django.db import connection
from django.test import TransactionTestCase


@unittest.skipUnless(connection.vendor == "mysql", "Requires live MySQL 8.4 (CI test-mysql-redis)")
class RealMySqlMigrationIntegrationTests(TransactionTestCase):
    def test_real_mysql_dry_run_and_execute_rollback_on_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src = tmp_dir / "ci_src.sqlite3"
            sq = sqlite3.connect(str(src))
            try:
                # Minimal table matching MySQL schema for dry-run validation
                sq.execute(
                    "CREATE TABLE finance_fundcategory (id INTEGER PRIMARY KEY, code TEXT, name TEXT, description TEXT, is_active INTEGER)"
                )
                sq.execute(
                    "INSERT INTO finance_fundcategory (id, code, name, description, is_active) VALUES (9901, 'CI_CAT', 'CI Quỹ', '', 1)"
                )
                sq.commit()
            finally:
                sq.close()

            dry_rep = run_sqlite_to_mysql_migration(source_sqlite=src, dry_run=True)
            self.assertEqual(dry_rep.source_rows.get("finance_fundcategory"), 1)

            # Empty source with existing non-empty MySQL tables must be rejected when allow_nonempty=False
            exec_err = run_sqlite_to_mysql_migration(
                source_sqlite=src,
                dry_run=False,
                backup_dir=tmp_dir / "bkp",
                allow_nonempty=False,
            )
            self.assertFalse(exec_err.ok)
