"""Small in-memory BM25 reference implementation; no embeddings or external calls."""
from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Iterable

from .contracts import Actor


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return re.findall(r"[^\W_]+", text, flags=re.UNICODE)


@dataclass(frozen=True)
class Document:
    source_id: str
    club_id: str
    text: str
    permission: str


@dataclass(frozen=True)
class Hit:
    source_id: str
    text: str
    score: float


def search(
    actor: Actor,
    documents: Iterable[Document],
    query: str,
    *,
    limit: int = 5,
) -> list[Hit]:
    if (
        not isinstance(actor, Actor)
        or not actor.is_valid()
        or type(limit) is not int
        or not 1 <= limit <= 20
        or not isinstance(query, str)
    ):
        return []
    q = set(tokens(query[:4000]))
    if not q:
        return []
    # Filter before ranking so unauthorized documents cannot influence scores.
    docs = [
        d
        for d in documents
        if d.club_id == actor.club_id and d.permission in actor.permissions
    ]
    if not docs:
        return []
    bags = [Counter(tokens(d.text)) for d in docs]
    lengths = [sum(b.values()) for b in bags]
    avg = max(sum(lengths) / len(docs), 1.0)
    idfs = {
        t: math.log(
            1
            + (len(docs) - sum(t in b for b in bags) + 0.5)
            / (sum(t in b for b in bags) + 0.5)
        )
        for t in q
    }
    hits = []
    for doc, bag, length in zip(docs, bags, lengths):
        norm = 1.2 * (0.25 + 0.75 * length / avg)
        score = sum(idfs[t] * bag[t] * 2.2 / (bag[t] + norm) for t in q if bag[t])
        if score > 0:
            hits.append(Hit(doc.source_id, doc.text, score))
    return sorted(hits, key=lambda h: (-h.score, h.source_id))[:limit]
