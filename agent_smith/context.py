"""Efficient context management for the agent."""

import json
import os
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class ContextStrategy(Enum):
    """Context management strategies."""
    SLIDING_WINDOW = "sliding_window"
    SUMMARY = "summary"
    IMPORTANCE = "importance"


@dataclass
class MessageToken:
    """A message with token count."""
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


class TokenCounter:
    """Estimate token counts for messages."""

    @staticmethod
    def count_tokens(text: str) -> int:
        """Count tokens using approximation (faster than tiktoken).
        
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
    def count_messages_tokens(messages: list[MessageToken]) -> int:
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
                TokenCounter.count_tokens(c.get("text", ""))
                for c in content
                if isinstance(c, dict)
            )
        else:
            content_tokens = TokenCounter.count_tokens(str(content))
        return content_tokens + overhead


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
    ):
        self.max_tokens = max_tokens
        self.strategy = strategy
        self.preserve_system = preserve_system
        self.preserve_last_n = preserve_last_n
        self.llm = llm
        self.session_id = session_id
        self.storage = storage
        
        self._system_message: Optional[MessageToken] = None
        self._messages: list[MessageToken] = []
        self._token_buffer = max_tokens // 10

    def set_system_prompt(self, content: str):
        """Set the system prompt."""
        tokens = TokenCounter.estimate_message_tokens("system", content)
        self._system_message = MessageToken(
            role="system",
            content=content,
            tokens=tokens,
            importance=1.0,
        )

    def add_message(self, role: str, content: Any, tool_call_id: str = None):
        """Add a message to context."""
        content_str = self._serialize_content(content)
        tokens = TokenCounter.estimate_message_tokens(role, content_str)
        
        msg = MessageToken(
            role=role,
            content=content_str,
            tool_call_id=tool_call_id,
            tokens=tokens,
            importance=self._calculate_importance(role, content_str),
        )
        self._messages.append(msg)

        if self.storage and self.session_id:
            self._persist_message(role, content_str, tool_call_id, tokens)

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

    async def _persist_message(self, role: str, content: str, tool_call_id: str, tokens: int):
        """Persist message to database."""
        try:
            await self.storage.add_message(
                session_id=self.session_id,
                role=role,
                content=content,
                tool_call_id=tool_call_id,
                tokens=tokens,
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
                self._messages.append(MessageToken(
                    role=msg.role,
                    content=msg.content,
                    tool_call_id=msg.tool_call_id,
                    tokens=msg.tokens,
                    timestamp=msg.created_at,
                ))
        except Exception:
            pass

    async def save_to_storage(self):
        """Save all messages to persistent storage."""
        if not self.storage or not self.session_id:
            return
        
        try:
            await self.storage.clear_messages(self.session_id)
            for msg in self._messages:
                await self.storage.add_message(
                    session_id=self.session_id,
                    role=msg.role,
                    content=msg.content,
                    tool_call_id=msg.tool_call_id,
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
        
        if self._system_message and self.preserve_system:
            result.append(self._system_message.to_dict())
        
        for msg in self._messages:
            result.append(msg.to_dict())
        
        return result

    def prepare_messages(self) -> list[dict]:
        """Prepare messages for LLM call, applying strategy."""
        if self.strategy == ContextStrategy.SLIDING_WINDOW:
            return self._sliding_window()
        elif self.strategy == ContextStrategy.SUMMARY:
            return self._summary_strategy()
        elif self.strategy == ContextStrategy.IMPORTANCE:
            return self._importance_strategy()
        return self._get_messages_for_llm()

    def _sliding_window(self) -> list[dict]:
        """Apply sliding window strategy."""
        messages = []
        
        if self._system_message and self.preserve_system:
            messages.append(self._system_message)
        
        current_tokens = (
            self._system_message.tokens if self._system_message and self.preserve_system else 0
        )
        
        recent_messages = self._messages[-self.preserve_last_n:] if self._messages else []
        
        for msg in reversed(recent_messages):
            if current_tokens + msg.tokens > self.max_tokens - self._token_buffer:
                break
            messages.insert(len([m for m in messages if m.role != "system"]), msg)
            current_tokens += msg.tokens
        
        older = [m for m in self._messages[:-self.preserve_last_n]] if self.preserve_last_n > 0 else self._messages
        
        for msg in reversed(older):
            if current_tokens + msg.tokens > self.max_tokens - self._token_buffer:
                continue
            messages.insert(1, msg)
            current_tokens += msg.tokens
        
        return [m.to_dict() for m in messages]

    def _summary_strategy(self) -> list[dict]:
        """Apply summary strategy (requires LLM)."""
        if not self.llm:
            return self._sliding_window()
        
        total = TokenCounter.count_messages_tokens(self._messages)
        
        if total < self.max_tokens * 0.7:
            return self._get_messages_for_llm()
        
        recent = self._messages[-self.preserve_last_n:]
        recent_tokens = TokenCounter.count_messages_tokens(recent)
        
        older = self._messages[:-self.preserve_last_n]
        
        if older:
            summary_text = self._create_summary(older)
            summary_msg = MessageToken(
                role="system",
                content=f"[Previous conversation summary]\n{summary_text}",
                tokens=TokenCounter.count_tokens(summary_text),
                importance=0.7,
            )
            messages = []
            if self._system_message and self.preserve_system:
                messages.append(self._system_message)
            messages.append(summary_msg)
            messages.extend(recent)
            return [m.to_dict() for m in messages]
        
        return self._get_messages_for_llm()

    async def _create_summary(self, messages: list[MessageToken]) -> str:
        """Create summary of older messages using LLM."""
        from agent_smith.llm import Message
        
        conversation = "\n".join(
            f"{m.role}: {m.content[:500]}" for m in messages
        )
        
        prompt = f"""Summarize this conversation concisely, preserving key information:
        
{conversation}

Summary:"""
        
        try:
            response = await self.llm.chat([Message("user", prompt)])
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
        
        messages = []
        if self._system_message and self.preserve_system:
            messages.append(self._system_message)
        
        current_tokens = (
            self._system_message.tokens if self._system_message and self.preserve_system else 0
        )
        
        for _, msg in scored:
            if current_tokens + msg.tokens > self.max_tokens - self._token_buffer:
                continue
            messages.append(msg)
            current_tokens += msg.tokens
        
        messages.sort(key=lambda m: m.timestamp)
        
        return [m.to_dict() for m in messages]

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
        if self._system_message:
            total += self._system_message.tokens
        
        return {
            "current_tokens": total,
            "max_tokens": self.max_tokens,
            "usage_percent": (total / self.max_tokens) * 100,
            "message_count": len(self._messages),
        }

    def clear(self):
        """Clear all messages (except system)."""
        self._messages.clear()

    def save_to_file(self, path: str):
        """Save context to file."""
        data = {
            "system": self._system_message.content if self._system_message else None,
            "messages": [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp.isoformat()}
                for m in self._messages
            ],
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
        
        self._messages.clear()
        for m in data.get("messages", []):
            msg = MessageToken(
                role=m["role"],
                content=m["content"],
                tokens=TokenCounter.count_tokens(m["content"]),
            )
            if "timestamp" in m:
                msg.timestamp = datetime.fromisoformat(m["timestamp"])
            self._messages.append(msg)
