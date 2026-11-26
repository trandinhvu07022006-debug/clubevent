import json
import logging
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .contracts import Actor, ToolCall, ToolResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Field:
    kind: str = "string"
    max_length: int = 256
    minimum: int = 0
    maximum: int = 100
    required: bool = True

    def __post_init__(self):
        if self.kind not in {"string", "integer", "boolean"}:
            raise ValueError("Unsupported field type")
        if self.kind == "string" and (
            type(self.max_length) is not int or self.max_length < 1
        ):
            raise ValueError("Invalid string length")
        if self.kind == "integer" and (
            type(self.minimum) is not int
            or type(self.maximum) is not int
            or self.minimum > self.maximum
        ):
            raise ValueError("Invalid integer range")

    def validate(self, value: Any) -> bool:
        if self.kind == "string":
            return (
                isinstance(value, str)
                and 0 < len(value.strip()) <= self.max_length
                and len(value) <= self.max_length
            )
        if self.kind == "integer":
            return type(value) is int and self.minimum <= value <= self.maximum
        return type(value) is bool

    def schema(self):
        if self.kind == "string":
            return {"type": "string", "minLength": 1, "maxLength": self.max_length}
        if self.kind == "integer":
            return {"type": "integer", "minimum": self.minimum, "maximum": self.maximum}
        return {"type": "boolean"}


@dataclass(frozen=True)
class ReadTool:
    name: str
    description: str
    permission: str
    fields: Mapping[str, Field]
    handler: Callable[[Actor, Mapping[str, Any]], Any]


class ToolRegistry:
    """Only trusted, audited read-only handlers may be registered.

    Every handler MUST independently scope ORM queries to actor and club and
    return only fields allowed to leave the server. This class cannot enforce
    read-only DB behavior or redact arbitrary handler output.
    """

    def __init__(self, max_output_chars: int = 8000):
        if type(max_output_chars) is not int or max_output_chars < 100:
            raise ValueError("Output budget too small")
        self._tools: dict[str, ReadTool] = {}
        self._max_output_chars = max_output_chars

    def register(self, tool: ReadTool):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", tool.name) or not tool.permission:
            raise ValueError("Invalid tool metadata")
        if tool.name in self._tools:
            raise ValueError("Duplicate tool")
        if not callable(tool.handler) or any(
            not isinstance(k, str) or not k or not isinstance(f, Field)
            for k, f in tool.fields.items()
        ):
            raise ValueError("Invalid tool configuration")
        self._tools[tool.name] = ReadTool(
            tool.name,
            tool.description,
            tool.permission,
            MappingProxyType(dict(tool.fields)),
            tool.handler,
        )

    @staticmethod
    def _allowed(actor: Actor, tool: ReadTool) -> bool:
        return (
            isinstance(actor, Actor)
            and actor.is_valid()
            and tool.permission in actor.permissions
        )

    def schemas(self, actor: Actor):
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {k: f.schema() for k, f in t.fields.items()},
                    "required": [k for k, f in t.fields.items() if f.required],
                },
            }
            for t in self._tools.values()
            if self._allowed(actor, t)
        ]

    def execute(self, actor: Actor, call: ToolCall) -> ToolResult:
        if not isinstance(call, ToolCall) or not isinstance(call.name, str):
            return ToolResult("", False, error="invalid_arguments")
        tool = self._tools.get(call.name)
        if tool is None or not self._allowed(actor, tool):
            return ToolResult(call.name, False, error="not_allowed")
        args = call.arguments
        if not isinstance(args, Mapping) or set(args) - set(tool.fields):
            return ToolResult(call.name, False, error="invalid_arguments")
        if any(
            (k not in args and f.required) or (k in args and not f.validate(args[k]))
            for k, f in tool.fields.items()
        ):
            return ToolResult(call.name, False, error="invalid_arguments")
        try:
            data = tool.handler(actor, dict(args))
            encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
            if len(encoded) > self._max_output_chars:
                return ToolResult(call.name, False, error="output_too_large")
            return ToolResult(call.name, True, json.loads(encoded))
        except Exception:
            logger.warning("read_tool_failed tool=%s", tool.name)
            return ToolResult(call.name, False, error="tool_failed")
