"""Tests for the Provider Registry."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanocode.provider_registry import (
    ProviderRegistry,
    ProviderSpec,
    ModelSpec,
    get_provider_registry,
    reset_provider_registry,
)


class TestProviderSpec:
    """Tests for ProviderSpec dataclass."""

    def test_spec_creation(self):
        """Test creating a provider spec."""
        spec = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="https://api.openai.com/v1",
        )
        assert spec.id == "openai"
        assert spec.name == "OpenAI"

    def test_get_model(self):
        """Test getting a model from spec."""
        model = ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai")
        spec = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="https://api.openai.com/v1",
            models={"gpt-4o": model},
        )
        assert spec.get_model("gpt-4o") is model
        assert spec.get_model("unknown") is None

    def test_list_models(self):
        """Test listing models in spec."""
        spec = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="https://api.openai.com/v1",
            models={"gpt-4o": ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai")},
        )
        assert spec.list_models() == ["gpt-4o"]

    def test_to_dict(self):
        """Test converting to dict."""
        spec = ProviderSpec(id="test", name="Test", api_base="http://test.com")
        d = spec.to_dict()
        assert d["id"] == "test"
        assert "model_count" in d


class TestModelSpec:
    """Tests for ModelSpec dataclass."""

    def test_spec_creation(self):
        """Test creating a model spec."""
        spec = ModelSpec(
            id="gpt-4o",
            name="GPT-4o",
            provider_id="openai",
            context_limit=128000,
        )
        assert spec.id == "gpt-4o"
        assert spec.context_limit == 128000

    def test_to_dict(self):
        """Test converting to dict."""
        spec = ModelSpec(id="test", name="Test", provider_id="test")
        d = spec.to_dict()
        assert d["id"] == "test"
        assert d["supports_tools"] is True

    def test_from_model_info(self):
        """Test creating from ModelInfo."""
        from nanocode.llm.registry import ModelInfo

        info = ModelInfo(
            id="gpt-4o",
            name="GPT-4o",
            provider_id="openai",
            api_endpoint="https://api.openai.com/v1",
            context_limit=128000,
        )
        spec = ModelSpec.from_model_info(info)
        assert spec.id == "gpt-4o"
        assert spec.context_limit == 128000


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def test_init(self, tmp_path):
        """Test initialization."""
        registry = ProviderRegistry(cache_dir=str(tmp_path))
        assert registry.cache_dir == tmp_path

    def test_get_provider(self):
        """Test getting a provider."""
        registry = ProviderRegistry()
        registry._providers["openai"] = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="https://api.openai.com/v1",
        )
        assert registry.get_provider("openai") is not None
        assert registry.get_provider("unknown") is None

    def test_get_model(self):
        """Test getting a model."""
        registry = ProviderRegistry()
        model = ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai")
        registry._providers["openai"] = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="https://api.openai.com/v1",
            models={"gpt-4o": model},
        )
        assert registry.get_model("openai", "gpt-4o") is model

    def test_get_model_by_full_id(self):
        """Test getting model by full ID."""
        registry = ProviderRegistry()
        model = ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai")
        registry._providers["openai"] = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="https://api.openai.com/v1",
            models={"gpt-4o": model},
        )
        assert registry.get_model_by_full_id("openai/gpt-4o") is model

    def test_list_providers(self):
        """Test listing providers."""
        registry = ProviderRegistry()
        registry._providers["openai"] = ProviderSpec(id="openai", name="OpenAI", api_base="")
        registry._providers["anthropic"] = ProviderSpec(id="anthropic", name="Anthropic", api_base="")
        assert sorted(registry.list_providers()) == ["anthropic", "openai"]

    def test_list_models(self):
        """Test listing models."""
        registry = ProviderRegistry()
        registry._providers["openai"] = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="",
            models={"gpt-4o": ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai")},
        )
        assert "gpt-4o" in registry.list_models("openai")

    def test_search_models(self):
        """Test searching models."""
        registry = ProviderRegistry()
        registry._providers["openai"] = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="",
            models={"gpt-4o": ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai")},
        )
        results = registry.search_models("gpt")
        assert len(results) >= 1

    def test_search_models_with_filters(self):
        """Test searching models with filters."""
        registry = ProviderRegistry()
        registry._providers["openai"] = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="",
            models={
                "gpt-4o": ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai", supports_vision=True),
                "gpt-4o-mini": ModelSpec(id="gpt-4o-mini", name="GPT-4o Mini", provider_id="openai", supports_vision=False),
            },
        )
        results = registry.search_models("gpt", supports_vision=True)
        assert len(results) == 1
        assert results[0].id == "gpt-4o"

    def test_get_free_models(self):
        """Test getting free models."""
        registry = ProviderRegistry()
        registry._providers["test"] = ProviderSpec(
            id="test",
            name="Test",
            api_base="",
            models={
                "free": ModelSpec(id="free", name="Free", provider_id="test", input_cost=0, output_cost=0),
                "paid": ModelSpec(id="paid", name="Paid", provider_id="test", input_cost=1.0),
            },
        )
        free = registry.get_free_models()
        assert len(free) == 1
        assert free[0].id == "free"

    def test_import_custom_provider(self):
        """Test importing custom provider."""
        registry = ProviderRegistry()
        spec = ProviderSpec(id="custom", name="Custom", api_base="http://custom.com")
        result = registry.import_custom_provider(spec)
        assert result is True
        assert registry.get_provider("custom") is spec

    def test_get_provider_stats(self):
        """Test getting provider stats."""
        registry = ProviderRegistry()
        registry._providers["openai"] = ProviderSpec(
            id="openai",
            name="OpenAI",
            api_base="",
            models={"gpt-4o": ModelSpec(id="gpt-4o", name="GPT-4o", provider_id="openai")},
        )
        stats = registry.get_provider_stats()
        assert stats["total_providers"] == 1
        assert stats["total_models"] == 1

    def test_export_catalog(self, tmp_path):
        """Test exporting catalog."""
        registry = ProviderRegistry()
        registry._providers["openai"] = ProviderSpec(id="openai", name="OpenAI", api_base="")
        export_path = tmp_path / "catalog.json"
        result = registry.export_catalog(str(export_path))
        assert result is True
        assert export_path.exists()


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_provider_registry_singleton(self):
        """Test global instance is singleton."""
        reset_provider_registry()
        r1 = get_provider_registry()
        r2 = get_provider_registry()
        assert r1 is r2

    def test_reset_provider_registry(self):
        """Test resetting global instance."""
        r1 = get_provider_registry()
        reset_provider_registry()
        r2 = get_provider_registry()
        assert r1 is not r2
