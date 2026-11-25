"""Chuyển nhật ký tương tác thành JSONL để rà soát và bổ sung golden set."""
import json

from .privacy import redact


def to_jsonl(logs) -> str:
    """Mỗi dòng một lượt hỏi đáp. Che PII thêm lần nữa trước khi ra khỏi hệ thống."""
    lines = []
    for log in logs:
        lines.append(json.dumps({
            "question": redact(log.question),
            "answer": redact(log.answer_preview),
            "intent": log.intent,
            "source": log.source,
            "rating": log.feedback,
            "note": redact(log.feedback_note),
            "model": log.model_name,
            "prompt_version": log.prompt_version,
            "created_at": log.created_at.isoformat(),
        }, ensure_ascii=False))
    return "".join(line + "\n" for line in lines)
