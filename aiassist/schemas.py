"""
JSON Schema cho đầu ra của từng tác vụ AI (structured output).

Schema chỉ giúp model trả đúng KHUÔN. Giá trị bên trong vẫn là dữ liệu không
tin cậy, nên các bước làm sạch trong services.py được giữ nguyên.
"""

_TEXT = {"type": "string"}
_TEXT_LIST = {"type": "array", "items": _TEXT}


def _object(**properties):
    """Object mà mọi trường đều bắt buộc."""
    return {"type": "object", "properties": properties,
            "required": list(properties)}


SUGGEST_TASKS = _object(tasks={"type": "array", "items": _object(
    title=_TEXT,
    days_before={"type": "integer", "minimum": 0},
    note=_TEXT,
    department=_TEXT,
    priority={"type": "string", "enum": ["LOW", "NORMAL", "HIGH", "URGENT"]},
)})

FEEDBACK_SUMMARY = _object(positive=_TEXT, negative=_TEXT, suggestion=_TEXT)

SCREENING = _object(
    score={"type": "integer", "minimum": 1, "maximum": 10},
    assessment=_TEXT,
    suggested_questions=_TEXT_LIST,
)

EVENT_CONTENT = _object(description=_TEXT, agenda=_TEXT, social_post=_TEXT)

POSTMORTEM = _object(
    executive_summary=_TEXT,
    highlights=_TEXT_LIST,
    financial_analysis=_TEXT,
    feedback_analysis=_TEXT,
    lessons_learned=_TEXT_LIST,
    action_items=_TEXT_LIST,
)

ASSISTANT = _object(
    answer=_TEXT,
    event_ids={"type": "array", "items": {"type": "integer"}},
)

PROPOSAL_REVIEW = _object(
    score={"type": "integer", "minimum": 1, "maximum": 10},
    strengths=_TEXT_LIST,
    risks=_TEXT_LIST,
    recommendation=_TEXT,
)

OPERATIONS_ANALYTICS = _object(
    summary=_TEXT,
    bottlenecks=_TEXT_LIST,
    action_plan=_TEXT_LIST,
)

SOCIAL_DIGEST = _object(
    headline=_TEXT,
    highlights=_TEXT_LIST,
    mood=_TEXT,
)
