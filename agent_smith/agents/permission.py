"""Permission system for tool execution control."""

from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Optional
from enum import Enum
import uuid

from nanocode.agents import (
    AgentInfo,
    PermissionAction,
    PermissionRule,
    evaluate_permission,
    get_disabled_tools,
)


class PermissionDeniedError(Exception):
    """Raised when permission is denied."""

    def __init__(self, message: str, rules: Optional[list[PermissionRule]] = None):
        super().__init__(message)
        self.rules = rules if rules is not None else []


class PermissionRejectedError(Exception):
    """Raised when user rejects permission."""

    pass


class PermissionCorrectedError(Exception):
    """Raised when user rejects with correction message."""

    def __init__(self, message: str):
        super().__init__(message)


@dataclass
class PermissionRequest:
    """A permission request."""

    id: str
    agent_name: str
    tool_name: str
    arguments: dict[str, Any]
    permission: str
    pattern: str
    action: PermissionAction


class PermissionReplyType(Enum):
    """Permission reply types."""

    ONCE = "once"
    ALWAYS = "always"
    REJECT = "reject"


@dataclass
class PermissionReply:
    """A permission reply."""

    request_id: str
    reply: PermissionReplyType
    message: Optional[str] = None


PermissionCallback = Callable[[PermissionRequest], Awaitable[PermissionReply]]


class PermissionHandler:
    """Handles permission evaluation and user prompts."""

    def __init__(self, callback: Optional[PermissionCallback] = None):
        self._pending: dict[str, PermissionRequest] = {}
        self._approved: list[PermissionRule] = []
        self._callback = callback
        self._default_deny = False

    def set_callback(self, callback: PermissionCallback):
        """Set the callback for asking permissions."""
        self._callback = callback

    def set_default_deny(self, deny: bool):
        """Set default deny mode for ask permissions without callback."""
        self._default_deny = deny

    def add_approved_rule(self, rule: PermissionRule):
        """Add a permanently approved rule."""
        self._approved.append(rule)

    def check_permission(
        self,
        agent: AgentInfo,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> PermissionAction:
        """Check if tool is allowed for this agent."""
        disabled = get_disabled_tools([tool_name], agent.permission)
        if tool_name in disabled:
            return PermissionAction.DENY

        permission = tool_name
        pattern = "*"

        if tool_name == "str_replace_editor":
            permission = "edit"

        return evaluate_permission(permission, pattern, agent.permission)

    async def request_permission(
        self,
        agent: AgentInfo,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> bool:
        """Request permission to execute a tool."""
        action = self.check_permission(agent, tool_name, arguments)

        if action == PermissionAction.ALLOW:
            return True

        if action == PermissionAction.DENY:
            raise PermissionDeniedError(
                f"Permission denied for tool '{tool_name}'", agent.permission
            )

        if self._callback is None:
            if self._default_deny:
                raise PermissionDeniedError(
                    f"Permission denied for tool '{tool_name}'", agent.permission
                )
            return True

        permission = tool_name
        pattern = "*"

        if tool_name == "str_replace_editor":
            permission = "edit"

        request = PermissionRequest(
            id=str(uuid.uuid4()),
            agent_name=agent.name,
            tool_name=tool_name,
            arguments=arguments,
            permission=permission,
            pattern=pattern,
            action=action,
        )

        self._pending[request.id] = request

        try:
            reply = await self._callback(request)

            if reply.reply == PermissionReplyType.REJECT:
                raise PermissionRejectedError(reply.message or "Permission rejected by user")

            if reply.reply == PermissionReplyType.ALWAYS:
                self.add_approved_rule(
                    PermissionRule(
                        permission=permission,
                        pattern=pattern,
                        action=PermissionAction.ALLOW,
                    )
                )

            return reply.reply != PermissionReplyType.REJECT

        finally:
            self._pending.pop(request.id, None)

    def get_pending_requests(self) -> list[PermissionRequest]:
        """Get list of pending permission requests."""
        return list(self._pending.values())

    def has_pending(self) -> bool:
        """Check if there are pending requests."""
        return len(self._pending) > 0
