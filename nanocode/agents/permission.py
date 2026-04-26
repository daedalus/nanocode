"""Permission system for tool execution control."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from nanocode.agents import (
    AgentInfo,
    PermissionAction,
    PermissionRule,
    evaluate_permission,
    get_disabled_tools,
)

logger = logging.getLogger("nanocode.permission")


class PermissionDeniedError(Exception):
    """Raised when permission is denied."""

    def __init__(self, message: str, rules: list[PermissionRule] | None = None):
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

    ALLOW = "allow"
    ONCE = "once"
    ALWAYS = "always"
    REJECT = "reject"


@dataclass
class PermissionReply:
    """A permission reply."""

    request_id: str
    reply: PermissionReplyType
    message: str | None = None


PermissionCallback = Callable[[PermissionRequest], Awaitable[PermissionReply]]


class PermissionHandler:
    """Handles permission evaluation and user prompts."""

    def __init__(self, callback: PermissionCallback | None = None):
        self._pending: dict[str, PermissionRequest] = {}
        self._approved: list[PermissionRule] = []
        self._callback = callback
        self._default_deny = False
        logger.debug("PermissionHandler initialized")

    def set_callback(self, callback: PermissionCallback):
        """Set the callback for asking permissions."""
        logger.debug("PermissionHandler callback set")
        self._callback = callback

    def set_default_deny(self, deny: bool):
        """Set default deny mode for ask permissions without callback."""
        logger.debug(f"PermissionHandler default_deny set to: {deny}")
        self._default_deny = deny

    def add_approved_rule(self, rule: PermissionRule):
        """Add a permanently approved rule."""
        self._approved.append(rule)
        logger.debug(
            f"Approved rule added: permission={rule.permission}, pattern={rule.pattern}"
        )

    def check_permission(
        self,
        agent: AgentInfo,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> PermissionAction:
        """Check if tool is allowed for this agent."""
        disabled = get_disabled_tools([tool_name], agent.permission)
        if tool_name in disabled:
            logger.debug(
                f"[{agent.name}] check_permission('{tool_name}') -> DENY (tool disabled)"
            )
            return PermissionAction.DENY

        permission = tool_name
        pattern = "*"

        if tool_name == "str_replace_editor":
            permission = "edit"

        action = evaluate_permission(permission, pattern, agent.permission)
        logger.debug(
            f"[{agent.name}] check_permission('{tool_name}', args={arguments}) -> {action.value}"
        )
        return action

    async def request_permission(
        self,
        agent: AgentInfo,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> bool:
        """Request permission to execute a tool."""
        action = self.check_permission(agent, tool_name, arguments)
        logger.debug(
            f"[{agent.name}] request_permission('{tool_name}') action={action.value}"
        )

        if action == PermissionAction.ALLOW:
            logger.debug(f"[{agent.name}] Permission ALLOWED for '{tool_name}'")
            return True

        if action == PermissionAction.DENY:
            logger.warning(f"[{agent.name}] Permission DENIED for '{tool_name}'")
            raise PermissionDeniedError(
                f"Permission denied for tool '{tool_name}'", agent.permission
            )

        if self._callback is None:
            # In TUI mode with no callback, auto-allow (permissions handled via UI)
            logger.debug(
                f"[{agent.name}] Permission ASK (no callback) -> allowing by default"
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

        logger.info(
            f"[{agent.name}] Requesting permission for '{tool_name}': {request}"
        )
        self._pending[request.id] = request

        try:
            reply = await self._callback(request)

            if reply.reply == PermissionReplyType.REJECT:
                logger.warning(
                    f"[{agent.name}] Permission REJECTED for '{tool_name}': {reply.message}"
                )
                raise PermissionRejectedError(
                    reply.message or "Permission rejected by user"
                )

            if reply.reply == PermissionReplyType.ALWAYS:
                logger.info(
                    f"[{agent.name}] Permission ALWAYS ALLOWED for '{tool_name}' (pattern={pattern})"
                )
                self.add_approved_rule(
                    PermissionRule(
                        permission=permission,
                        pattern=pattern,
                        action=PermissionAction.ALLOW,
                    )
                )

            allowed = reply.reply != PermissionReplyType.REJECT
            logger.info(
                f"[{agent.name}] Permission result for '{tool_name}': {reply.reply.value} -> allowed={allowed}"
            )
            return allowed

        finally:
            self._pending.pop(request.id, None)

    def get_pending_requests(self) -> list[PermissionRequest]:
        """Get list of pending permission requests."""
        requests = list(self._pending.values())
        logger.debug(f"get_pending_requests() -> {len(requests)} pending")
        return requests

    def has_pending(self) -> bool:
        """Check if there are pending requests."""
        has = len(self._pending) > 0
        if has:
            logger.debug(f"has_pending() -> True ({len(self._pending)} pending)")
        return has
