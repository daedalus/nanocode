"""Efficient context management for the agent."""

import json
import os
import tempfile
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class ContextStrategy(Enum):
    """Context management strategies."""

    SLIDING_WINDOW = "sliding_window"
    SUMMARY = "summary"
    IMPORTANCE = "importance"
    COMPACTION = "compaction"


class MessageRole(Enum):
    """Message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class MessagePartType(Enum):
    """Message part types."""

    TEXT = "text"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    IMAGE = "image"


@dataclass
class MessagePart:
    """A single part of a message."""

    part_type: MessagePartType
    content: str
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    provider_metadata: Optional[dict] = None
    tokens: int = 0

    def to_dict(self) -> dict:
        """Convert to dict."""
        result = {"type": self.part_type.value, "content": self.content}
        if self.tool_name:
            result["tool_name"] = self.tool_name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.provider_metadata:
            result["provider_metadata"] = self.provider_metadata
        return result


@dataclass
class Message:
    """A message with parts and metadata."""

    role: str
    parts: list[MessagePart] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    importance: float = 0.5
    summary: Optional[str] = None
    tokens: int = 0

    @staticmethod
    def create_text(role: str, content: str) -> "Message":
        """Create a text message."""
        msg = Message(role=role)
        msg.add_text(content)
        return msg

    @staticmethod
    def create_tool_result(tool_name: str, tool_call_id: str, content: str) -> "Message":
        """Create a tool result message."""
        msg = Message(role="tool")
        msg.add_tool_result(tool_name, tool_call_id, content)
        return msg

    def add_text(self, content: str):
        """Add text part."""
        tokens = TokenCounter.count_tokens(content)
        self.parts.append(
            MessagePart(
                part_type=MessagePartType.TEXT,
                content=content,
                tokens=tokens,
            )
        )
        self.tokens += tokens

    def add_reasoning(self, content: str, provider_metadata: dict = None):
        """Add reasoning part."""
        tokens = TokenCounter.count_tokens(content)
        self.parts.append(
            MessagePart(
                part_type=MessagePartType.REASONING,
                content=content,
                provider_metadata=provider_metadata,
                tokens=tokens,
            )
        )
        self.tokens += tokens

    def add_tool_call(self, tool_name: str, tool_call_id: str, args: str):
        """Add tool call part."""
        tokens = TokenCounter.count_tokens(args)
        self.parts.append(
            MessagePart(
                part_type=MessagePartType.TOOL_CALL,
                content=args,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tokens=tokens,
            )
        )
        self.tokens += tokens

    def add_tool_result(self, tool_name: str, tool_call_id: str, content: str):
        """Add tool result part."""
        tokens = TokenCounter.count_tokens(content)
        self.parts.append(
            MessagePart(
                part_type=MessagePartType.TOOL_RESULT,
                content=content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tokens=tokens,
            )
        )
        self.tokens += tokens

    def get_text_content(self) -> str:
        """Get combined text content."""
        return " ".join(p.content for p in self.parts if p.part_type == MessagePartType.TEXT)

    def get_tool_results(self) -> list[tuple[str, str, str]]:
        """Get all tool results as (tool_name, tool_call_id, content)."""
        results = []
        for p in self.parts:
            if p.part_type == MessagePartType.TOOL_RESULT and p.tool_name and p.tool_call_id:
                results.append((p.tool_name, p.tool_call_id, p.content))
        return results

    def to_dict(self) -> dict:
        """Convert to dict for LLM API."""
        result = {"role": self.role}

        if len(self.parts) == 1 and self.parts[0].part_type == MessagePartType.TEXT:
            result["content"] = self.parts[0].content
        else:
            result["content"] = [p.to_dict() for p in self.parts]

        return result


@dataclass
class MessageToken:
    """Legacy message with token count (backward compatibility)."""

    role: str
    content: str
    tool_call_id: Optional[str] = None
    tokens: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    importance: float = 0.5

    def to_dict(self) -> dict:
        """Convert to dict for LLM."""
        result = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


class ModelLimits:
    """Model-specific context limits."""

    DEFAULT_LIMITS = {
        "gpt-4o": {"context": 128000, "output": 16384},
        "gpt-4o-mini": {"context": 128000, "output": 16384},
        "gpt-4-turbo": {"context": 128000, "output": 4096},
        "gpt-4": {"context": 8192, "output": 4096},
        "gpt-3.5-turbo": {"context": 16385, "output": 4096},
        "claude-3-5-sonnet": {"context": 200000, "output": 8192},
        "claude-3-opus": {"context": 200000, "output": 4096},
        "claude-3-haiku": {"context": 200000, "output": 4096},
        "claude-3-sonnet": {"context": 200000, "output": 4096},
        "default": {"context": 8000, "output": 4096},
    }

    _registry = None

    @classmethod
    def _get_registry(cls):
        """Get the model registry."""
        if cls._registry is None:
            try:
                from nanocode.llm.registry import get_registry

                cls._registry = get_registry()
            except ImportError:
                pass
        return cls._registry

    @classmethod
    async def load_registry(cls):
        """Load model registry from models.dev."""
        registry = cls._get_registry()
        if registry:
            try:
                await registry.load()
            except Exception:
                pass

    @classmethod
    def get_limits(cls, model: str) -> dict:
        """Get context and output limits for a model.

        First tries to get limits from models.dev registry,
        then falls back to built-in defaults.
        """
        registry = cls._get_registry()

        if registry and registry._providers:
            full_id = model
            if "/" in full_id:
                model_info = registry.get_model_by_full_id(full_id)
                if model_info:
                    context_limit = model_info.context_limit
                    output_limit = min(context_limit // 8, 16384)
                    return {"context": context_limit, "output": output_limit}

        model_lower = model.lower()
        for key, limits in cls.DEFAULT_LIMITS.items():
            if key in model_lower:
                return limits.copy()
        return cls.DEFAULT_LIMITS["default"].copy()

    @classmethod
    def get_limits_sync(cls, model: str) -> dict:
        """Synchronous version of get_limits (uses cache only)."""
        registry = cls._get_registry()

        if registry and registry._providers:
            full_id = model
            if "/" in full_id:
                model_info = registry.get_model_by_full_id(full_id)
                if model_info:
                    context_limit = model_info.context_limit
                    output_limit = min(context_limit // 8, 16384)
                    return {"context": context_limit, "output": output_limit}

        model_lower = model.lower()
        for key, limits in cls.DEFAULT_LIMITS.items():
            if key in model_lower:
                return limits.copy()
        return cls.DEFAULT_LIMITS["default"].copy()


class TokenCounter:
    """Estimate token counts for messages."""

    @staticmethod
    def count_tokens(text: str) -> int:
        """Count tokens using approximation.

        Uses: ~4 chars per token for English, adjusts for other languages.
        """
        if not text:
            return 0
        char_count = len(text)
        tokens = char_count // 4
        tokens += len(text.split())
        tokens = tokens // 2
        return max(1, tokens)

    @staticmethod
    def count_messages_tokens(messages: list[Message]) -> int:
        """Count total tokens in messages."""
        return sum(m.tokens for m in messages)

    @staticmethod
    def estimate_message_tokens(role: str, content: Any) -> int:
        """Estimate tokens for a single message."""
        overhead = 4
        if isinstance(content, str):
            content_tokens = TokenCounter.count_tokens(content)
        elif isinstance(content, list):
            content_tokens = sum(
                TokenCounter.count_tokens(c.get("text", "")) for c in content if isinstance(c, dict)
            )
        else:
            content_tokens = TokenCounter.count_tokens(str(content))
        return content_tokens + overhead


class ScrapManager:
    """Manages scrap files for large tool outputs."""

    def __init__(self, scrap_dir: str = None):
        self.scrap_dir = scrap_dir or os.path.join(tempfile.gettempdir(), "nanocode", "scrap")
        os.makedirs(self.scrap_dir, exist_ok=True)

    def save(self, content: str, extension: str = "txt") -> str:
        """Save content to scrap file and return path."""
        import hashlib
        import uuid

        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        filename = f"scrap_{uuid.uuid4().hex[:8]}_{content_hash}.{extension}"
        filepath = os.path.join(self.scrap_dir, filename)

        with open(filepath, "w") as f:
            f.write(content)

        return filepath

    def read(self, filepath: str) -> str:
        """Read content from scrap file."""
        if not os.path.exists(filepath):
            return ""
        with open(filepath, "r") as f:
            return f.read()

    def delete(self, filepath: str):
        """Delete scrap file."""
        if os.path.exists(filepath):
            os.remove(filepath)


class ContextManager:
    """Manages conversation context within token limits."""

    def __init__(
        self,
        max_tokens: int = 8000,
        strategy: ContextStrategy = ContextStrategy.SLIDING_WINDOW,
        preserve_system: bool = True,
        preserve_last_n: int = 3,
        llm=None,
        session_id: str = None,
        storage=None,
        model: str = "gpt-4o",
        compaction_enabled: bool = True,
    ):
        self.max_tokens = max_tokens
        self.strategy = strategy
        self.preserve_system = preserve_system
        self.preserve_last_n = preserve_last_n
        self.llm = llm
        self.session_id = session_id
        self.storage = storage
        self.model = model
        self.compaction_enabled = compaction_enabled

        self._system_parts: list[MessagePart] = []
        self._messages: list[Message] = []
        self._token_buffer = max_tokens // 10
        self._scrap_manager = ScrapManager()

        model_limits = ModelLimits.get_limits_sync(model)
        self._context_limit = model_limits["context"]
        self._output_limit = model_limits["output"]
        self._reserved_tokens = min(2000, self._output_limit // 4)

    async def init_async(self):
        """Async initialization - load model limits from registry."""
        await ModelLimits.load_registry()
        model_limits = ModelLimits.get_limits_sync(self.model)
        self._context_limit = model_limits["context"]
        self._output_limit = model_limits["output"]
        self._reserved_tokens = min(2000, self._output_limit // 4)

    def set_system_prompt(self, content: str):
        """Set the system prompt as text part."""
        self._system_parts.clear()
        self._system_parts.append(
            MessagePart(
                part_type=MessagePartType.TEXT,
                content=content,
                tokens=TokenCounter.count_tokens(content),
            )
        )

    def add_system_prompt(self, content: str):
        """Add a system prompt part (supports multi-part prompts)."""
        self._system_parts.append(
            MessagePart(
                part_type=MessagePartType.TEXT,
                content=content,
                tokens=TokenCounter.count_tokens(content),
            )
        )

    def add_message(self, role: str, content: Any = None, tool_call_id: str = None):
        """Add a message to context."""
        msg = Message(role=role)

        if content:
            if isinstance(content, str):
                msg.add_text(content)
            elif isinstance(content, dict):
                if content.get("type") == "text":
                    msg.add_text(content.get("text", ""))
                elif content.get("type") == "reasoning":
                    msg.add_reasoning(
                        content.get("text", ""),
                        content.get("provider_metadata"),
                    )
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict):
                        if c.get("type") == "text":
                            msg.add_text(c.get("text", ""))
                        elif c.get("type") == "reasoning":
                            msg.add_reasoning(
                                c.get("text", ""),
                                c.get("provider_metadata"),
                            )

        msg.importance = self._calculate_importance(role, msg.get_text_content())
        self._messages.append(msg)

        if self.storage and self.session_id:
            self._persist_message(msg)

    def add_tool_result(
        self, tool_name: str, tool_call_id: str, content: str, max_scrap_size: int = 10000
    ):
        """Add a tool result message, using scrap for large content."""
        tokens = TokenCounter.count_tokens(content)

        if tokens > max_scrap_size // 4:
            scrap_path = self._scrap_manager.save(content)
            truncated = f"[Output truncated. Full output saved to: {scrap_path}]\n\nUse the Read tool to access the full content."
            content = truncated

        msg = Message(role="tool")
        msg.add_tool_result(tool_name, tool_call_id, content)
        self._messages.append(msg)

        if self.storage and self.session_id:
            self._persist_message(msg)

    def _serialize_content(self, content: Any) -> str:
        """Serialize message content to string."""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") == "text":
                        parts.append(c.get("text", ""))
                    elif c.get("type") == "image_url":
                        parts.append("[image]")
            return " ".join(parts)
        return str(content)

    async def _persist_message(self, message: Message):
        """Persist message to database."""
        try:
            content = message.get_text_content()
            await self.storage.add_message(
                session_id=self.session_id,
                role=message.role,
                content=content,
                tool_call_id=None,
                tokens=message.tokens,
            )
        except Exception:
            pass

    async def load_from_storage(self):
        """Load messages from persistent storage."""
        if not self.storage or not self.session_id:
            return

        try:
            messages = await self.storage.get_messages(self.session_id)
            for msg in messages:
                message = Message(role=msg.role)
                message.add_text(msg.content)
                message.tokens = msg.tokens
                message.timestamp = msg.created_at
                self._messages.append(message)
        except Exception:
            pass

    async def save_to_storage(self):
        """Save all messages to persistent storage."""
        if not self.storage or not self.session_id:
            return

        try:
            await self.storage.clear_messages(self.session_id)
            for msg in self._messages:
                content = msg.get_text_content()
                await self.storage.add_message(
                    session_id=self.session_id,
                    role=msg.role,
                    content=content,
                    tool_call_id=None,
                    tokens=msg.tokens,
                )
        except Exception:
            pass

    def _calculate_importance(self, role: str, content: str) -> float:
        """Calculate message importance score."""
        base = 0.5

        if role == "system":
            return 1.0
        elif role == "user":
            return 0.8
        elif role == "assistant":
            base = 0.6
        elif role == "tool":
            base = 0.4

        if len(content) > 5000:
            base *= 0.8

        return base

    def _get_messages_for_llm(self) -> list[dict]:
        """Get messages in format for LLM API."""
        result = []

        if self._system_parts and self.preserve_system:
            result.append(
                {
                    "role": "system",
                    "content": " ".join(p.content for p in self._system_parts),
                }
            )

        for msg in self._messages:
            result.append(msg.to_dict())

        return result

    def prepare_messages(self) -> list[dict]:
        """Prepare messages for LLM call, applying strategy."""
        if self.compaction_enabled and self.strategy == ContextStrategy.COMPACTION:
            self._maybe_compact()

        if self.strategy == ContextStrategy.SLIDING_WINDOW:
            return self._sliding_window()
        elif self.strategy == ContextStrategy.SUMMARY:
            return self._summary_strategy()
        elif self.strategy == ContextStrategy.IMPORTANCE:
            return self._importance_strategy()
        elif self.strategy == ContextStrategy.COMPACTION:
            return self._compaction_strategy()

        return self._get_messages_for_llm()

    def _maybe_compact(self):
        """Check if compaction is needed and trigger if so."""
        total = TokenCounter.count_messages_tokens(self._messages)
        usable_context = self._context_limit - self._reserved_tokens

        if total >= usable_context:
            self._compact()

    def _compact(self):
        """Compact messages by summarizing old ones."""
        if not self.llm:
            return

        import asyncio

        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(self._compact_async())
        except RuntimeError:
            pass

    async def _compact_async(self):
        """Async compaction - summarize old messages."""
        if len(self._messages) < 4:
            return

        recent = self._messages[-self.preserve_last_n :]
        older = self._messages[: -self.preserve_last_n]

        if not older:
            return

        summary_text = await self._create_summary(older)

        summary_msg = Message(role="system")
        summary_msg.add_text(f"[Previous conversation summary]\n{summary_text}")

        compacted_msg = Message(role="assistant")
        compacted_msg.add_text("[Conversation compacted - see summary above]")
        compacted_msg.summary = summary_text

        self._messages = [compacted_msg] + recent

    def _compaction_strategy(self) -> list[dict]:
        """Compaction-based strategy."""
        self._maybe_compact()
        return self._get_messages_for_llm()

    def _sliding_window(self) -> list[dict]:
        """Apply sliding window strategy."""
        messages = []

        if self._system_parts and self.preserve_system:
            system_tokens = sum(p.tokens for p in self._system_parts)
        else:
            system_tokens = 0

        recent_messages = self._messages[-self.preserve_last_n :] if self._messages else []

        result_messages = []
        current_tokens = system_tokens

        for msg in reversed(recent_messages):
            if current_tokens + msg.tokens > self.max_tokens - self._token_buffer:
                break
            result_messages.insert(0, msg)
            current_tokens += msg.tokens

        older = (
            [m for m in self._messages[: -self.preserve_last_n]]
            if self.preserve_last_n > 0
            else self._messages
        )

        for msg in reversed(older):
            if current_tokens + msg.tokens > self.max_tokens - self._token_buffer:
                continue
            result_messages.insert(
                (
                    len([m for m in result_messages if m.role == "system"]) + 1
                    if self._system_parts and self.preserve_system
                    else 1
                ),
                msg,
            )
            current_tokens += msg.tokens

        return self._messages_to_dict(result_messages)

    def _messages_to_dict(self, messages: list[Message]) -> list[dict]:
        """Convert messages to dict format."""
        result = []

        if self._system_parts and self.preserve_system:
            result.append(
                {
                    "role": "system",
                    "content": " ".join(p.content for p in self._system_parts),
                }
            )

        for msg in messages:
            result.append(msg.to_dict())

        return result

    def _summary_strategy(self) -> list[dict]:
        """Apply summary strategy (requires LLM)."""
        if not self.llm:
            return self._sliding_window()

        total = TokenCounter.count_messages_tokens(self._messages)

        if total < self.max_tokens * 0.7:
            return self._get_messages_for_llm()

        recent = self._messages[-self.preserve_last_n :]
        older = self._messages[: -self.preserve_last_n]

        if older:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    summary_text = f"[{len(older)} messages from earlier in the conversation]"
                else:
                    summary_text = loop.run_until_complete(self._create_summary(older))
            except:
                summary_text = f"[{len(older)} messages from earlier in the conversation]"

            summary_msg = Message(role="system")
            summary_msg.add_text(f"[Previous conversation summary]\n{summary_text}")

            messages = []
            if self._system_parts and self.preserve_system:
                messages.append(
                    {
                        "role": "system",
                        "content": " ".join(p.content for p in self._system_parts),
                    }
                )
            messages.append(summary_msg.to_dict())
            messages.extend([m.to_dict() for m in recent])
            return messages

        return self._get_messages_for_llm()

    async def _create_summary(self, messages: list[Message]) -> str:
        """Create summary of older messages using LLM."""
        conversation = "\n".join(f"{m.role}: {m.get_text_content()[:500]}" for m in messages)

        prompt = f"""Summarize this conversation concisely, preserving key information:
        
{conversation}

Summary:"""

        try:
            from nanocode.llm import Message as LLMMessage

            response = await self.llm.chat([LLMMessage("user", prompt)])
            return response.content[:1500]
        except:
            return f"[{len(messages)} messages from earlier in the conversation]"

    def _importance_strategy(self) -> list[dict]:
        """Apply importance-based strategy."""
        scored = []

        for i, msg in enumerate(self._messages):
            recency_boost = 1.0 - (len(self._messages) - i) * 0.01
            score = msg.importance * recency_boost
            scored.append((score, msg))

        scored.sort(key=lambda x: x[0], reverse=True)

        result_messages = []
        current_tokens = (
            sum(p.tokens for p in self._system_parts)
            if self._system_parts and self.preserve_system
            else 0
        )

        for _, msg in scored:
            if current_tokens + msg.tokens > self.max_tokens - self._token_buffer:
                continue
            result_messages.append(msg)
            current_tokens += msg.tokens

        result_messages.sort(key=lambda m: m.timestamp)

        return self._messages_to_dict(result_messages)

    def truncate_tool_result(self, content: str, max_tokens: int = 500) -> str:
        """Truncate long tool results intelligently."""
        tokens = TokenCounter.count_tokens(content)

        if tokens <= max_tokens:
            return content

        lines = content.split("\n")
        result_lines = []
        current_tokens = 0

        for line in lines:
            line_tokens = TokenCounter.count_tokens(line)
            if current_tokens + line_tokens > max_tokens - 50:
                result_lines.append(f"... [truncated {tokens - current_tokens} tokens]")
                break
            result_lines.append(line)
            current_tokens += line_tokens

        return "\n".join(result_lines)

    def get_token_usage(self) -> dict:
        """Get current token usage statistics."""
        total = TokenCounter.count_messages_tokens(self._messages)
        if self._system_parts:
            total += sum(p.tokens for p in self._system_parts)

        usable = self._context_limit - self._reserved_tokens

        return {
            "current_tokens": total,
            "max_tokens": self.max_tokens,
            "context_limit": self._context_limit,
            "usable_context": usable,
            "output_limit": self._output_limit,
            "reserved_tokens": self._reserved_tokens,
            "usage_percent": (total / self.max_tokens) * 100 if self.max_tokens > 0 else 0,
            "context_usage_percent": (total / usable) * 100 if usable > 0 else 0,
            "message_count": len(self._messages),
        }

    def clear(self):
        """Clear all messages (except system)."""
        self._messages.clear()

    def save_to_file(self, path: str):
        """Save context to file."""
        data = {
            "system": (
                " ".join(p.content for p in self._system_parts) if self._system_parts else None
            ),
            "messages": [
                {
                    "role": m.role,
                    "content": m.get_text_content(),
                    "timestamp": m.timestamp.isoformat(),
                    "tokens": m.tokens,
                }
                for m in self._messages
            ],
            "model": self.model,
            "limits": {
                "context": self._context_limit,
                "output": self._output_limit,
            },
        }
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_from_file(self, path: str):
        """Load context from file."""
        if not os.path.exists(path):
            return

        with open(path) as f:
            data = json.load(f)

        if data.get("system"):
            self.set_system_prompt(data["system"])

        if data.get("model"):
            self.model = data["model"]
            limits = ModelLimits.get_limits(self.model)
            self._context_limit = limits["context"]
            self._output_limit = limits["output"]
            self._reserved_tokens = min(2000, self._output_limit // 4)

        self._messages.clear()
        for m in data.get("messages", []):
            msg = Message(role=m["role"])
            msg.add_text(m["content"])
            msg.tokens = m.get("tokens", TokenCounter.count_tokens(m["content"]))
            if "timestamp" in m:
                msg.timestamp = datetime.fromisoformat(m["timestamp"])
            self._messages.append(msg)
