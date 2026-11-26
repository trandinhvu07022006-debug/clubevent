from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Actor:
    """Construct ONLY from authenticated server-side identity and permissions."""

    user_id: str
    club_id: str
    permissions: frozenset[str]

    def is_valid(self) -> bool:
        """Reject malformed identities; authentication is still the adapter's duty."""
        return (
            type(self.user_id) is str
            and bool(self.user_id.strip())
            and type(self.club_id) is str
            and bool(self.club_id.strip())
            and type(self.permissions) is frozenset
            and all(type(p) is str and bool(p.strip()) for p in self.permissions)
        )


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    data: Any = None
    error: str = ""


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class ModelReply:
    text: str = ""
    calls: tuple[ToolCall, ...] = ()


class ModelProvider(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelReply:
        """Adapter owns transport, timeout, retries, quota and provider-specific schemas."""
        ...
