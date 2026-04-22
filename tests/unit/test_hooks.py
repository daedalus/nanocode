"""Tests for hook system."""

import json
import tempfile
from pathlib import Path

import pytest

from nanocode.hooks import (
    CommandHook,
    HookAction,
    HookContext,
    HookEvent,
    HookManager,
    HookResult,
    PythonHook,
    create_security_hook,
)


class TestHookEvent:
    """Test HookEvent enum."""

    def test_hook_events_exist(self):
        """Test all hook events are defined."""
        assert HookEvent.PRE_TOOL_USE.value == "PreToolUse"
        assert HookEvent.POST_TOOL_USE.value == "PostToolUse"
        assert HookEvent.NOTIFICATION.value == "Notification"
        assert HookEvent.STOP.value == "Stop"
        assert HookEvent.SESSION_START.value == "SessionStart"
        assert HookEvent.SESSION_END.value == "SessionEnd"
        assert HookEvent.ERROR.value == "Error"


class TestHookAction:
    """Test HookAction enum."""

    def test_hook_actions_exist(self):
        """Test all hook actions are defined."""
        assert HookAction.ALLOW.value == "allow"
        assert HookAction.DENY.value == "deny"
        assert HookAction.WARN.value == "warn"
        assert HookAction.MODIFY.value == "modify"
        assert HookAction.STOP.value == "stop"


class TestHookContext:
    """Test HookContext dataclass."""

    def test_basic_context(self):
        """Test creating basic context."""
        ctx = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name="read",
            tool_args={"path": "/test/file.txt"},
        )

        assert ctx.event == HookEvent.PRE_TOOL_USE
        assert ctx.tool_name == "read"
        assert ctx.tool_args == {"path": "/test/file.txt"}

    def test_full_context(self):
        """Test creating full context with all fields."""
        ctx = HookContext(
            event=HookEvent.POST_TOOL_USE,
            session_id="test-session",
            agent_name="build",
            tool_name="write",
            tool_args={"path": "/test/file.txt"},
            tool_result="File written successfully",
            tool_success=True,
            message="Test message",
        )

        assert ctx.session_id == "test-session"
        assert ctx.agent_name == "build"
        assert ctx.tool_result == "File written successfully"
        assert ctx.tool_success is True


class TestHookResult:
    """Test HookResult dataclass."""

    def test_allow_result(self):
        """Test allow result."""
        result = HookResult(action=HookAction.ALLOW)

        assert result.action == HookAction.ALLOW

    def test_deny_result(self):
        """Test deny result with message."""
        result = HookResult(
            action=HookAction.DENY,
            message="Tool blocked by security policy",
        )

        assert result.action == HookAction.DENY
        assert result.message == "Tool blocked by security policy"

    def test_modify_result(self):
        """Test modify result with new args."""
        result = HookResult(
            action=HookAction.MODIFY,
            modified_args={"path": "/safe/path.txt"},
        )

        assert result.action == HookAction.MODIFY
        assert result.modified_args == {"path": "/safe/path.txt"}


class TestHookManager:
    """Test HookManager."""

    @pytest.fixture
    def temp_hooks_dir(self):
        """Create temporary hooks directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks_dir = Path(tmpdir) / ".nanocode" / "hooks"
            hooks_dir.mkdir(parents=True)
            yield tmpdir

    def test_empty_manager(self):
        """Test empty hook manager."""
        manager = HookManager()

        assert len(manager.hooks[HookEvent.PRE_TOOL_USE]) == 0

    def test_discover_hooks_empty_dir(self, temp_hooks_dir):
        """Test discovering hooks in empty directory."""
        manager = HookManager(base_dir=temp_hooks_dir)
        hooks = manager.discover_hooks()

        assert len(hooks) == 0

    def test_discover_json_hooks(self, temp_hooks_dir):
        """Test discovering JSON hooks."""
        hooks_file = Path(temp_hooks_dir) / ".nanocode" / "hooks" / "test.json"
        hooks_file.write_text(
            json.dumps(
                [
                    {
                        "name": "test-hook",
                        "event": "PreToolUse",
                        "description": "Test hook",
                        "pattern": "read",
                        "type": "command",
                        "command": "echo 'test'",
                        "action_on_result": "allow",
                    }
                ]
            )
        )

        manager = HookManager(base_dir=temp_hooks_dir)
        hooks = manager.discover_hooks()

        assert len(hooks) == 1
        assert hooks[0].name == "test-hook"
        assert hooks[0].event == HookEvent.PRE_TOOL_USE

    def test_register_hook(self):
        """Test registering a hook."""
        manager = HookManager()
        hook = CommandHook(
            name="test-cmd",
            event=HookEvent.PRE_TOOL_USE,
            command="echo test",
        )

        manager.register_hook(hook)

        assert len(manager.hooks[HookEvent.PRE_TOOL_USE]) == 1

    def test_unregister_hook(self):
        """Test unregistering a hook."""
        manager = HookManager()
        hook = CommandHook(
            name="test-cmd",
            event=HookEvent.PRE_TOOL_USE,
            command="echo test",
        )
        manager.register_hook(hook)

        result = manager.unregister_hook("test-cmd")

        assert result is True
        assert len(manager.hooks[HookEvent.PRE_TOOL_USE]) == 0

    def test_unregister_nonexistent_hook(self):
        """Test unregistering nonexistent hook."""
        manager = HookManager()

        result = manager.unregister_hook("nonexistent")

        assert result is False

    def test_get_hooks_by_event(self):
        """Test getting hooks by event."""
        manager = HookManager()
        hook = CommandHook(
            name="test-cmd",
            event=HookEvent.PRE_TOOL_USE,
            command="echo test",
        )
        manager.register_hook(hook)

        hooks = manager.get_hooks(HookEvent.PRE_TOOL_USE)

        assert len(hooks) == 1
        assert hooks[0].name == "test-cmd"

    def test_get_hooks_by_event_and_tool(self):
        """Test getting hooks filtered by tool name."""
        manager = HookManager()
        hook = CommandHook(
            name="test-cmd",
            event=HookEvent.PRE_TOOL_USE,
            command="echo test",
            pattern="read",
        )
        manager.register_hook(hook)

        matching = manager.get_hooks(HookEvent.PRE_TOOL_USE, "read")
        non_matching = manager.get_hooks(HookEvent.PRE_TOOL_USE, "write")

        assert len(matching) == 1
        assert len(non_matching) == 0


class TestCommandHook:
    """Test CommandHook."""

    @pytest.mark.asyncio
    async def test_command_hook_allow(self):
        """Test command hook that allows."""
        hook = CommandHook(
            name="allow-hook",
            event=HookEvent.PRE_TOOL_USE,
            command="echo 'allowed'",
            action_on_result=HookAction.ALLOW,
        )

        result = await hook.run(HookContext(event=HookEvent.PRE_TOOL_USE))

        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_command_hook_deny(self):
        """Test command hook that denies on nonzero exit."""
        hook = CommandHook(
            name="deny-hook",
            event=HookEvent.PRE_TOOL_USE,
            command="exit 1",
            action_on_result=HookAction.ALLOW,
        )

        result = await hook.run(HookContext(event=HookEvent.PRE_TOOL_USE))

        assert result.action == HookAction.DENY


class TestPythonHook:
    """Test PythonHook."""

    @pytest.mark.asyncio
    async def test_python_hook_with_func(self):
        """Test Python hook with direct function."""
        async def my_hook(ctx: HookContext) -> HookResult:
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="py-hook",
            event=HookEvent.PRE_TOOL_USE,
            func=my_hook,
        )

        result = await hook.run(HookContext(event=HookEvent.PRE_TOOL_USE))

        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_python_hook_modify_args(self):
        """Test Python hook that modifies arguments."""
        async def modify_hook(ctx: HookContext) -> HookResult:
            if ctx.tool_args:
                modified = dict(ctx.tool_args)
                modified["path"] = "/safe/path.txt"
                return HookResult(action=HookAction.MODIFY, modified_args=modified)
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="modify-hook",
            event=HookEvent.PRE_TOOL_USE,
            func=modify_hook,
        )

        ctx = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name="read",
            tool_args={"path": "/dangerous/path.txt"},
        )
        result = await hook.run(ctx)

        assert result.action == HookAction.MODIFY
        assert result.modified_args["path"] == "/safe/path.txt"


class TestHookManagerExecution:
    """Test hook manager execution methods."""

    @pytest.mark.asyncio
    async def test_run_pre_tool_hooks_allows(self):
        """Test pre-tool hooks allow execution."""
        manager = HookManager()

        async def allow_all(ctx: HookContext) -> HookResult:
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="allow-all",
            event=HookEvent.PRE_TOOL_USE,
            func=allow_all,
        )
        manager.register_hook(hook)

        result = await manager.run_pre_tool_hooks(
            tool_name="read",
            tool_args={"path": "/test/file.txt"},
        )

        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_run_pre_tool_hooks_denies(self):
        """Test pre-tool hooks can block execution."""
        manager = HookManager()

        async def block_read(ctx: HookContext) -> HookResult:
            if ctx.tool_name == "read":
                return HookResult(action=HookAction.DENY, message="Reading is blocked")
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="block-read",
            event=HookEvent.PRE_TOOL_USE,
            func=block_read,
        )
        manager.register_hook(hook)

        result = await manager.run_pre_tool_hooks(
            tool_name="read",
            tool_args={"path": "/test/file.txt"},
        )

        assert result.action == HookAction.DENY
        assert "blocked" in result.message

    @pytest.mark.asyncio
    async def test_run_pre_tool_hooks_modifies(self):
        """Test pre-tool hooks can modify arguments."""
        manager = HookManager()

        async def modify_path(ctx: HookContext) -> HookResult:
            if ctx.tool_args:
                modified = dict(ctx.tool_args)
                modified["path"] = "/safe/path.txt"
                return HookResult(action=HookAction.MODIFY, modified_args=modified)
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="modify-path",
            event=HookEvent.PRE_TOOL_USE,
            func=modify_path,
        )
        manager.register_hook(hook)

        result = await manager.run_pre_tool_hooks(
            tool_name="read",
            tool_args={"path": "/original/path.txt"},
        )

        assert result.action == HookAction.ALLOW
        assert result.modified_args["path"] == "/safe/path.txt"

    @pytest.mark.asyncio
    async def test_run_post_tool_hooks(self):
        """Test post-tool hooks run after execution."""
        manager = HookManager()

        async def log_execution(ctx: HookContext) -> HookResult:
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="log-execution",
            event=HookEvent.POST_TOOL_USE,
            func=log_execution,
        )
        manager.register_hook(hook)

        result = await manager.run_post_tool_hooks(
            tool_name="read",
            tool_args={"path": "/test/file.txt"},
            tool_result="file content",
            tool_success=True,
        )

        assert result.action == HookAction.ALLOW


class TestSecurityHook:
    """Test security hook creation."""

    def test_create_security_hook(self):
        """Test creating a security hook."""
        hook = create_security_hook(
            name="block-env",
            patterns=[r"^env$", r"^get_env$"],
            action=HookAction.DENY,
            message="Environment access denied",
        )

        assert hook.name == "block-env"
        assert hook.enabled is True

    @pytest.mark.asyncio
    async def test_security_hook_blocks(self):
        """Test security hook blocks matching tools."""
        hook = create_security_hook(
            name="block-env",
            patterns=[r"^env$"],
            action=HookAction.DENY,
            message="Blocked",
        )

        ctx = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name="env",
            tool_args={},
        )
        result = await hook.run(ctx)

        assert result.action == HookAction.DENY

    @pytest.mark.asyncio
    async def test_security_hook_allows_non_matching(self):
        """Test security hook allows non-matching tools."""
        hook = create_security_hook(
            name="block-env",
            patterns=[r"^env$"],
            action=HookAction.DENY,
            message="Blocked",
        )

        ctx = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name="read",
            tool_args={},
        )
        result = await hook.run(ctx)

        assert result.action == HookAction.ALLOW


class TestHookManagerSession:
    """Test session-related hooks."""

    @pytest.mark.asyncio
    async def test_session_start_hooks(self):
        """Test session start hooks."""
        manager = HookManager()

        async def session_init(ctx: HookContext) -> HookResult:
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="session-init",
            event=HookEvent.SESSION_START,
            func=session_init,
        )
        manager.register_hook(hook)

        result = await manager.run_session_start_hooks(session_id="test-123")

        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_session_end_hooks(self):
        """Test session end hooks."""
        manager = HookManager()

        async def session_cleanup(ctx: HookContext) -> HookResult:
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="session-cleanup",
            event=HookEvent.SESSION_END,
            func=session_cleanup,
        )
        manager.register_hook(hook)

        result = await manager.run_session_end_hooks(session_id="test-123")

        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_error_hooks(self):
        """Test error hooks."""
        manager = HookManager()

        async def error_logger(ctx: HookContext) -> HookResult:
            return HookResult(action=HookAction.ALLOW)

        hook = PythonHook(
            name="error-logger",
            event=HookEvent.ERROR,
            func=error_logger,
        )
        manager.register_hook(hook)

        test_error = ValueError("Test error")
        result = await manager.run_error_hooks(error=test_error)

        assert result.action == HookAction.ALLOW
