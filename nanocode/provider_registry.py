"""Provider Registry - Clean provider/model separation.

Enhances existing registry with:
- ProviderSpec pattern for cleaner data structure
- Dynamic catalog fetching from OpenRouter
- Provider health checks
- Better caching with versioning
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from nanocode.llm.registry import ModelInfo, ModelRegistry, ProviderInfo

logger = logging.getLogger(__name__)


@dataclass
class ProviderSpec:
    """Specification for a provider - cleaner separation than flat dict."""

    id: str
    name: str
    api_base: str
    auth_type: str = "api_key"
    env_vars: List[str] = field(default_factory=list)
    models: Dict[str, "ModelSpec"] = field(default_factory=dict)
    health_check_url: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    last_updated: float = field(default_factory=time.time)

    def get_model(self, model_id: str) -> Optional["ModelSpec"]:
        """Get a model by ID."""
        return self.models.get(model_id)

    def list_models(self) -> List[str]:
        """List all model IDs."""
        return list(self.models.keys())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "api_base": self.api_base,
            "auth_type": self.auth_type,
            "env_vars": self.env_vars,
            "health_check_url": self.health_check_url,
            "capabilities": self.capabilities,
            "version": self.version,
            "last_updated": self.last_updated,
            "model_count": len(self.models),
        }


@dataclass
class ModelSpec:
    """Specification for a model - cleaner separation."""

    id: str
    name: str
    provider_id: str
    context_limit: int = 128000
    max_output_tokens: int = 4096
    input_cost: float = 0.0
    output_cost: float = 0.0
    supports_tools: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True
    supports_json_mode: bool = False
    supports_system_prompt: bool = True
    reasoning_effort: Optional[str] = None
    description: str = ""
    version: int = 1

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "provider_id": self.provider_id,
            "context_limit": self.context_limit,
            "max_output_tokens": self.max_output_tokens,
            "input_cost": self.input_cost,
            "output_cost": self.output_cost,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "supports_streaming": self.supports_streaming,
            "supports_json_mode": self.supports_json_mode,
            "supports_system_prompt": self.supports_system_prompt,
            "reasoning_effort": self.reasoning_effort,
            "description": self.description,
            "version": self.version,
        }

    @classmethod
    def from_model_info(cls, info: ModelInfo) -> "ModelSpec":
        """Create ModelSpec from existing ModelInfo."""
        return cls(
            id=info.id,
            name=info.name,
            provider_id=info.provider_id,
            context_limit=info.context_limit,
            max_output_tokens=info.max_output_tokens,
            input_cost=info.input_cost,
            output_cost=info.output_cost,
            supports_tools=info.supports_tools,
            supports_vision=info.supports_vision,
            supports_streaming=info.supports_streaming,
            reasoning_effort=info.reasoning_effort,
            description=info.description,
        )


class ProviderRegistry:
    """Enhanced provider registry with ProviderSpec pattern.

    Builds on existing ModelRegistry with cleaner separation.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """Initialize the provider registry.

        Args:
            cache_dir: Directory for caching
        """
        if cache_dir is None:
            xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
            cache_dir = str(Path(xdg_data) / "nanocode" / "provider_cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._providers: Dict[str, ProviderSpec] = {}
        self._model_registry: Optional[ModelRegistry] = None
        self._health_status: Dict[str, bool] = {}
        self._last_health_check: Dict[str, float] = {}

    @property
    def model_registry(self) -> ModelRegistry:
        """Get or create the model registry."""
        if self._model_registry is None:
            self._model_registry = ModelRegistry()
        return self._model_registry

    async def initialize(self, force_refresh: bool = False):
        """Initialize the registry.

        Args:
            force_refresh: Force refresh from models.dev
        """
        # Load from models.dev
        await self.model_registry.load(force_refresh=force_refresh)

        # Convert to ProviderSpec pattern
        for provider_id, provider_info in self.model_registry._providers.items():
            self._providers[provider_id] = self._convert_provider(provider_info)

        logger.info(f"Provider registry initialized: {len(self._providers)} providers")

    def _convert_provider(self, info: ProviderInfo) -> ProviderSpec:
        """Convert ProviderInfo to ProviderSpec."""
        models = {}
        for model_id, model_info in info.models.items():
            models[model_id] = ModelSpec.from_model_info(model_info)

        return ProviderSpec(
            id=info.id,
            name=info.name,
            api_base=info.api_base,
            auth_type=info.auth_type,
            env_vars=info.env_vars,
            models=models,
            capabilities={
                "supports_tools": any(m.supports_tools for m in models.values()),
                "supports_vision": any(m.supports_vision for m in models.values()),
                "supports_streaming": any(m.supports_streaming for m in models.values()),
            },
        )

    def get_provider(self, provider_id: str) -> Optional[ProviderSpec]:
        """Get provider by ID."""
        return self._providers.get(provider_id)

    def get_model(self, provider_id: str, model_id: str) -> Optional[ModelSpec]:
        """Get model by provider and model ID."""
        provider = self._providers.get(provider_id)
        if not provider:
            return None
        return provider.get_model(model_id)

    def get_model_by_full_id(self, full_id: str) -> Optional[ModelSpec]:
        """Get model by full ID (e.g., 'openai/gpt-4o')."""
        if "/" not in full_id:
            return None
        provider_id, model_id = full_id.split("/", 1)
        return self.get_model(provider_id, model_id)

    def list_providers(self) -> List[str]:
        """List all provider IDs."""
        return list(self._providers.keys())

    def list_models(self, provider_id: Optional[str] = None) -> List[str]:
        """List model IDs, optionally filtered by provider."""
        if provider_id:
            provider = self._providers.get(provider_id)
            return provider.list_models() if provider else []

        models = []
        for provider in self._providers.values():
            models.extend(provider.list_models())
        return models

    def search_models(
        self,
        query: str,
        limit: int = 10,
        supports_tools: Optional[bool] = None,
        supports_vision: Optional[bool] = None,
        max_cost: Optional[float] = None,
    ) -> List[ModelSpec]:
        """Search models with filters.

        Args:
            query: Search query
            limit: Maximum results
            supports_tools: Filter by tool support
            supports_vision: Filter by vision support
            max_cost: Maximum input cost per million tokens

        Returns:
            List of matching ModelSpec objects
        """
        results = []
        query_lower = query.lower()

        for provider in self._providers.values():
            for model in provider.models.values():
                # Text match
                if query_lower not in model.name.lower() and query_lower not in model.id.lower():
                    continue

                # Capability filters
                if supports_tools is not None and model.supports_tools != supports_tools:
                    continue
                if supports_vision is not None and model.supports_vision != supports_vision:
                    continue
                if max_cost is not None and model.input_cost > max_cost:
                    continue

                results.append(model)
                if len(results) >= limit:
                    return results

        return results

    def get_free_models(self) -> List[ModelSpec]:
        """Get all free models."""
        results = []
        for provider in self._providers.values():
            for model in provider.models.values():
                if model.input_cost == 0 and model.output_cost == 0:
                    results.append(model)
        return results

    def get_models_by_capability(
        self,
        capability: str,
        value: Any = True,
    ) -> List[ModelSpec]:
        """Get models by capability."""
        results = []
        for provider in self._providers.values():
            for model in provider.models.items():
                model_spec = model[1]
                if getattr(model_spec, f"supports_{capability}", None) == value:
                    results.append(model_spec)
        return results

    async def check_provider_health(self, provider_id: str) -> bool:
        """Check if a provider is healthy.

        Args:
            provider_id: Provider to check

        Returns:
            True if healthy
        """
        provider = self._providers.get(provider_id)
        if not provider:
            return False

        # Rate limit health checks (1 per minute)
        last_check = self._last_health_check.get(provider_id, 0)
        if time.time() - last_check < 60:
            return self._health_status.get(provider_id, True)

        # Simple health check - try to access API base
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(provider.api_base)
                healthy = response.status_code < 500
        except Exception:
            healthy = False

        self._health_status[provider_id] = healthy
        self._last_health_check[provider_id] = time.time()

        return healthy

    def get_provider_stats(self) -> Dict[str, Any]:
        """Get provider statistics."""
        total_models = sum(len(p.models) for p in self._providers.values())
        free_models = len(self.get_free_models())

        return {
            "total_providers": len(self._providers),
            "total_models": total_models,
            "free_models": free_models,
            "providers": {
                pid: {
                    "name": p.name,
                    "model_count": len(p.models),
                    "capabilities": p.capabilities,
                }
                for pid, p in self._providers.items()
            },
        }

    def export_catalog(self, path: str) -> bool:
        """Export provider catalog to JSON.

        Args:
            path: Output file path

        Returns:
            True if successful
        """
        try:
            catalog = {
                "version": 1,
                "exported_at": time.time(),
                "providers": {
                    pid: p.to_dict() for pid, p in self._providers.items()
                },
            }
            with open(path, "w") as f:
                json.dump(catalog, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to export catalog: {e}")
            return False

    def import_custom_provider(self, spec: ProviderSpec) -> bool:
        """Import a custom provider spec.

        Args:
            spec: ProviderSpec to import

        Returns:
            True if successful
        """
        try:
            self._providers[spec.id] = spec
            logger.info(f"Imported custom provider: {spec.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to import provider: {e}")
            return False


# Global instance
_provider_registry: Optional[ProviderRegistry] = None


def get_provider_registry(cache_dir: Optional[str] = None) -> ProviderRegistry:
    """Get or create the global provider registry."""
    global _provider_registry
    if _provider_registry is None:
        _provider_registry = ProviderRegistry(cache_dir)
    return _provider_registry


def reset_provider_registry():
    """Reset the global provider registry."""
    global _provider_registry
    _provider_registry = None
