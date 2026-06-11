"""Tests for the Cost Tracking system."""

import pytest
import tempfile
from pathlib import Path

from nanocode.cost import (
    CostTracker,
    ModelPricing,
    SessionCost,
    CostEntry,
    TokenUsage,
    get_cost_tracker,
    reset_cost_tracker,
    DEFAULT_PRICING,
)


class TestModelPricing:
    """Tests for ModelPricing dataclass."""

    def test_pricing_creation(self):
        """Test creating pricing."""
        pricing = ModelPricing(
            model_id="gpt-4o",
            provider="openai",
            input_price_per_mtoken=2.50,
            input_cache_hit_price_per_mtoken=1.25,
            output_price_per_mtoken=10.00,
        )
        assert pricing.model_id == "gpt-4o"
        assert pricing.input_price_per_mtoken == 2.50

    def test_calculate_cost(self):
        """Test cost calculation."""
        pricing = ModelPricing(
            model_id="test",
            provider="test",
            input_price_per_mtoken=1.00,
            input_cache_hit_price_per_mtoken=0.50,
            output_price_per_mtoken=2.00,
        )

        # 1M input tokens (miss) + 1M output tokens
        cost = pricing.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_hit_tokens=0,
        )
        assert cost == 3.00  # $1.00 + $2.00

    def test_calculate_cost_with_cache(self):
        """Test cost calculation with cache hits."""
        pricing = ModelPricing(
            model_id="test",
            provider="test",
            input_price_per_mtoken=1.00,
            input_cache_hit_price_per_mtoken=0.50,
            output_price_per_mtoken=2.00,
        )

        # 1M input tokens (500k miss, 500k hit) + 1M output tokens
        cost = pricing.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_hit_tokens=500_000,
        )
        assert cost == 2.75  # $0.50 (miss) + $0.25 (hit) + $2.00 (output)


class TestSessionCost:
    """Tests for SessionCost dataclass."""

    def test_session_creation(self):
        """Test creating a session."""
        session = SessionCost(session_id="test-session")
        assert session.session_id == "test-session"
        assert session.total_cost == 0.0

    def test_add_entry(self):
        """Test adding an entry."""
        session = SessionCost(session_id="test")
        entry = CostEntry(
            model_id="gpt-4o",
            provider="openai",
            input_tokens=1000,
            output_tokens=500,
            cache_hit_tokens=0,
            cost=0.01,
        )
        session.add_entry(entry)
        assert session.total_cost == 0.01
        assert session.total_input_tokens == 1000
        assert session.total_output_tokens == 500


class TestCostTracker:
    """Tests for CostTracker."""

    def test_init(self, tmp_path):
        """Test initialization."""
        tracker = CostTracker(storage_dir=str(tmp_path))
        assert tracker.storage_dir == str(tmp_path)

    def test_get_pricing(self):
        """Test getting pricing."""
        tracker = CostTracker()

        # Exact match
        pricing = tracker.get_pricing("gpt-4o")
        assert pricing is not None
        assert pricing.model_id == "gpt-4o"

        # Partial match
        pricing = tracker.get_pricing("gpt-4o-mini-2024")
        assert pricing is not None

        # Not found
        pricing = tracker.get_pricing("unknown-model")
        assert pricing is None

    def test_record_usage(self):
        """Test recording usage."""
        tracker = CostTracker()

        cost = tracker.record_usage(
            session_id="test-session",
            model_id="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )

        assert cost > 0
        assert tracker.get_global_cost() > 0

    def test_record_usage_unknown_model(self):
        """Test recording usage for unknown model."""
        tracker = CostTracker()

        cost = tracker.record_usage(
            session_id="test-session",
            model_id="unknown-model",
            input_tokens=1000,
            output_tokens=500,
        )

        assert cost == 0.0

    def test_get_session_cost(self):
        """Test getting session cost."""
        tracker = CostTracker()

        tracker.record_usage("session-1", "gpt-4o", 1000, 500)
        session = tracker.get_session_cost("session-1")

        assert session is not None
        assert session.total_cost > 0

    def test_get_session_cost_not_found(self):
        """Test getting non-existent session cost."""
        tracker = CostTracker()
        session = tracker.get_session_cost("nonexistent")
        assert session is None

    def test_get_stats_global(self):
        """Test getting global stats."""
        tracker = CostTracker()

        tracker.record_usage("session-1", "gpt-4o", 1000, 500)
        tracker.record_usage("session-2", "gpt-4o-mini", 2000, 1000)

        stats = tracker.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["global_cost"] > 0

    def test_get_stats_session(self):
        """Test getting session stats."""
        tracker = CostTracker()

        tracker.record_usage("session-1", "gpt-4o", 1000, 500, cache_hit_tokens=200)
        stats = tracker.get_stats("session-1")

        assert stats["session_id"] == "session-1"
        assert stats["total_input_tokens"] == 1000
        assert stats["cache_hit_rate"] == 0.2

    def test_format_cost(self):
        """Test cost formatting."""
        tracker = CostTracker()

        assert tracker.format_cost(0.001) == "$0.001000"
        assert tracker.format_cost(0.05) == "$0.0500"
        assert tracker.format_cost(1.50) == "$1.50"

    def test_format_session_summary(self):
        """Test session summary formatting."""
        tracker = CostTracker()

        tracker.record_usage("session-1", "gpt-4o", 1000, 500)
        summary = tracker.format_session_summary("session-1")

        assert "session-1" in summary
        assert "Total Cost" in summary

    def test_save_and_load_session(self, tmp_path):
        """Test saving and loading session."""
        tracker = CostTracker(storage_dir=str(tmp_path))

        tracker.record_usage("session-1", "gpt-4o", 1000, 500)
        saved = tracker.save_session("session-1")
        assert saved is True

        # Create new tracker and load
        tracker2 = CostTracker(storage_dir=str(tmp_path))
        loaded = tracker2.load_session("session-1")
        assert loaded is True
        assert tracker2.get_session_cost("session-1") is not None


class TestDefaultPricing:
    """Tests for default pricing."""

    def test_default_pricing_exists(self):
        """Test that default pricing exists."""
        assert len(DEFAULT_PRICING) > 0

    def test_gpt4o_pricing(self):
        """Test GPT-4o pricing."""
        pricing = DEFAULT_PRICING.get("gpt-4o")
        assert pricing is not None
        assert pricing.input_price_per_mtoken == 2.50

    def test_claude_pricing(self):
        """Test Claude pricing."""
        pricing = DEFAULT_PRICING.get("claude-3-5-sonnet-20241022")
        assert pricing is not None
        assert pricing.input_price_per_mtoken == 3.00


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_cost_tracker_singleton(self):
        """Test global instance is singleton."""
        reset_cost_tracker()
        t1 = get_cost_tracker()
        t2 = get_cost_tracker()
        assert t1 is t2

    def test_reset_cost_tracker(self):
        """Test resetting global instance."""
        t1 = get_cost_tracker()
        reset_cost_tracker()
        t2 = get_cost_tracker()
        assert t1 is not t2
