"""Tests for plugin functionality."""

import asyncio
import tempfile

import pytest

from nanocode.plugin import (
    Plugin,
    PluginContext,
    PluginHookType,
    PluginMetadata,
    get_plugin_manager,
    list_plugins,
    register_plugin,
    unregister_plugin,
)


class TestPlugin(Plugin):
    """Test plugin implementation."""

    @property
    def name(self) -> str:
        return "test-plugin"

    def get_hooks(self):
        return {
            "on_startup": self._on_startup,
            "on_event": self._on_event,
        }

    async def _on_startup(self):
        return "startup called"

    async def _on_event(self, event):
        return f"event: {event}"


class ToolPlugin(Plugin):
    """Plugin that provides tools."""

    @property
    def name(self) -> str:
        return "tool-plugin"

    def get_hooks(self):
        return {
            "tool": self._get_tools,
        }

    def _get_tools(self):
        return [{"name": "test_tool", "description": "A test tool"}]


class AuthPlugin(Plugin):
    """Plugin that provides authentication."""

    @property
    def name(self) -> str:
        return "auth-plugin"

    def get_hooks(self):
        return {
            "auth": self._authenticate,
        }

    async def _authenticate(self, credentials):
        return {"token": "test-token", "authenticated": True}


@pytest.fixture
def plugin_manager():
    """Get and reset plugin manager."""
    manager = get_plugin_manager()
    manager.reset()
    return manager


def test_plugin_metadata():
    """Test plugin metadata."""
    metadata = PluginMetadata(
        name="test",
        version="1.0.0",
        description="A test plugin",
    )
    assert metadata.name == "test"
    assert metadata.version == "1.0.0"


def test_plugin_manager_singleton():
    """Test that plugin manager is a singleton."""
    m1 = get_plugin_manager()
    m2 = get_plugin_manager()
    assert m1 is m2


def test_register_plugin(plugin_manager):
    """Test registering a plugin."""
    plugin = TestPlugin()
    name = plugin_manager.register_plugin(plugin)
    assert name == "test-plugin"
    assert "test-plugin" in plugin_manager.list_plugins()


def test_register_duplicate_plugin(plugin_manager):
    """Test registering duplicate plugin raises error."""
    plugin = TestPlugin()
    plugin_manager.register_plugin(plugin)

    with pytest.raises(ValueError, match="already registered"):
        plugin_manager.register_plugin(plugin)


def test_unregister_plugin(plugin_manager):
    """Test unregistering a plugin."""
    plugin = TestPlugin()
    plugin_manager.register_plugin(plugin)
    assert "test-plugin" in plugin_manager.list_plugins()

    plugin_manager.unregister_plugin("test-plugin")
    assert "test-plugin" not in plugin_manager.list_plugins()


def test_get_plugin(plugin_manager):
    """Test getting a plugin by name."""
    plugin = TestPlugin()
    plugin_manager.register_plugin(plugin)

    retrieved = plugin_manager.get_plugin("test-plugin")
    assert retrieved is not None
    assert retrieved.name == "test-plugin"


def test_get_nonexistent_plugin(plugin_manager):
    """Test getting nonexistent plugin returns None."""
    assert plugin_manager.get_plugin("nonexistent") is None


def test_plugin_hooks(plugin_manager):
    """Test plugin hooks are registered."""
    plugin = TestPlugin()
    plugin_manager.register_plugin(plugin)

    hooks = plugin_manager.get_hooks(PluginHookType.ON_STARTUP)
    assert len(hooks) > 0


def test_trigger_hook(plugin_manager):
    """Test triggering a hook."""
    plugin = TestPlugin()
    plugin_manager.register_plugin(plugin)

    results = asyncio.run(plugin_manager.trigger_hook(PluginHookType.ON_STARTUP))
    assert len(results) > 0


def test_trigger_hook_with_args(plugin_manager):
    """Test triggering a hook with arguments."""

    class EventPlugin(Plugin):
        @property
        def name(self) -> str:
            return "event-plugin"

        async def on_event(self, event):
            return f"event: {event}"

        def get_hooks(self):
            return {"event": self.on_event}

    plugin = EventPlugin()
    plugin_manager.register_plugin(plugin)

    results = asyncio.run(
        plugin_manager.trigger_hook(PluginHookType.EVENT, {"type": "test"})
    )
    assert len(results) > 0


def test_plugin_context(plugin_manager):
    """Test plugin context."""
    context = PluginContext(
        directory="/test/dir",
        worktree="/test/worktree",
    )
    plugin_manager.set_context(context)

    retrieved = plugin_manager.get_context()
    assert retrieved.directory == "/test/dir"
    assert retrieved.worktree == "/test/worktree"


def test_list_plugins_empty(plugin_manager):
    """Test listing plugins when none registered."""
    assert plugin_manager.list_plugins() == []


def test_multiple_plugins(plugin_manager):
    """Test registering multiple plugins."""
    plugin1 = TestPlugin()
    plugin2 = ToolPlugin()
    plugin3 = AuthPlugin()

    plugin_manager.register_plugin(plugin1)
    plugin_manager.register_plugin(plugin2)
    plugin_manager.register_plugin(plugin3)

    assert len(plugin_manager.list_plugins()) == 3


def test_convenience_functions():
    """Test convenience functions."""
    manager = get_plugin_manager()
    manager.reset()

    plugin = TestPlugin()
    register_plugin(plugin)

    assert "test-plugin" in list_plugins()

    unregister_plugin("test-plugin")
    assert "test-plugin" not in list_plugins()


@pytest.mark.asyncio
async def test_plugin_on_load():
    """Test plugin on_load lifecycle."""

    class LoadPlugin(Plugin):
        @property
        def name(self) -> str:
            return "load-test"

        async def on_load(self, context):
            return "loaded"

    manager = get_plugin_manager()
    manager.reset()

    plugin = LoadPlugin()
    manager.register_plugin(plugin)

    context = PluginContext(directory="/test", worktree="/test")
    result = await plugin.on_load(context)
    assert result == "loaded"


@pytest.mark.asyncio
async def test_plugin_initialize():
    """Test initializing all plugins."""
    manager = get_plugin_manager()
    manager.reset()

    plugin = TestPlugin()
    manager.register_plugin(plugin)

    await manager.initialize_plugins()


@pytest.mark.asyncio
async def test_plugin_shutdown():
    """Test shutting down all plugins."""
    manager = get_plugin_manager()
    manager.reset()

    plugin = TestPlugin()
    manager.register_plugin(plugin)

    await manager.shutdown_plugins()


def test_plugin_disabled():
    """Test disabling plugins."""
    manager = get_plugin_manager()
    manager.reset()

    manager.enabled = False

    plugin = TestPlugin()
    manager.register_plugin(plugin)

    results = asyncio.run(manager.trigger_hook(PluginHookType.ON_STARTUP))
    assert results == []


def test_load_plugins_from_directory():
    """Test loading plugins from directory."""
    manager = get_plugin_manager()
    manager.reset()

    with tempfile.TemporaryDirectory() as tmpdir:
        manager.set_context(PluginContext(directory=tmpdir, worktree=tmpdir))
        asyncio.run(manager.load_plugins_from_directory(tmpdir))
