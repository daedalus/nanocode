"""Tests for model registry and provider router."""

import pytest
import tempfile
import os
import json

from agent.llm.registry import ModelRegistry, ModelInfo, ProviderInfo
from agent.llm.router import ProviderRouter, ParsedModelID, ProviderConfig


class TestModelRegistry:
    """Test model registry."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create temp cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_registry_data(self):
        """Mock models.dev data."""
        return {
            "openai": {
                "name": "OpenAI",
                "api": "https://api.openai.com/v1",
                "models": {
                    "gpt-4o": {
                        "id": "openai/gpt-4o",
                        "name": "GPT-4o",
                        "cost": {"input": 0.005, "output": 0.015},
                        "limit": {"context": 128000},
                        "modalities": {"input": ["text"], "output": ["text"]},
                    },
                    "gpt-3.5-turbo": {
                        "id": "openai/gpt-3.5-turbo",
                        "name": "GPT-3.5 Turbo",
                        "cost": {"input": 0.0005, "output": 0.0015},
                        "limit": {"context": 16385},
                        "modalities": {"input": ["text"], "output": ["text"]},
                    },
                },
            },
            "anthropic": {
                "name": "Anthropic",
                "api": "https://api.anthropic.com/v1",
                "models": {
                    "claude-3-5-sonnet-20241022": {
                        "id": "anthropic/claude-3-5-sonnet-20241022",
                        "name": "Claude 3.5 Sonnet",
                        "cost": {"input": 0.003, "output": 0.015},
                        "limit": {"context": 200000},
                        "tool_call": True,
                    },
                },
            },
            "free-provider": {
                "name": "Free Provider",
                "api": "https://api.free-provider.com/v1",
                "models": {
                    "free-model": {
                        "id": "free-provider/free-model",
                        "name": "Free Model",
                        "cost": {"input": 0, "output": 0},
                        "limit": {"context": 8192},
                    },
                },
            },
        }

    def test_registry_initialization(self, temp_cache_dir):
        """Test registry initialization."""
        registry = ModelRegistry(cache_dir=temp_cache_dir)
        
        assert registry.cache_dir == temp_cache_dir
        assert registry.cache_file.endswith("models_registry.json")

    def test_parse_models(self, temp_cache_dir, mock_registry_data):
        """Test parsing models from data."""
        registry = ModelRegistry(cache_dir=temp_cache_dir)
        registry._parse_models(mock_registry_data)
        
        providers = registry.list_providers()
        assert "openai" in providers
        assert "anthropic" in providers
        assert "free-provider" in providers

    def test_get_provider(self, temp_cache_dir, mock_registry_data):
        """Test getting provider info."""
        registry = ModelRegistry(cache_dir=temp_cache_dir)
        registry._parse_models(mock_registry_data)
        
        provider = registry.get_provider("openai")
        
        assert provider is not None
        assert provider.name == "OpenAI"
        assert provider.api_base == "https://api.openai.com/v1"

    def test_get_model(self, temp_cache_dir, mock_registry_data):
        """Test getting model info."""
        registry = ModelRegistry(cache_dir=temp_cache_dir)
        registry._parse_models(mock_registry_data)
        
        model = registry.get_model("openai", "gpt-4o")
        
        assert model is not None
        assert model.name == "GPT-4o"
        assert model.input_cost == 0.005
        assert model.output_cost == 0.015
        assert model.context_limit == 128000
        assert model.is_free is False

    def test_get_model_by_full_id(self, temp_cache_dir, mock_registry_data):
        """Test getting model by full ID."""
        registry = ModelRegistry(cache_dir=temp_cache_dir)
        registry._parse_models(mock_registry_data)
        
        model = registry.get_model_by_full_id("openai/gpt-4o")
        
        assert model is not None
        assert model.id == "openai/gpt-4o"

    def test_free_models(self, temp_cache_dir, mock_registry_data):
        """Test getting free models."""
        registry = ModelRegistry(cache_dir=temp_cache_dir)
        registry._parse_models(mock_registry_data)
        
        free_models = registry.get_free_models()
        
        assert len(free_models) == 1
        assert free_models[0].provider_id == "free-provider"

    def test_save_and_load_cache(self, temp_cache_dir, mock_registry_data):
        """Test cache save and load."""
        registry1 = ModelRegistry(cache_dir=temp_cache_dir)
        registry1._parse_models(mock_registry_data)
        registry1._save_to_cache()
        
        registry2 = ModelRegistry(cache_dir=temp_cache_dir)
        cached = registry2._load_from_cache()
        
        assert cached is not None
        assert "openai" in cached


class TestProviderRouter:
    """Test provider router."""

    @pytest.fixture
    def router(self):
        """Create router instance."""
        return ProviderRouter()

    def test_parse_model_id_with_provider(self, router):
        """Test parsing model ID with explicit provider."""
        parsed = router.parse_model_id("openai/gpt-4o")
        
        assert parsed.provider == "openai"
        assert parsed.model == "gpt-4o"

    def test_parse_model_id_without_provider(self, router):
        """Test parsing model ID without provider."""
        parsed = router.parse_model_id("gpt-4o")
        
        assert parsed.provider == "openai"
        assert parsed.model == "gpt-4o"

    def test_infer_provider_claude(self, router):
        """Test inferring anthropic provider."""
        parsed = router.parse_model_id("claude-3-5-sonnet")
        
        assert parsed.provider == "anthropic"

    def test_infer_provider_gemini(self, router):
        """Test inferring google provider."""
        parsed = router.parse_model_id("gemini-pro")
        
        assert parsed.provider == "google"

    def test_infer_provider_llama(self, router):
        """Test inferring ollama provider."""
        parsed = router.parse_model_id("llama-3")
        
        assert parsed.provider == "ollama"

    def test_add_explicit_provider(self, router):
        """Test adding explicit provider config."""
        router.add_explicit_provider("custom", {
            "base_url": "https://custom.api.com/v1",
            "api_key": "custom-key",
        })
        
        config = router.get_provider_config("custom/model")
        
        assert config.provider == "custom"
        assert config.base_url == "https://custom.api.com/v1"
        assert config.api_key == "custom-key"

    def test_get_provider_config_defaults(self, router):
        """Test getting provider config with defaults."""
        config = router.get_provider_config("gpt-4o")
        
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert "api.openai.com" in config.base_url

    def test_get_provider_config_openai(self, router):
        """Test getting OpenAI provider config."""
        config = router.get_provider_config("openai/gpt-4o")
        
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert "api.openai.com" in config.base_url

    def test_get_provider_config_anthropic(self, router):
        """Test getting Anthropic provider config."""
        config = router.get_provider_config("anthropic/claude-3-5-sonnet")
        
        assert config.provider == "anthropic"
        assert config.model == "claude-3-5-sonnet"
        assert "api.anthropic.com" in config.base_url

    def test_get_provider_config_ollama(self, router):
        """Test getting Ollama provider config."""
        config = router.get_provider_config("ollama/llama3")
        
        assert config.provider == "ollama"
        assert config.model == "llama3"
        assert "localhost:11434" in config.base_url

    def test_opencode_provider_special_handling(self, router):
        """Test special handling for opencode provider."""
        config = router.get_provider_config("opencode/gpt-5-nano")
        
        assert config.provider == "opencode"
        assert config.base_url == "https://opencode.ai/zen/v1"

    def test_is_provider_available_with_key(self, router):
        """Test availability check with API key."""
        os.environ["OPENAI_API_KEY"] = "test-key"
        
        available = router.is_provider_available("gpt-4o")
        
        assert available is True
        
        del os.environ["OPENAI_API_KEY"]

    def test_is_provider_available_local(self, router):
        """Test availability check for local providers."""
        available = router.is_provider_available("ollama/llama3")
        
        assert available is True

    def test_is_provider_available_public(self, router):
        """Test availability check with public key."""
        router.add_explicit_provider("opencode", {"api_key": "public"})
        
        available = router.is_provider_available("opencode/model")
        
        assert available is True
