"""Cost Tracking - Per-model pricing with session cost display.

Based on Aura's cost tracking:
- Per-model pricing with three buckets: input_miss, input_hit, output
- Track session cost
- Display in TUI/CLI
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelPricing:
    """Pricing for a specific model."""

    model_id: str
    provider: str
    input_price_per_mtoken: float = 0.0  # Price per million input tokens (cache miss)
    input_cache_hit_price_per_mtoken: float = 0.0  # Price per million input tokens (cache hit)
    output_price_per_mtoken: float = 0.0  # Price per million output tokens

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_hit_tokens: int = 0,
    ) -> float:
        """Calculate cost for token usage.

        Args:
            input_tokens: Total input tokens
            output_tokens: Output tokens
            cache_hit_tokens: Tokens served from cache

        Returns:
            Cost in dollars
        """
        # Input cost (cache miss)
        input_miss_tokens = input_tokens - cache_hit_tokens
        input_cost = (input_miss_tokens / 1_000_000) * self.input_price_per_mtoken

        # Input cost (cache hit)
        cache_cost = (cache_hit_tokens / 1_000_000) * self.input_cache_hit_price_per_mtoken

        # Output cost
        output_cost = (output_tokens / 1_000_000) * self.output_price_per_mtoken

        return input_cost + cache_cost + output_cost


# Default pricing for major models (prices per million tokens)
DEFAULT_PRICING: Dict[str, ModelPricing] = {
    # OpenAI models
    "gpt-4o": ModelPricing("gpt-4o", "openai", 2.50, 1.25, 10.00),
    "gpt-4o-mini": ModelPricing("gpt-4o-mini", "openai", 0.15, 0.075, 0.60),
    "gpt-4-turbo": ModelPricing("gpt-4-turbo", "openai", 10.00, 5.00, 30.00),
    "gpt-4": ModelPricing("gpt-4", "openai", 30.00, 15.00, 60.00),
    "gpt-3.5-turbo": ModelPricing("gpt-3.5-turbo", "openai", 0.50, 0.25, 1.50),
    "o1": ModelPricing("o1", "openai", 15.00, 7.50, 60.00),
    "o1-mini": ModelPricing("o1-mini", "openai", 3.00, 1.50, 12.00),

    # Anthropic models
    "claude-3-5-sonnet-20241022": ModelPricing("claude-3-5-sonnet-20241022", "anthropic", 3.00, 0.30, 15.00),
    "claude-3-5-haiku-20241022": ModelPricing("claude-3-5-haiku-20241022", "anthropic", 0.80, 0.08, 4.00),
    "claude-3-opus-20240229": ModelPricing("claude-3-opus-20240229", "anthropic", 15.00, 1.50, 75.00),
    "claude-3-sonnet-20240229": ModelPricing("claude-3-sonnet-20240229", "anthropic", 3.00, 0.30, 15.00),
    "claude-3-haiku-20240307": ModelPricing("claude-3-haiku-20240307", "anthropic", 0.25, 0.025, 1.25),

    # Google models
    "gemini-1.5-pro": ModelPricing("gemini-1.5-pro", "google", 1.25, 0.3125, 5.00),
    "gemini-1.5-flash": ModelPricing("gemini-1.5-flash", "google", 0.075, 0.01875, 0.30),
    "gemini-2.0-flash": ModelPricing("gemini-2.0-flash", "google", 0.10, 0.025, 0.40),

    # Meta models (via various providers)
    "llama-3.1-405b": ModelPricing("llama-3.1-405b", "meta", 3.00, 0.60, 3.00),
    "llama-3.1-70b": ModelPricing("llama-3.1-70b", "meta", 0.59, 0.118, 0.79),
    "llama-3.1-8b": ModelPricing("llama-3.1-8b", "meta", 0.10, 0.02, 0.10),

    # Mistral models
    "mistral-large": ModelPricing("mistral-large", "mistral", 2.00, 0.40, 6.00),
    "mistral-medium": ModelPricing("mistral-medium", "mistral", 2.70, 0.54, 8.10),

    # DeepSeek models
    "deepseek-chat": ModelPricing("deepseek-chat", "deepseek", 0.14, 0.014, 0.28),
    "deepseek-coder": ModelPricing("deepseek-coder", "deepseek", 0.14, 0.014, 0.28),
}


@dataclass
class TokenUsage:
    """Token usage for a single request."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class CostEntry:
    """A single cost entry."""

    model_id: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cost: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionCost:
    """Total cost for a session."""

    session_id: str
    entries: List[CostEntry] = field(default_factory=list)
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_hit_tokens: int = 0

    def add_entry(self, entry: CostEntry):
        """Add a cost entry."""
        self.entries.append(entry)
        self.total_cost += entry.cost
        self.total_input_tokens += entry.input_tokens
        self.total_output_tokens += entry.output_tokens
        self.total_cache_hit_tokens += entry.cache_hit_tokens


class CostTracker:
    """Tracks costs for LLM API usage.

    Based on Aura's cost tracking:
    - Per-model pricing with three buckets
    - Track session cost
    - Display statistics
    """

    def __init__(
        self,
        custom_pricing: Optional[Dict[str, ModelPricing]] = None,
        storage_dir: Optional[str] = None,
    ):
        """Initialize the cost tracker.

        Args:
            custom_pricing: Custom pricing overrides
            storage_dir: Directory to store cost data
        """
        self.pricing = {**DEFAULT_PRICING}
        if custom_pricing:
            self.pricing.update(custom_pricing)

        if storage_dir is None:
            xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
            storage_dir = str(Path(xdg_data) / "nanocode" / "costs")
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

        self._sessions: Dict[str, SessionCost] = {}
        self._global_cost: float = 0.0

    def get_pricing(self, model_id: str) -> Optional[ModelPricing]:
        """Get pricing for a model.

        Args:
            model_id: Model identifier

        Returns:
            ModelPricing if found, None otherwise
        """
        # Try exact match
        if model_id in self.pricing:
            return self.pricing[model_id]

        # Try partial match
        for key, pricing in self.pricing.items():
            if key in model_id or model_id in key:
                return pricing

        return None

    def record_usage(
        self,
        session_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_hit_tokens: int = 0,
    ) -> float:
        """Record token usage and calculate cost.

        Args:
            session_id: Session identifier
            model_id: Model identifier
            input_tokens: Input tokens
            output_tokens: Output tokens
            cache_hit_tokens: Tokens served from cache

        Returns:
            Cost in dollars
        """
        pricing = self.get_pricing(model_id)
        if not pricing:
            logger.warning(f"No pricing found for model: {model_id}")
            return 0.0

        cost = pricing.calculate_cost(input_tokens, output_tokens, cache_hit_tokens)

        entry = CostEntry(
            model_id=model_id,
            provider=pricing.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_tokens=cache_hit_tokens,
            cost=cost,
        )

        # Add to session
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionCost(session_id=session_id)
        self._sessions[session_id].add_entry(entry)

        # Add to global
        self._global_cost += cost

        logger.debug(
            f"Cost recorded: ${cost:.6f} for {model_id} "
            f"(in={input_tokens}, out={output_tokens}, cache={cache_hit_tokens})"
        )

        return cost

    def get_session_cost(self, session_id: str) -> Optional[SessionCost]:
        """Get cost for a session."""
        return self._sessions.get(session_id)

    def get_global_cost(self) -> float:
        """Get total cost across all sessions."""
        return self._global_cost

    def get_stats(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get cost statistics.

        Args:
            session_id: Optional session to get stats for

        Returns:
            Statistics dict
        """
        if session_id:
            session = self._sessions.get(session_id)
            if not session:
                return {"error": "Session not found"}
            return {
                "session_id": session_id,
                "total_cost": session.total_cost,
                "total_input_tokens": session.total_input_tokens,
                "total_output_tokens": session.total_output_tokens,
                "total_cache_hit_tokens": session.total_cache_hit_tokens,
                "cache_hit_rate": (
                    session.total_cache_hit_tokens / session.total_input_tokens
                    if session.total_input_tokens > 0
                    else 0
                ),
                "num_requests": len(session.entries),
            }

        # Global stats
        total_input = sum(s.total_input_tokens for s in self._sessions.values())
        total_output = sum(s.total_output_tokens for s in self._sessions.values())
        total_cache = sum(s.total_cache_hit_tokens for s in self._sessions.values())

        return {
            "global_cost": self._global_cost,
            "total_sessions": len(self._sessions),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cache_hit_tokens": total_cache,
            "cache_hit_rate": total_cache / total_input if total_input > 0 else 0,
        }

    def format_cost(self, cost: float) -> str:
        """Format cost for display."""
        if cost < 0.01:
            return f"${cost:.6f}"
        elif cost < 1.0:
            return f"${cost:.4f}"
        else:
            return f"${cost:.2f}"

    def format_session_summary(self, session_id: str) -> str:
        """Format session cost summary."""
        session = self._sessions.get(session_id)
        if not session:
            return "No cost data for this session"

        lines = [
            f"Session: {session_id}",
            f"Total Cost: {self.format_cost(session.total_cost)}",
            f"Requests: {len(session.entries)}",
            f"Input Tokens: {session.total_input_tokens:,}",
            f"Output Tokens: {session.total_output_tokens:,}",
            f"Cache Hit Tokens: {session.total_cache_hit_tokens:,}",
        ]

        if session.total_input_tokens > 0:
            cache_rate = session.total_cache_hit_tokens / session.total_input_tokens * 100
            lines.append(f"Cache Hit Rate: {cache_rate:.1f}%")

        return "\n".join(lines)

    def save_session(self, session_id: str) -> bool:
        """Save session cost data to disk."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        try:
            path = Path(self.storage_dir) / f"{session_id}.json"
            data = {
                "session_id": session.session_id,
                "total_cost": session.total_cost,
                "total_input_tokens": session.total_input_tokens,
                "total_output_tokens": session.total_output_tokens,
                "total_cache_hit_tokens": session.total_cache_hit_tokens,
                "entries": [
                    {
                        "model_id": e.model_id,
                        "provider": e.provider,
                        "input_tokens": e.input_tokens,
                        "output_tokens": e.output_tokens,
                        "cache_hit_tokens": e.cache_hit_tokens,
                        "cost": e.cost,
                        "timestamp": e.timestamp,
                    }
                    for e in session.entries
                ],
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save session cost: {e}")
            return False

    def load_session(self, session_id: str) -> bool:
        """Load session cost data from disk."""
        try:
            path = Path(self.storage_dir) / f"{session_id}.json"
            if not path.exists():
                return False

            with open(path) as f:
                data = json.load(f)

            session = SessionCost(session_id=session_id)
            session.total_cost = data.get("total_cost", 0)
            session.total_input_tokens = data.get("total_input_tokens", 0)
            session.total_output_tokens = data.get("total_output_tokens", 0)
            session.total_cache_hit_tokens = data.get("total_cache_hit_tokens", 0)

            for entry_data in data.get("entries", []):
                session.entries.append(
                    CostEntry(
                        model_id=entry_data["model_id"],
                        provider=entry_data["provider"],
                        input_tokens=entry_data["input_tokens"],
                        output_tokens=entry_data["output_tokens"],
                        cache_hit_tokens=entry_data.get("cache_hit_tokens", 0),
                        cost=entry_data["cost"],
                        timestamp=entry_data.get("timestamp", time.time()),
                    )
                )

            self._sessions[session_id] = session
            self._global_cost += session.total_cost
            return True

        except Exception as e:
            logger.error(f"Failed to load session cost: {e}")
            return False


# Global instance
_cost_tracker: Optional[CostTracker] = None


def get_cost_tracker(custom_pricing: Optional[Dict[str, ModelPricing]] = None) -> CostTracker:
    """Get or create the global cost tracker."""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker(custom_pricing)
    return _cost_tracker


def reset_cost_tracker():
    """Reset the global cost tracker."""
    global _cost_tracker
    _cost_tracker = None
