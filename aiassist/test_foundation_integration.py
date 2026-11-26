"""Integration & security boundary tests for KMG AI Foundation 0.2.1 in aiassist."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, EventVisibility, TicketType

from .adapters import (
    build_public_tool_registry,
    build_server_actor,
    retrieve_knowledge_bm25,
)
from .chatbot import answer
from .core.contracts import Actor, ToolCall
from .models import ClubKnowledge, KnowledgeCategory


class FoundationIntegrationTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.guest = User.objects.create_user(
            username="f_guest", password="x", full_name="Khách A", role=Role.GUEST
        )
        self.locked = User.objects.create_user(
            username="f_locked", password="x", full_name="Khoá B", is_locked=True
        )
        self.lead = User.objects.create_user(
            username="f_lead", password="x", full_name="Trưởng C", role=Role.LEAD
        )
        from organization.models import Appointment, Position, PositionCode, ScopeType
        chair_pos, _ = Position.objects.get_or_create(
            code=PositionCode.CHAIRMAN,
            defaults={
                "name": "Chủ nhiệm CLB",
                "scope_type": ScopeType.CLUB,
                "is_officer": True,
                "is_singleton": True,
            },
        )
        Appointment.objects.create(
            user=self.lead, position=chair_pos, scope_type=ScopeType.CLUB, is_active=True
        )
        self.pub_event = Event.objects.create(
            name="Acoustic Ngoài Trời",
            location="Sân trường",
            starts_at=now + timezone.timedelta(days=4),
            register_deadline=now + timezone.timedelta(days=3),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        TicketType.objects.create(event=self.pub_event, name="Vé thường", price=0, quota=50)
        self.internal_event = Event.objects.create(
            name="Họp Mật Ban Chủ Nhiệm",
            location="Phòng Kín",
            starts_at=now + timezone.timedelta(days=2),
            register_deadline=now + timezone.timedelta(days=1),
            status=EventStatus.OPEN,
            visibility=EventVisibility.INTERNAL,
        )
        self.draft_event = Event.objects.create(
            name="Nháp Bí Mật",
            location="Ẩn",
            starts_at=now + timezone.timedelta(days=6),
            register_deadline=now + timezone.timedelta(days=5),
            status=EventStatus.DRAFT,
            visibility=EventVisibility.PUBLIC,
        )
        self.kb = ClubKnowledge.objects.create(
            title="Chính sách chuyển nhượng vé",
            category=KnowledgeCategory.RULE,
            keywords="chuyen nhuong, doi ve",
            content="Bạn có thể chuyển vé cho bạn khác trước 3 giờ diễn ra sự kiện.",
            visibility="PUBLIC",
            priority=1,
        )

    def test_server_actor_reflects_server_auth_and_blocks_locked_users(self):
        anon = build_server_actor(None)
        self.assertEqual(anon.user_id, "guest:anon")
        self.assertEqual(anon.permissions, frozenset({"public.read"}))

        locked_actor = build_server_actor(self.locked)
        self.assertEqual(locked_actor.user_id, "guest:anon")
        self.assertEqual(locked_actor.permissions, frozenset({"public.read"}))

        lead_actor = build_server_actor(self.lead)
        self.assertEqual(lead_actor.user_id, f"user:{self.lead.pk}")
        self.assertIn("club.document.manage_confidential", lead_actor.permissions)
        self.assertIn("club.event.view_internal", lead_actor.permissions)

    def test_public_tools_never_expose_internal_or_draft_events(self):
        registry = build_public_tool_registry()
        lead_actor = build_server_actor(self.lead)
        res = registry.execute(
            lead_actor,
            ToolCall("list_public_events", {"upcoming_only": True, "limit": 10}),
        )
        self.assertTrue(res.ok)
        names = [item["name"] for item in res.data]
        self.assertIn("Acoustic Ngoài Trời", names)
        self.assertNotIn("Họp Mật Ban Chủ Nhiệm", names)
        self.assertNotIn("Nháp Bí Mật", names)

    def test_bm25_retrieval_matches_unaccented_vietnamese_and_blocks_offtopic(self):
        hits = retrieve_knowledge_bm25("chuyen nhuong ve cho ban khac")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["title"], "Chính sách chuyển nhượng vé")
        self.assertEqual(retrieve_knowledge_bm25("thời tiết Tokyo hôm nay"), [])
        # Malformed actor must return nothing
        bad_actor = Actor(user_id="", club_id="kmg", permissions=frozenset({"public.read"}))
        self.assertEqual(
            build_public_tool_registry().execute(
                bad_actor,
                ToolCall("search_club_knowledge", {"query": "chuyen ve", "limit": 3}),
            ).error,
            "not_allowed",
        )

    @override_settings(AI_FOUNDATION_AGENT=True)
    @patch("aiassist.adapters._ask_ai")
    def test_feature_flagged_foundation_agent_tool_roundtrip_and_pii_redaction(self, mock_ai):
        mock_ai.side_effect = [
            {"calls": [{"name": "list_public_events", "arguments": {"upcoming_only": True, "limit": 5}}]},
            {"answer": "CLB sắp có sự kiện Acoustic Ngoài Trời tại Sân trường bạn nhé."},
        ]
        result = answer("Gửi xe ở đâu và có show nào không? Sđt mình 0912345678", user=self.guest)
        self.assertEqual(result["source"], "ai")
        self.assertIn("Acoustic Ngoài Trời", result["text"])
        first_prompt = mock_ai.call_args_list[0].args[0]
        self.assertNotIn("0912345678", first_prompt)
        second_prompt = mock_ai.call_args_list[1].args[0]
        self.assertIn("Acoustic Ngoài Trời", second_prompt)
        self.assertNotIn("Họp Mật Ban Chủ Nhiệm", second_prompt)

    @override_settings(AI_FOUNDATION_AGENT=True, AI_PROVIDER="mock")
    def test_foundation_agent_falls_back_cleanly_when_provider_unavailable(self):
        result = answer("Gửi xe ở đâu?", user=self.guest)
        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["source"], "rules")
