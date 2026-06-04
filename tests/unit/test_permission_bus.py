"""Tests for permission bus - event-driven permission system."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class TestPermissionEventTypes:
    """Test PermissionEventType enum."""

    def test_event_types_exist(self):
        """Test PermissionEventType has required values."""
        from nanocode.agents.permission_bus import PermissionEventType

        assert PermissionEventType.ASKED.value == "permission.asked"
        assert PermissionEventType.ANSWERED.value == "permission.answered"
        assert PermissionEventType.REPLIED.value == "permission.replied"


class TestPermissionEvents:
    """Test permission event dataclasses."""

    def test_asked_event(self):
        """Test PermissionAskedEvent creation."""
        from nanocode.agents.permission_bus import PermissionAskedEvent

        event = PermissionAskedEvent(
            id="perm_1", session_id="sess_1", tool_name="bash",
            permission="allow", metadata={"command": "ls"},
        )
        assert event.id == "perm_1"
        assert event.tool_name == "bash"

    def test_replied_event(self):
        """Test PermissionRepliedEvent creation."""
        from nanocode.agents.permission_bus import PermissionRepliedEvent

        event = PermissionRepliedEvent(id="perm_1", session_id="sess_1", reply="allow")
        assert event.reply == "allow"


@pytest.mark.usefixtures("preserve_cwd")
class TestPermissionBus:
    """Test PermissionBus singleton."""

    def test_singleton(self):
        """Test PermissionBus is a singleton."""
        from nanocode.agents.permission_bus import PermissionBus

        bus1 = PermissionBus()
        bus2 = PermissionBus()
        assert bus1 is bus2

    def test_initial_state(self):
        """Test PermissionBus initial state."""
        from nanocode.agents.permission_bus import PermissionBus

        bus = PermissionBus()
        assert bus.has_pending() is False
        assert bus.get_pending_count() == 0

    def test_subscribe_and_emit(self):
        """Test subscribing and emitting events."""
        from nanocode.agents.permission_bus import (
            PermissionBus, PermissionEventType, PermissionAskedEvent,
        )

        bus = PermissionBus()
        handler = MagicMock()
        bus.subscribe(PermissionEventType.ASKED, handler)
        event = PermissionAskedEvent(
            id="perm_1", session_id="sess_1", tool_name="bash",
            permission="allow", metadata={},
        )
        with patch.object(bus, "_pending_requests", {}):
            asyncio.run(bus.emit(event))
        handler.assert_called_once()

    def test_unsubscribe(self):
        """Test unsubscribing from events."""
        from nanocode.agents.permission_bus import (
            PermissionBus, PermissionEventType, PermissionAskedEvent,
        )

        bus = PermissionBus()
        handler = MagicMock()
        bus.subscribe(PermissionEventType.ASKED, handler)
        bus.unsubscribe(PermissionEventType.ASKED, handler)
        event = PermissionAskedEvent(
            id="perm_1", session_id="sess_1", tool_name="bash",
            permission="allow", metadata={},
        )
        with patch.object(bus, "_pending_requests", {}):
            asyncio.run(bus.emit(event))
        handler.assert_not_called()

    def test_reply_permission(self):
        """Test replying to a pending permission."""
        from nanocode.agents.permission_bus import PermissionBus

        bus = PermissionBus()

        async def run_test():
            future = asyncio.Future()
            with patch.object(bus, "_pending_requests", {"perm_1": future}):
                bus.reply_permission("perm_1", "allow")
                assert future.result() == "allow"

        asyncio.run(run_test())

    def test_reply_permission_unknown(self):
        """Test replying to unknown permission does not raise."""
        from nanocode.agents.permission_bus import PermissionBus

        bus = PermissionBus()
        bus.reply_permission("unknown_id", "allow")

    def test_has_pending(self):
        """Test has_pending returns True when requests exist."""
        from nanocode.agents.permission_bus import PermissionBus

        bus = PermissionBus()
        with patch.object(bus, "_pending_requests", {"perm_1": MagicMock()}):
            assert bus.has_pending() is True

    def test_get_pending_count(self):
        """Test get_pending_count returns correct count."""
        from nanocode.agents.permission_bus import PermissionBus

        bus = PermissionBus()
        with patch.object(bus, "_pending_requests", {
            "perm_1": MagicMock(),
            "perm_2": MagicMock(),
        }):
            assert bus.get_pending_count() == 2

    @pytest.mark.asyncio
    async def test_request_permission_timeout(self):
        """Test request_permission times out and returns reject."""
        from nanocode.agents.permission_bus import PermissionBus

        bus = PermissionBus()
        with patch.object(bus, "emit") as mock_emit:
            mock_emit.return_value = None
            result = await bus.request_permission(
                session_id="sess_1", tool_name="bash",
                permission="allow", metadata={},
            )
            assert result == "reject"

    def test_get_permission_bus(self):
        """Test get_permission_bus returns singleton."""
        from nanocode.agents.permission_bus import get_permission_bus, PermissionBus

        bus = get_permission_bus()
        assert isinstance(bus, PermissionBus)
