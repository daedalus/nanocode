"""Model registry from models.dev - provides access to 2000+ LLM models."""

import os
import json
import time
from typing import Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ModelInfo:
    """Information about a model."""
    id: str
    name: str
    provider_id: str
    api_endpoint: str
    context_limit: int
    input_cost: float = 0
    output_cost: float = 0
    supports_tools: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True
    is_free: bool = False


@dataclass
class ProviderInfo:
    """Information about a provider."""
    id: str
    name: str
    api_base: str
    models: dict[str, ModelInfo] = field(default_factory=dict)
    env_vars: list[str] = field(default_factory=list)
    auth_type: str = "api_key"


class ModelRegistry:
    """Registry of models from models.dev.
    
    Fetches model data from models.dev API and caches locally.
    Supports 75+ providers and 2000+ models.
    """
    
    CACHE_DIR = ".agent/cache"
    CACHE_FILE = "models_registry.json"
    REFRESH_INTERVAL = 60 * 60 * 1000  # 1 hour
    
    def __init__(self, cache_dir: str = None):
        self.cache_dir = cache_dir or self.CACHE_DIR
        self.cache_file = os.path.join(self.cache_dir, self.CACHE_FILE)
        self._providers: dict[str, ProviderInfo] = {}
        self._last_refresh = 0
        self._ensure_cache_dir()
    
    def _ensure_cache_dir(self):
        """Ensure cache directory exists."""
        os.makedirs(self.cache_dir, exist_ok=True)
    
    async def load(self, force_refresh: bool = False):
        """Load model registry from cache or fetch from models.dev."""
        current_time = int(time.time() * 1000)
        
        if not force_refresh and self._providers:
            return
        
        if not force_refresh:
            cached = self._load_from_cache()
            if cached:
                self._providers = cached
                return
        
        await self.refresh()
    
    def _load_from_cache(self) -> Optional[dict[str, ProviderInfo]]:
        """Load from local cache."""
        if not os.path.exists(self.cache_file):
            return None
        
        try:
            with open(self.cache_file) as f:
                data = json.load(f)
            
            providers = {}
            for pid, pdata in data.items():
                models = {}
                for mid, mdata in pdata.get("models", {}).items():
                    models[mid] = ModelInfo(
                        id=mdata["id"],
                        name=mdata["name"],
                        provider_id=mdata["provider_id"],
                        api_endpoint=mdata["api_endpoint"],
                        context_limit=mdata.get("context_limit", 128000),
                        input_cost=mdata.get("input_cost", 0),
                        output_cost=mdata.get("output_cost", 0),
                        supports_tools=mdata.get("supports_tools", True),
                        supports_vision=mdata.get("supports_vision", False),
                        supports_streaming=mdata.get("supports_streaming", True),
                        is_free=mdata.get("is_free", False),
                    )
                
                providers[pid] = ProviderInfo(
                    id=pdata["id"],
                    name=pdata["name"],
                    api_base=pdata["api_base"],
                    models=models,
                    env_vars=pdata.get("env_vars", []),
                    auth_type=pdata.get("auth_type", "api_key"),
                )
            
            return providers
        except Exception:
            return None
    
    def _save_to_cache(self):
        """Save to local cache."""
        data = {}
        for pid, provider in self._providers.items():
            data[pid] = {
                "id": provider.id,
                "name": provider.name,
                "api_base": provider.api_base,
                "env_vars": provider.env_vars,
                "auth_type": provider.auth_type,
                "models": {
                    mid: {
                        "id": m.id,
                        "name": m.name,
                        "provider_id": m.provider_id,
                        "api_endpoint": m.api_endpoint,
                        "context_limit": m.context_limit,
                        "input_cost": m.input_cost,
                        "output_cost": m.output_cost,
                        "supports_tools": m.supports_tools,
                        "supports_vision": m.supports_vision,
                        "supports_streaming": m.supports_streaming,
                        "is_free": m.is_free,
                    }
                    for mid, m in provider.models.items()
                }
            }
        
        with open(self.cache_file, "w") as f:
            json.dump(data, f, indent=2)
    
    async def refresh(self):
        """Fetch latest model data from models.dev."""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://models.dev/api.json",
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
            
            self._parse_models(data)
            self._save_to_cache()
        except Exception as e:
            print(f"Failed to fetch models.dev: {e}")
            cached = self._load_from_cache()
            if cached:
                self._providers = cached
    
    def _parse_models(self, data: dict):
        """Parse models from models.dev format."""
        self._providers = {}
        
        for provider_id, provider_data in data.items():
            models = {}
            api_base = provider_data.get("api", "")
            
            for model_id, model_data in provider_data.get("models", {}).items():
                cost = model_data.get("cost", {})
                limit = model_data.get("limit", {})
                
                models[model_id] = ModelInfo(
                    id=model_data.get("id", model_id),
                    name=model_data.get("name", model_id),
                    provider_id=provider_id,
                    api_endpoint=api_base,
                    context_limit=limit.get("context", 128000),
                    input_cost=cost.get("input", 0),
                    output_cost=cost.get("output", 0),
                    supports_tools=model_data.get("tool_call", False),
                    supports_vision="image" in str(model_data.get("modalities", {}).get("input", [])),
                    supports_streaming=True,
                    is_free=cost.get("input", 0) == 0 and cost.get("output", 0) == 0,
                )
            
            self._providers[provider_id] = ProviderInfo(
                id=provider_id,
                name=provider_data.get("name", provider_id),
                api_base=api_base,
                models=models,
                env_vars=provider_data.get("env", []),
                auth_type="api_key",
            )
    
    def get_provider(self, provider_id: str) -> Optional[ProviderInfo]:
        """Get provider by ID."""
        return self._providers.get(provider_id)
    
    def get_model(self, provider_id: str, model_id: str) -> Optional[ModelInfo]:
        """Get model by provider and model ID."""
        provider = self._providers.get(provider_id)
        if not provider:
            return None
        return provider.models.get(model_id)
    
    def get_model_by_full_id(self, full_id: str) -> Optional[ModelInfo]:
        """Get model by full ID (e.g., 'openai/gpt-4o')."""
        if "/" not in full_id:
            return None
        
        provider_id, model_id = full_id.split("/", 1)
        return self.get_model(provider_id, model_id)
    
    def list_providers(self) -> list[str]:
        """List all available provider IDs."""
        return list(self._providers.keys())
    
    def list_models(self, provider_id: str) -> list[str]:
        """List all model IDs for a provider."""
        provider = self._providers.get(provider_id)
        if not provider:
            return []
        return list(provider.models.keys())
    
    def search_models(self, query: str, limit: int = 10) -> list[ModelInfo]:
        """Search models by name."""
        results = []
        query_lower = query.lower()
        
        for provider in self._providers.values():
            for model in provider.models.values():
                if query_lower in model.name.lower() or query_lower in model.id.lower():
                    results.append(model)
                    if len(results) >= limit:
                        return results
        
        return results
    
    def get_free_models(self) -> list[ModelInfo]:
        """Get all free models."""
        results = []
        for provider in self._providers.values():
            for model in provider.models.values():
                if model.is_free:
                    results.append(model)
        return results


# Global registry instance
_registry: Optional[ModelRegistry] = None


def get_registry() -> ModelRegistry:
    """Get the global model registry instance."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
