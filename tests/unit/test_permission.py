"""Tests for permission handler."""

import pytest

from nanocode.agents import (
    AgentMode,
    PermissionAction,
    PermissionRule,
    AgentInfo,
)
from nanocode.agents.permission import (
    PermissionHandler,
    PermissionDeniedError,
    PermissionRejectedError,
    PermissionCorrectedError,
    PermissionReplyType,
    PermissionReply,
)


class TestPermissionHandler:
    """Test permission handler."""

    @pytest.fixture
    def build_agent(self):
        """Create a build agent."""
        return AgentInfo(
            name="build",
            description="Build agent",
            mode=AgentMode.PRIMARY,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
            ],
        )

    @pytest.fixture
    def plan_agent(self):
        """Create a plan agent."""
        return AgentInfo(
            name="plan",
            description="Plan agent",
            mode=AgentMode.PRIMARY,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="edit", pattern="*", action=PermissionAction.DENY),
                PermissionRule(permission="bash", action=PermissionAction.ASK),
            ],
        )

    def test_check_permission_allow(self, build_agent):
        """Test permission check allows when allowed."""
        handler = PermissionHandler()

        action = handler.check_permission(build_agent, "read", {})

        assert action == PermissionAction.ALLOW

    def test_check_permission_deny(self, plan_agent):
        """Test permission check denies when denied."""
        handler = PermissionHandler()

        action = handler.check_permission(plan_agent, "edit", {})

        assert action == PermissionAction.DENY

    def test_check_permission_ask(self, plan_agent):
        """Test permission check asks when configured to ask."""
        handler = PermissionHandler()

        action = handler.check_permission(plan_agent, "bash", {})

        assert action == PermissionAction.ASK

    @pytest.mark.asyncio
    async def test_request_permission_allow(self, build_agent):
        """Test requesting permission when allowed."""
        handler = PermissionHandler()

        result = await handler.request_permission(build_agent, "read", {})

        assert result is True

    @pytest.mark.asyncio
    async def test_request_permission_deny(self, plan_agent):
        """Test requesting permission when denied."""
        handler = PermissionHandler()

        with pytest.raises(PermissionDeniedError):
            await handler.request_permission(plan_agent, "edit", {})

    @pytest.mark.asyncio
    async def test_request_permission_ask_no_callback(self, plan_agent):
        """Test asking permission with no callback defaults to deny."""
        handler = PermissionHandler()
        handler.set_default_deny(True)

        with pytest.raises(PermissionDeniedError):
            await handler.request_permission(plan_agent, "bash", {})

    @pytest.mark.asyncio
    async def test_request_permission_ask_with_callback(self, plan_agent):
        """Test asking permission with callback."""

        async def callback(request):
            return PermissionReply(
                request_id=request.id,
                reply=PermissionReplyType.ONCE,
            )

        handler = PermissionHandler(callback)

        result = await handler.request_permission(plan_agent, "bash", {})

        assert result is True

    @pytest.mark.asyncio
    async def test_request_permission_reject(self, plan_agent):
        """Test permission rejected by user."""

        async def callback(request):
            return PermissionReply(
                request_id=request.id,
                reply=PermissionReplyType.REJECT,
                message="Not allowed",
            )

        handler = PermissionHandler(callback)

        with pytest.raises(PermissionRejectedError) as exc:
            await handler.request_permission(plan_agent, "bash", {})

        assert "Not allowed" in str(exc.value)

    @pytest.mark.asyncio
    async def test_request_permission_always(self, plan_agent):
        """Test permission always granted."""

        async def callback(request):
            return PermissionReply(
                request_id=request.id,
                reply=PermissionReplyType.ALWAYS,
            )

        handler = PermissionHandler(callback)

        result = await handler.request_permission(plan_agent, "bash", {})

        assert result is True

        result2 = await handler.request_permission(plan_agent, "bash", {})
        assert result2 is True

    def test_get_pending_requests(self, build_agent):
        """Test getting pending requests."""
        handler = PermissionHandler()

        requests = handler.get_pending_requests()

        assert len(requests) == 0

    def test_has_pending(self, build_agent):
        """Test checking for pending requests."""
        handler = PermissionHandler()

        assert handler.has_pending() is False


class TestPermissionErrors:
    """Test permission error classes."""

    def test_permission_denied_error(self):
        """Test permission denied error."""
        rules = [PermissionRule(permission="edit", action=PermissionAction.DENY)]
        error = PermissionDeniedError("Denied", rules)

        assert "Denied" in str(error)
        assert error.rules == rules

    def test_permission_rejected_error(self):
        """Test permission rejected error."""
        error = PermissionRejectedError("User rejected")

        assert "User rejected" in str(error)

    def test_permission_corrected_error(self):
        """Test permission corrected error."""
        error = PermissionCorrectedError("Try a different approach")

        assert "Try a different approach" in str(error)
