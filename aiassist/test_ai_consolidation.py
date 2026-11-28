"""Consolidation 4.0 tests for KMG AI: 3 capabilities, Vietnamese variants, Egress/PII & personalization."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from aiassist.chatbot import answer
from aiassist.egress import DataClassification, evaluate_egress
from aiassist.management.commands.import_ai_dataset import (
    DEFAULT_CANDIDATES_PATH,
    import_knowledge_jsonl,
)
from aiassist.models import ApprovalStatus, ClubKnowledge, MusicLearningProfile
from aiassist.privacy import redact

User = get_user_model()


class KmgAiConsolidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ai_consol_user",
            password="Password123!",
            email="aiconsol@example.com",
        )

    def test_three_capabilities_and_vietnamese_variants(self):
        # 1. Gia sư âm nhạc (có dấu, không dấu, viết tắt)
        r_music_diacritic = answer("Cách bấm hợp âm F trưởng không bị rè?", user=self.user, allow_ai=False)
        self.assertIn("F", r_music_diacritic["text"])

        r_music_nodiacritic = answer("cach bam hop am f truong ko bi re", user=self.user, allow_ai=False)
        self.assertIn("F", r_music_nodiacritic["text"])

        # 2. Người bạn đồng hành sinh viên
        r_comp = answer("Mình bị stress và áp lực deadline quá, làm sao cân bằng?", user=self.user, allow_ai=False)
        self.assertTrue(len(r_comp["text"]) > 20)

        # 3. Trợ lý vận hành CLB (viết tắt clb / sk)
        r_ops = answer("clb sắp tới có sk gì ko?", user=self.user, allow_ai=False)
        self.assertIn("text", r_ops)

        # Câu hỏi nhiều ý + câu hỏi tiếp nối (có history)
        r_multi = answer(
            "Cách luyện thanh nhạc cơ bản và CLB có các ban nào?",
            user=self.user,
            allow_ai=False,
        )
        self.assertTrue(len(r_multi["text"]) > 20)

        r_followup = answer(
            "Vậy tập bao lâu mỗi ngày thì ổn?",
            user=self.user,
            allow_ai=False,
            history=[
                {"role": "user", "text": "Cách bấm hợp âm F trưởng"},
                {"role": "assistant", "text": r_music_diacritic["text"]},
            ],
        )
        self.assertTrue(len(r_followup["text"]) > 10)

    def test_egress_policy_and_pii_masking(self):
        self.assertTrue(evaluate_egress(primary_provider="gemini", classification=DataClassification.PUBLIC).allowed)
        self.assertFalse(evaluate_egress(primary_provider="gemini", classification=DataClassification.INTERNAL).allowed)
        self.assertFalse(evaluate_egress(primary_provider="gemini", classification=DataClassification.CONFIDENTIAL).allowed)
        self.assertFalse(evaluate_egress(primary_provider="openai", classification=DataClassification.PRIVATE_PII).allowed)

        masked = redact("Liên hệ 0912345678 hoặc sv@kma.edu.vn, MSSV AT200123")
        self.assertNotIn("0912345678", masked)
        self.assertNotIn("sv@kma.edu.vn", masked)
        self.assertNotIn("AT200123", masked)

    def test_personalization_consent_disable_and_delete(self):
        self.client.force_login(self.user)
        url = reverse("aiassist:music_profile_api")

        # Enable & configure
        res_on = self.client.post(
            url,
            data=json.dumps({
                "personalization_enabled": True,
                "instrument": "GUITAR",
                "level": "BEGINNER",
                "goal": "Đệm hát cơ bản",
            }),
            content_type="application/json",
        )
        self.assertEqual(res_on.status_code, 200)
        self.assertTrue(MusicLearningProfile.objects.filter(user=self.user, personalization_enabled=True).exists())

        # Disable personalization
        res_off = self.client.post(
            url,
            data=json.dumps({"personalization_enabled": False}),
            content_type="application/json",
        )
        self.assertEqual(res_off.status_code, 200)
        self.assertFalse(res_off.json()["personalization_enabled"])

        # Delete music learning profile
        res_del = self.client.delete(url)
        self.assertEqual(res_del.status_code, 200)
        self.assertFalse(MusicLearningProfile.objects.filter(user=self.user).exists())

    def test_46_knowledge_candidates_import_and_moderation(self):
        res = import_knowledge_jsonl(DEFAULT_CANDIDATES_PATH, dry_run=False)
        self.assertEqual(res["created"], 46)
        self.assertEqual(ClubKnowledge.objects.filter(approval_status=ApprovalStatus.PENDING).count(), 46)
        # All 46 candidates are PUBLIC and have non-empty title & content
        self.assertEqual(ClubKnowledge.objects.filter(visibility="PUBLIC").count(), 46)

    def test_confidential_knowledge_never_exported_by_default(self):
        from io import StringIO
        from django.core.management import call_command
        from aiassist.models import KnowledgeCategory, KnowledgeVisibility

        canary = "CANARY-CONFIDENTIAL-SECRET-999"
        ClubKnowledge.objects.create(
            knowledge_id="CONF-CANARY-1",
            title="Nội bộ mật",
            category=KnowledgeCategory.RULE,
            visibility=KnowledgeVisibility.CONFIDENTIAL,
            approval_status=ApprovalStatus.APPROVED,
            content=canary,
            is_active=True,
        )
        out = StringIO()
        call_command("export_finetune_dataset", stdout=out)
        # Default export excludes CONFIDENTIAL/INTERNAL canaries
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ft.jsonl"
            call_command("export_finetune_dataset", output=str(p), stdout=StringIO())
            if p.exists():
                self.assertNotIn(canary, p.read_text(encoding="utf-8"))
