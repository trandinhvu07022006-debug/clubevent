"""Phase 2 security regression tests: upload validation, download headers, and proxy/CSP invariants."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from operations.services import submit_task_deliverable
from operations.test_phase2_operations import Phase2OperationsBase
from organization.services import GovernanceError
from social.models import ChatAttachment, ChatMessage
from social.services import ensure_club_conversation


class OperationsUploadAndDownloadSecurityTests(Phase2OperationsBase):
    def test_submit_task_deliverable_rejects_dangerous_uploads(self):
        task = self._task([self.member_a])
        dangerous = [
            SimpleUploadedFile("evil.html", b"<script>alert(1)</script>", content_type="text/html"),
            SimpleUploadedFile("vector.svg", b"<svg onload='alert(1)'></svg>", content_type="image/svg+xml"),
            SimpleUploadedFile("payload.exe", b"MZ\x90\x00binary", content_type="application/octet-stream"),
            SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf"),
            SimpleUploadedFile("fake.pdf", b"<!doctype html><html></html>", content_type="application/pdf"),
        ]
        for bad_file in dangerous:
            with self.subTest(filename=bad_file.name):
                with self.assertRaises(GovernanceError):
                    submit_task_deliverable(
                        actor=self.member_a,
                        task=task,
                        submission_note="Bao cao",
                        attachment=bad_file,
                    )

    def test_download_submission_sets_nosniff_and_private_no_store(self):
        vault = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        with override_settings(PRIVATE_VAULT_ROOT=vault):
            task = self._task([self.member_a])
            sub = submit_task_deliverable(
                actor=self.member_a,
                task=task,
                submission_note="Nop file an toan",
                attachment=SimpleUploadedFile("report.txt", b"safe-content", content_type="text/plain"),
            )
            self.client.force_login(self.member_a)
            resp = self.client.get(reverse("operations:download_submission", args=[sub.pk]))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
            self.assertEqual(resp["Cache-Control"], "private, no-store")
            self.assertEqual(b"".join(resp.streaming_content), b"safe-content")


class SocialAttachmentDispositionTests(Phase2OperationsBase):
    def test_svg_content_type_never_served_inline_in_chat_download(self):
        vault = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        with override_settings(PRIVATE_VAULT_ROOT=vault):
            conv = ensure_club_conversation(self.member_a)
            msg = ChatMessage.objects.create(
                conversation=conv,
                sender=self.member_a,
                iv_nonce=b"123456789012",
                ciphertext=b"cipher",
            )
            att = ChatAttachment.objects.create(
                message=msg,
                file=SimpleUploadedFile("x.svg", b"<svg></svg>", content_type="image/svg+xml"),
                original_filename="x.svg",
                content_type="image/svg+xml",
                file_size=11,
                checksum_sha256="a" * 64,
            )
            self.client.force_login(self.member_a)
            resp = self.client.get(reverse("social:chat_attachment_download", args=[att.pk]))
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp["Content-Disposition"].startswith("attachment;"))
            self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
            self.assertEqual(b"".join(resp.streaming_content), b"<svg></svg>")


class NginxConfigSecurityTests(SimpleTestCase):
    def test_nginx_template_sets_forwarded_host_csp_and_private_vault_deny(self):
        nginx_conf = (Path(settings.BASE_DIR) / "deployment" / "nginx.conf.template").read_text(encoding="utf-8")
        self.assertIn("proxy_set_header X-Forwarded-Host $http_host;", nginx_conf)
        self.assertIn("location /private_vault/ { return 404; }", nginx_conf)
        self.assertIn("Content-Security-Policy", nginx_conf)
        self.assertIn("Content-Security-Policy-Report-Only", nginx_conf)
        self.assertIn("frame-ancestors 'none'", nginx_conf)
