"""Plugin system for extensible functionality."""

import os
import asyncio
import importlib.util
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod


@dataclass
class PluginMetadata:
    """Metadata about a plugin."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    homepage: str = ""


class PluginHookType(Enum):
    """Types of plugin hooks."""

    AUTH = "auth"
    EVENT = "event"
    TOOL = "tool"
    BEFORE_EXECUTE = "before_execute"
    AFTER_EXECUTE = "after_execute"
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"
    PRE_PROMPT = "pre_prompt"
    POST_RESPONSE = "post_response"


@dataclass
class PluginContext:
    """Context passed to plugins."""

    directory: str
    worktree: str
    config: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class Plugin(ABC):
    """Base class for plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the plugin name."""
        pass

    @property
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(name=self.name)

    async def on_load(self, context: PluginContext):
        """Called when plugin is loaded."""
        pass

    async def on_unload(self):
        """Called when plugin is unloaded."""
        pass

    async def on_startup(self):
        """Called on application startup."""
        pass

    async def on_shutdown(self):
        """Called on application shutdown."""
        pass

    def get_hooks(self) -> dict[str, Callable]:
        """Return hooks provided by this plugin."""
        return {}


@runtime_checkable
class ToolPlugin(Protocol):
    """Protocol for tool plugins."""

    def get_tools(self) -> list[dict]: ...


@runtime_checkable
class AuthPlugin(Protocol):
    """Protocol for authentication plugins."""

    async def authenticate(self, credentials: dict) -> dict: ...


@runtime_checkable
class EventPlugin(Protocol):
    """Protocol for event handling plugins."""

    async def on_event(self, event: dict): ...


class PluginManager:
    """Manages plugin loading and lifecycle."""

    _instance: Optional["PluginManager"] = None

    def __new__(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._plugins: dict[str, Plugin] = {}
        self._hooks: dict[PluginHookType, list[tuple[str, Callable]]] = {
            hook_type: [] for hook_type in PluginHookType
        }
        self._context = PluginContext(
            directory=os.getcwd(),
            worktree=os.getcwd(),
        )
        self._enabled = True
        self._initialized = True

    def reset(self):
        """Reset the plugin manager."""
        self._plugins.clear()
        self._hooks = {hook_type: [] for hook_type in PluginHookType}

    @property
    def enabled(self) -> bool:
        """Check if plugins are enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Set plugin enabled state."""
        self._enabled = value

    def set_context(self, context: PluginContext):
        """Set the plugin context."""
        self._context = context

    def get_context(self) -> PluginContext:
        """Get the plugin context."""
        return self._context

    def register_plugin(self, plugin: Plugin) -> str:
        """Register a plugin."""
        name = plugin.name

        if name in self._plugins:
            raise ValueError(f"Plugin {name} is already registered")

        self._plugins[name] = plugin

        hooks = plugin.get_hooks()
        for hook_name, hook_fn in hooks.items():
            try:
                hook_type = PluginHookType(hook_name)
                self._hooks[hook_type].append((name, hook_fn))
            except ValueError:
                pass

        return name

    def unregister_plugin(self, name: str):
        """Unregister a plugin."""
        if name not in self._plugins:
            return

        plugin = self._plugins.pop(name)

        for hook_type in PluginHookType:
            self._hooks[hook_type] = [(n, fn) for n, fn in self._hooks[hook_type] if n != name]

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[str]:
        """List all registered plugins."""
        return list(self._plugins.keys())

    def get_hooks(self, hook_type: PluginHookType) -> list[tuple[str, Callable]]:
        """Get hooks of a specific type."""
        return self._hooks.get(hook_type, [])

    async def trigger_hook(self, hook_type: PluginHookType, *args, **kwargs) -> list[Any]:
        """Trigger all hooks of a specific type."""
        if not self._enabled:
            return []

        results = []
        for name, hook_fn in self._hooks.get(hook_type, []):
            try:
                result = hook_fn(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                results.append(result)
            except Exception:
                pass

        return results

    async def load_plugin_from_module(self, module_path: str) -> str:
        """Load a plugin from a Python module."""
        spec = importlib.util.spec_from_file_location("plugin_module", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin from {module_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, "plugin"):
            plugin = module.plugin
            if isinstance(plugin, Plugin):
                return self.register_plugin(plugin)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Plugin) and attr != Plugin:
                plugin = attr()
                return self.register_plugin(plugin)

        raise ValueError(f"No plugin found in {module_path}")

    async def load_plugin_from_package(self, package_name: str) -> str:
        """Load a plugin from an installed package."""
        try:
            module = importlib.import_module(package_name)
        except ImportError:
            raise ImportError(f"Cannot import package {package_name}")

        if hasattr(module, "plugin"):
            plugin = module.plugin
            if isinstance(plugin, Plugin):
                return self.register_plugin(plugin)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Plugin) and attr != Plugin:
                plugin = attr()
                return self.register_plugin(plugin)

        raise ValueError(f"No plugin found in package {package_name}")

    async def load_plugins_from_directory(self, directory: str):
        """Load all plugins from a directory."""
        plugins_dir = Path(directory)

        if not plugins_dir.exists():
            return

        for plugin_file in plugins_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            try:
                await self.load_plugin_from_module(str(plugin_file))
            except Exception:
                pass

    async def initialize_plugins(self):
        """Initialize all loaded plugins."""
        for name, plugin in self._plugins.items():
            try:
                await plugin.on_load(self._context)
            except Exception:
                pass

        await self.trigger_hook(PluginHookType.ON_STARTUP)

    async def shutdown_plugins(self):
        """Shutdown all plugins."""
        await self.trigger_hook(PluginHookType.ON_SHUTDOWN)

        for name, plugin in self._plugins.items():
            try:
                await plugin.on_unload()
            except Exception:
                pass


def get_plugin_manager() -> PluginManager:
    """Get the global plugin manager."""
    return PluginManager()


def register_plugin(plugin: Plugin) -> str:
    """Register a plugin with the global manager."""
    return get_plugin_manager().register_plugin(plugin)


def unregister_plugin(name: str):
    """Unregister a plugin from the global manager."""
    get_plugin_manager().unregister_plugin(name)


def list_plugins() -> list[str]:
    """List all registered plugins."""
    return get_plugin_manager().list_plugins()


async def trigger_hook(hook_type: PluginHookType, *args, **kwargs) -> list[Any]:
    """Trigger a hook on all plugins."""
    return await get_plugin_manager().trigger_hook(hook_type, *args, **kwargs)
