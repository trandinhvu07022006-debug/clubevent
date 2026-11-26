"""Django adapters bridging Clubevent ORM/auth/LLM gateway with aiassist.core."""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from django.conf import settings
from django.utils import timezone

from events.models import (Event, EventStatus, EventVisibility,
                           can_view_internal_events)
from organizing.models import Department
from recruitment.models import RecruitmentRound

from .chatbot import normalize, prepare_query
from .core.agent import Agent
from .core.contracts import Actor, Message, ModelProvider, ModelReply, ToolCall
from .core.retrieval import Document, search as bm25_search
from .core.tools import Field, ReadTool, ToolRegistry
from .models import ClubKnowledge, KnowledgeVisibility
from .privacy import known_names, redact, sanitize_untrusted_input
from .services import RETRIEVAL_STOPWORDS, _ask_ai


def build_server_actor(user) -> Actor:
    """
    Construct an Actor strictly from authenticated server-side user state.
    Never accept user_id, club_id, or permissions from client payloads or LLM output.
    """
    if not user or not getattr(user, "is_authenticated", False) or getattr(user, "is_locked", False):
        return Actor(
            user_id="guest:anon",
            club_id="kmg",
            permissions=frozenset({"public.read"}),
        )
    perms = {"public.read", "member.authenticated"}
    if can_view_internal_events(user):
        perms.add("club.event.view_internal")
    if getattr(user, "is_staff_btc", False):
        perms.add("organizing.staff")
    if getattr(user, "is_lead", False):
        perms.add("organizing.lead")
    return Actor(
        user_id=f"user:{user.pk}",
        club_id="kmg",
        permissions=frozenset(perms),
    )


def _tool_list_public_events(actor: Actor, args: Mapping[str, Any]) -> list[dict]:
    """Read-only, PII-free summary of PUBLIC non-draft events."""
    now = timezone.now()
    qs = (
        Event.objects.filter(visibility=EventVisibility.PUBLIC)
        .exclude(status=EventStatus.DRAFT)
        .prefetch_related("ticket_types")
    )
    if args.get("upcoming_only", True):
        qs = qs.filter(starts_at__gte=now).order_by("starts_at")
    else:
        qs = qs.order_by("-starts_at")
    limit = int(args.get("limit", 5))
    results = []
    for ev in qs[:limit]:
        results.append({
            "id": ev.pk,
            "name": redact(ev.name),
            "status": ev.get_status_display(),
            "starts_at": timezone.localtime(ev.starts_at).strftime("%H:%M %d/%m/%Y"),
            "location": redact(ev.location),
            "tickets": [
                {
                    "name": tt.name,
                    "price": tt.price,
                    "remaining": tt.remaining,
                    "quota": tt.quota,
                }
                for tt in ev.ticket_types.all()
            ],
        })
    return results


_KB_PERMISSION_MAP = {
    KnowledgeVisibility.PUBLIC: "public.read",
    KnowledgeVisibility.INTERNAL: "club.event.view_internal",
    KnowledgeVisibility.CONFIDENTIAL: "organizing.lead",
}


def _kb_documents() -> list[tuple[ClubKnowledge, Document]]:
    """Build normalized BM25 documents for active ClubKnowledge with classification permissions."""
    docs: list[tuple[ClubKnowledge, Document]] = []
    for item in ClubKnowledge.objects.filter(is_active=True).order_by("priority", "-updated_at"):
        norm_text = prepare_query(f"{item.title} {item.keywords} {item.content}")
        perm = _KB_PERMISSION_MAP.get(item.visibility, "club.event.view_internal")
        docs.append((
            item,
            Document(
                source_id=f"kb:{item.pk}",
                club_id="kmg",
                text=norm_text,
                permission=perm,
            ),
        ))
    return docs


def retrieve_knowledge_bm25(query: str, actor: Actor | None = None, limit: int = 4) -> list[dict]:
    """
    Hybrid BM25 retrieval over ClubKnowledge using Foundation's permission-first search.
    Returns empty list when no meaningful non-stopword query tokens match.
    """
    safe_actor = actor if (isinstance(actor, Actor) and actor.is_valid()) else build_server_actor(None)
    norm_query = prepare_query(query)
    meaningful = {
        t for t in re.findall(r"\w+", norm_query)
        if len(t) >= 2 and t not in RETRIEVAL_STOPWORDS
    }
    if not meaningful:
        return []

    pairs = _kb_documents()
    if not pairs:
        return []
    by_id = {doc.source_id: item for item, doc in pairs}
    hits = bm25_search(safe_actor, [doc for _, doc in pairs], " ".join(sorted(meaningful)), limit=limit)
    out = []
    for hit in hits:
        item = by_id.get(hit.source_id)
        if item is None:
            continue
        out.append({
            "id": item.pk,
            "title": redact(item.title),
            "category": item.get_category_display(),
            "snippet": redact(" ".join(item.content.split())[:350]),
            "score": round(hit.score, 4),
        })
    return out


def _tool_search_club_knowledge(actor: Actor, args: Mapping[str, Any]) -> list[dict]:
    return retrieve_knowledge_bm25(
        str(args["query"]),
        actor=actor,
        limit=int(args["limit"]),
    )


def _tool_get_club_overview(actor: Actor, args: Mapping[str, Any]) -> dict:
    depts = [
        {"name": redact(d.name), "description": redact((d.description or "")[:160])}
        for d in Department.objects.all().order_by("order", "id")[:12]
    ]
    rec = RecruitmentRound.current() or RecruitmentRound.next_upcoming()
    rec_info = None
    if rec:
        rec_info = {
            "name": redact(rec.name),
            "is_open": bool(rec.is_open),
            "opens_at": timezone.localtime(rec.opens_at).strftime("%d/%m/%Y"),
            "closes_at": timezone.localtime(rec.closes_at).strftime("%H:%M %d/%m/%Y"),
        }
    return {"departments": depts, "recruitment": rec_info}


def build_public_tool_registry() -> ToolRegistry:
    """Register strictly read-only, PII-free public tools."""
    registry = ToolRegistry(max_output_chars=8000)
    registry.register(ReadTool(
        name="list_public_events",
        description="Liệt kê các sự kiện công khai của CLB kèm lịch và số vé còn lại.",
        permission="public.read",
        fields={
            "upcoming_only": Field(kind="boolean", required=True),
            "limit": Field(kind="integer", minimum=1, maximum=10, required=True),
        },
        handler=_tool_list_public_events,
    ))
    registry.register(ReadTool(
        name="search_club_knowledge",
        description="Tìm thông tin chính thức trong Kho tri thức & FAQ của CLB bằng BM25.",
        permission="public.read",
        fields={
            "query": Field(kind="string", max_length=200, required=True),
            "limit": Field(kind="integer", minimum=1, maximum=6, required=True),
        },
        handler=_tool_search_club_knowledge,
    ))
    registry.register(ReadTool(
        name="get_club_overview",
        description="Lấy danh sách các Ban chuyên môn và thông tin đợt tuyển thành viên.",
        permission="public.read",
        fields={},
        handler=_tool_get_club_overview,
    ))
    return registry


class DjangoGatewayProvider(ModelProvider):
    """Adapter wrapping Clubevent's _ask_ai gateway for Foundation's Agent loop."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.AI_ASSISTANT_MODEL or settings.AI_MODEL

    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelReply:
        serialized_msgs = [{"role": m.role, "content": m.content} for m in messages]
        prompt = (
            "Bạn là bộ điều phối công cụ chỉ đọc của KMG Club.\n"
            "Chỉ trả về JSON theo một trong hai dạng:\n"
            '1) Gọi công cụ: {"calls": [{"name": "ten_tool", "arguments": {...}}]}\n'
            '2) Trả lời cuối cùng (tiếng Việt có dấu, tối đa 4 câu, không markdown): {"answer": "..."}\n\n'
            f"CÔNG CỤ ĐƯỢC PHÉP:\n{json.dumps(list(tools), ensure_ascii=False)}\n\n"
            f"HỘI THOẠI:\n{json.dumps(serialized_msgs, ensure_ascii=False)}"
        )
        data = _ask_ai(prompt, model=self.model)
        if not isinstance(data, dict):
            raise ValueError("Malformed gateway JSON payload")
        raw_calls = data.get("calls")
        if raw_calls:
            if not isinstance(raw_calls, list):
                raise ValueError("Invalid calls payload")
            parsed_calls = []
            for item in raw_calls:
                if not isinstance(item, dict):
                    raise ValueError("Invalid tool call item")
                name = item.get("name")
                args = item.get("arguments")
                if not isinstance(name, str) or not isinstance(args, Mapping):
                    raise ValueError("Invalid tool call fields")
                parsed_calls.append(ToolCall(name=name, arguments=dict(args)))
            return ModelReply(text="", calls=tuple(parsed_calls))
        return ModelReply(text=str(data.get("answer") or "").strip(), calls=())


def ask_with_foundation(question: str, user=None) -> dict | None:
    """
    Run Foundation 0.2.1 bounded Agent with server-side Actor and read-only public tools.
    Returns None on unavailable/empty/error so caller can fall back cleanly.
    """
    actor = build_server_actor(user)
    clean_question = sanitize_untrusted_input(redact((question or "").strip(), known_names(user)))[:500]
    if not clean_question:
        return None
    agent = Agent(
        DjangoGatewayProvider(),
        build_public_tool_registry(),
        max_rounds=3,
        max_calls=5,
        max_context_chars=48000,
    )
    response = agent.answer(actor, clean_question)
    if response.status != "ok" or not response.text.strip():
        return None
    model = settings.AI_ASSISTANT_MODEL or settings.AI_MODEL
    text = " ".join(response.text.split())[:800]
    return {
        "intent": "ai",
        "source": "ai",
        "text": text,
        "links": [],
        "meta": {
            "model_name": model,
            "prompt_version": "foundation-0.2.1",
        },
    }
