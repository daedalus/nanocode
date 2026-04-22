"""Hook system for agent lifecycle events."""

import asyncio
import importlib.util
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger("nanocode.hooks")


class HookEvent(StrEnum):
    """Events that can trigger hooks."""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    NOTIFICATION = "Notification"
    STOP = "Stop"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    ERROR = "Error"


class HookAction(StrEnum):
    """Actions a hook can take."""

    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    MODIFY = "modify"
    STOP = "stop"


@dataclass
class HookContext:
    """Context passed to hooks."""

    event: HookEvent
    session_id: str | None = None
    agent_name: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None
    tool_success: bool | None = None
    message: str | None = None
    error: Exception | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """Result from hook execution."""

    action: HookAction
    message: str | None = None
    modified_args: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


HookCallable = Callable[[HookContext], Awaitable[HookResult]]


class Hook(ABC):
    """Base class for hooks."""

    def __init__(
        self,
        name: str,
        event: HookEvent,
        description: str = "",
        enabled: bool = True,
    ):
        self.name = name
        self.event = event
        self.description = description
        self.enabled = enabled

    @abstractmethod
    async def run(self, context: HookContext) -> HookResult:
        """Execute the hook."""
        pass

    def matches_pattern(self, tool_name: str | None, pattern: str | None) -> bool:
        """Check if this hook matches the given tool pattern."""
        if not pattern:
            return True
        if not tool_name:
            return False
        try:
            return bool(re.match(pattern, tool_name))
        except re.error:
            return tool_name == pattern


@dataclass
class CommandHook(Hook):
    """Hook that runs a shell command."""

    command: str = ""
    shell: bool = True
    timeout: int = 30
    action_on_result: HookAction = HookAction.ALLOW

    def __init__(
        self,
        name: str,
        event: HookEvent,
        command: str,
        description: str = "",
        pattern: str | None = None,
        action_on_result: HookAction = HookAction.ALLOW,
        enabled: bool = True,
    ):
        super().__init__(name, event, description, enabled)
        self.command = command
        self.pattern = pattern
        self.action_on_result = action_on_result
        self.shell = True
        self.timeout = 30

    async def run(self, context: HookContext) -> HookResult:
        """Execute the shell command."""
        import subprocess

        env = os.environ.copy()
        env["NANO_HOOK_EVENT"] = context.event.value
        env["NANO_HOOK_TOOL"] = context.tool_name or ""
        env["NANO_HOOK_SESSION"] = context.session_id or ""

        try:
            proc = await asyncio.create_subprocess_shell(
                self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            if proc.returncode == 0:
                return HookResult(
                    action=self.action_on_result,
                    message=stdout.decode().strip() if stdout else None,
                )
            else:
                return HookResult(
                    action=HookAction.DENY,
                    message=f"Hook failed: {stderr.decode().strip() if stderr else 'unknown error'}",
                )
        except TimeoutError:
            return HookResult(
                action=HookAction.DENY,
                message=f"Hook timed out after {self.timeout}s",
            )
        except Exception as e:
            return HookResult(
                action=HookAction.DENY,
                message=f"Hook error: {str(e)}",
            )


@dataclass
class PythonHook(Hook):
    """Hook that runs a Python function."""

    func: HookCallable | None = None
    module_path: str | None = None
    function_name: str | None = None

    def __init__(
        self,
        name: str,
        event: HookEvent,
        func: HookCallable | None = None,
        module_path: str | None = None,
        function_name: str | None = None,
        description: str = "",
        pattern: str | None = None,
        enabled: bool = True,
    ):
        super().__init__(name, event, description, enabled)
        self.func = func
        self.module_path = module_path
        self.function_name = function_name
        self.pattern = pattern

    async def run(self, context: HookContext) -> HookResult:
        """Execute the Python function."""
        if self.func:
            return await self.func(context)

        if self.module_path and self.function_name:
            try:
                spec = importlib.util.spec_from_file_location(
                    self.module_path, self.module_path
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    func = getattr(module, self.function_name)
                    return await func(context)
            except Exception as e:
                return HookResult(
                    action=HookAction.DENY,
                    message=f"Failed to load hook: {str(e)}",
                )

        return HookResult(action=HookAction.ALLOW)


class HookManager:
    """Manages hooks and their execution."""

    DEFAULT_HOOK_DIRS = [
        ".nanocode/hooks",
        ".claude/hooks",
        ".opencode/hooks",
        os.path.expanduser("~/.nanocode/hooks"),
        os.path.expanduser("~/.config/nanocode/hooks"),
    ]

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.getcwd()
        self.hooks: dict[HookEvent, list[Hook]] = {
            event: [] for event in HookEvent
        }
        self._python_hooks: dict[str, HookCallable] = {}

    def discover_hooks(self) -> list[Hook]:
        """Discover hooks in configured directories."""
        discovered = []

        search_paths = []
        for d in self.DEFAULT_HOOK_DIRS:
            if d.startswith("."):
                search_paths.append(os.path.join(self.base_dir, d))
            elif os.path.isabs(d):
                search_paths.append(d)

        for path in search_paths:
            if os.path.isdir(path):
                for filename in os.listdir(path):
                    if filename.endswith((".json", ".py")):
                        full_path = os.path.join(path, filename)
                        try:
                            if filename.endswith(".json"):
                                hooks = self._load_json_hook(full_path)
                            else:
                                hooks = self._load_python_hook(full_path)
                            discovered.extend(hooks)
                            logger.info(f"Loaded {len(hooks)} hook(s) from {full_path}")
                        except Exception as e:
                            logger.error(f"Failed to load hook {full_path}: {e}")

        for hook in discovered:
            self.register_hook(hook)

        return discovered

    def _load_json_hook(self, path: str) -> list[Hook]:
        """Load hooks from a JSON file."""
        with open(path) as f:
            data = json.load(f)

        hooks = []
        hook_configs = data if isinstance(data, list) else [data]

        for config in hook_configs:
            event = HookEvent(config.get("event", ""))
            name = config.get("name", os.path.basename(path))
            description = config.get("description", "")
            pattern = config.get("pattern")
            enabled = config.get("enabled", True)

            if config.get("type") == "command":
                hook = CommandHook(
                    name=name,
                    event=event,
                    command=config.get("command", ""),
                    description=description,
                    pattern=pattern,
                    action_on_result=HookAction(
                        config.get("action_on_result", "allow")
                    ),
                    enabled=enabled,
                )
                hooks.append(hook)

        return hooks

    def _load_python_hook(self, path: str) -> list[Hook]:
        """Load hooks from a Python file."""
        hooks = []
        try:
            spec = importlib.util.spec_from_file_location("hook_module", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, Hook) and attr != Hook:
                        instance = attr()
                        if isinstance(instance, Hook):
                            hooks.append(instance)
        except Exception as e:
            logger.error(f"Failed to load Python hook {path}: {e}")

        return hooks

    def register_hook(self, hook: Hook) -> None:
        """Register a hook."""
        self.hooks[hook.event].append(hook)
        logger.debug(f"Registered hook '{hook.name}' for event '{hook.event.value}'")

    def unregister_hook(self, name: str) -> bool:
        """Unregister a hook by name."""
        for event_hooks in self.hooks.values():
            for i, hook in enumerate(event_hooks):
                if hook.name == name:
                    event_hooks.pop(i)
                    return True
        return False

    def get_hooks(self, event: HookEvent, tool_name: str | None = None) -> list[Hook]:
        """Get hooks for an event, optionally filtered by tool name."""
        result = []
        for hook in self.hooks.get(event, []):
            if hook.enabled and hook.matches_pattern(tool_name, getattr(hook, "pattern", None)):
                result.append(hook)
        return result

    async def run_pre_tool_hooks(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session_id: str | None = None,
        agent_name: str | None = None,
    ) -> HookResult:
        """Run PreToolUse hooks and return combined result."""
        context = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
        )

        hooks = self.get_hooks(HookEvent.PRE_TOOL_USE, tool_name)
        for hook in hooks:
            result = await hook.run(context)
            if result.action == HookAction.DENY:
                return result
            if result.action == HookAction.MODIFY and result.modified_args:
                context.tool_args = result.modified_args

        return HookResult(action=HookAction.ALLOW, modified_args=context.tool_args)

    async def run_post_tool_hooks(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Any,
        tool_success: bool,
        session_id: str | None = None,
        agent_name: str | None = None,
    ) -> HookResult:
        """Run PostToolUse hooks and return combined result."""
        context = HookContext(
            event=HookEvent.POST_TOOL_USE,
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            tool_success=tool_success,
        )

        hooks = self.get_hooks(HookEvent.POST_TOOL_USE, tool_name)
        for hook in hooks:
            result = await hook.run(context)
            if result.action == HookAction.STOP:
                return result

        return HookResult(action=HookAction.ALLOW)

    async def run_notification_hook(
        self,
        message: str,
        session_id: str | None = None,
    ) -> HookResult:
        """Run Notification hooks."""
        context = HookContext(
            event=HookEvent.NOTIFICATION,
            session_id=session_id,
            message=message,
        )

        hooks = self.get_hooks(HookEvent.NOTIFICATION)
        for hook in hooks:
            result = await hook.run(context)
            if result.action == HookAction.STOP:
                return result

        return HookResult(action=HookAction.ALLOW)

    async def run_session_start_hooks(
        self,
        session_id: str,
    ) -> HookResult:
        """Run SessionStart hooks."""
        context = HookContext(
            event=HookEvent.SESSION_START,
            session_id=session_id,
        )

        hooks = self.get_hooks(HookEvent.SESSION_START)
        for hook in hooks:
            result = await hook.run(context)
            if result.action == HookAction.DENY:
                return result

        return HookResult(action=HookAction.ALLOW)

    async def run_session_end_hooks(
        self,
        session_id: str,
    ) -> HookResult:
        """Run SessionEnd hooks."""
        context = HookContext(
            event=HookEvent.SESSION_END,
            session_id=session_id,
        )

        hooks = self.get_hooks(HookEvent.SESSION_END)
        for hook in hooks:
            result = await hook.run(context)
            if result.action == HookAction.STOP:
                return result

        return HookResult(action=HookAction.ALLOW)

    async def run_error_hooks(
        self,
        error: Exception,
        session_id: str | None = None,
    ) -> HookResult:
        """Run Error hooks."""
        context = HookContext(
            event=HookEvent.ERROR,
            session_id=session_id,
            error=error,
        )

        hooks = self.get_hooks(HookEvent.ERROR)
        for hook in hooks:
            result = await hook.run(context)
            if result.action == HookAction.STOP:
                return result

        return HookResult(action=HookAction.ALLOW)


def create_security_hook(
    name: str,
    patterns: list[str],
    action: HookAction = HookAction.DENY,
    message: str = "Tool blocked by security hook",
) -> Hook:
    """Create a security hook that blocks specific tool patterns."""

    class SecurityHook(Hook):
        def __init__(self):
            super().__init__(name, HookEvent.PRE_TOOL_USE, f"Security hook for {patterns}")
            self.patterns = patterns
            self.action = action
            self.message = message

        def matches_pattern(self, tool_name: str | None, pattern: str | None) -> bool:
            if not tool_name:
                return False
            for p in self.patterns:
                if re.match(p, tool_name):
                    return True
            return False

        async def run(self, context: HookContext) -> HookResult:
            if context.tool_name and self.matches_pattern(context.tool_name, None):
                return HookResult(action=self.action, message=self.message)
            return HookResult(action=HookAction.ALLOW)

    return SecurityHook()
