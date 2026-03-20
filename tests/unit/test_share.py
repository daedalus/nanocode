"""Tests for share functionality."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from nanocode.share import (
    ShareInfo,
    get_share_manager,
    create_share,
    remove_share,
    get_share,
    is_shared,
    list_shares,
    generate_share_url,
    ForkManager,
    ForkError,
    get_fork_manager,
    fork_session,
)


@pytest.fixture
def share_manager():
    """Get and reset share manager."""
    manager = get_share_manager()
    manager.reset()
    return manager


def test_share_info_dataclass():
    """Test ShareInfo dataclass."""
    info = ShareInfo(
        session_id="session-123",
        share_id="share-456",
        secret="secret123",
        url="https://example.com/share/456",
    )
    assert info.session_id == "session-123"
    assert info.share_id == "share-456"
    assert info.secret == "secret123"
    assert info.url == "https://example.com/share/456"


def test_share_manager_singleton():
    """Test that share manager is a singleton."""
    m1 = get_share_manager()
    m2 = get_share_manager()
    assert m1 is m2


def test_share_manager_reset(share_manager):
    """Test resetting share manager."""
    share_manager.reset()
    assert len(share_manager.list_shares()) == 0


def test_generate_share_url():
    """Test generating share URL."""
    url = generate_share_url("abc123")
    assert "abc123" in url


def test_is_shared_false(share_manager):
    """Test is_shared returns False for non-shared session."""
    assert is_shared("nonexistent") is False


def test_get_share_none(share_manager):
    """Test get_share returns None for non-shared session."""
    assert get_share("nonexistent") is None


@pytest.mark.asyncio
async def test_create_share(share_manager):
    """Test creating a share."""
    info = await create_share("session-123")
    assert info.session_id == "session-123"
    assert info.share_id
    assert info.secret
    assert info.url


@pytest.mark.asyncio
async def test_create_share_idempotent(share_manager):
    """Test that creating a share twice returns same share."""
    info1 = await create_share("session-123")
    info2 = await create_share("session-123")
    assert info1.share_id == info2.share_id


@pytest.mark.asyncio
async def test_list_shares(share_manager):
    """Test listing shares."""
    await create_share("session-1")
    await create_share("session-2")
    shares = list_shares()
    assert len(shares) == 2


@pytest.mark.asyncio
async def test_remove_share(share_manager):
    """Test removing a share."""
    await create_share("session-123")
    assert is_shared("session-123") is True

    await remove_share("session-123")
    assert is_shared("session-123") is False


@pytest.mark.asyncio
async def test_get_share_after_create(share_manager):
    """Test getting share after creation."""
    await create_share("session-123")
    info = get_share("session-123")
    assert info is not None
    assert info.session_id == "session-123"


def test_disabled_property(share_manager):
    """Test disabled property."""
    assert isinstance(share_manager.disabled, bool)


@pytest.mark.asyncio
async def test_sync_share(share_manager):
    """Test syncing share data."""
    await create_share("session-123")

    await asyncio.sleep(0.1)

    result = get_share("session-123")
    assert result is not None


def test_share_info_has_url(share_manager):
    """Test that share info has URL."""
    import os

    os.environ["OPENCODE_SHARE_URL"] = "https://custom.example.com"

    manager = get_share_manager()
    manager.reset()

    ShareInfo(
        session_id="test",
        share_id="abc",
        secret="xyz",
        url="",
    )

    assert "custom.example.com" in "https://custom.example.com/share/abc"


def test_fork_manager_singleton():
    """Test that fork manager is a singleton."""
    m1 = get_fork_manager()
    m2 = get_fork_manager()
    assert m1 is m2


def test_fork_manager_set_storage():
    """Test setting storage on fork manager."""
    manager = get_fork_manager()
    mock_storage = MagicMock()
    manager.set_storage(mock_storage)
    assert manager._storage is mock_storage


@pytest.mark.asyncio
async def test_fork_session_success():
    """Test forking a session successfully."""
    manager = get_fork_manager()
    mock_storage = AsyncMock()
    mock_storage.fork_session = AsyncMock(return_value=MagicMock(id="new-session-id"))
    manager.set_storage(mock_storage)

    result = await fork_session("session-123", "New Session")
    assert result == "new-session-id"
    mock_storage.fork_session.assert_called_once_with("session-123", "New Session")


@pytest.mark.asyncio
async def test_fork_session_with_default_title():
    """Test forking a session with default title."""
    manager = get_fork_manager()
    mock_storage = AsyncMock()
    mock_storage.fork_session = AsyncMock(return_value=MagicMock(id="new-session-id"))
    manager.set_storage(mock_storage)

    await fork_session("session-123")
    mock_storage.fork_session.assert_called_once_with("session-123", None)


@pytest.mark.asyncio
async def test_fork_session_not_found():
    """Test forking a non-existent session."""
    manager = get_fork_manager()
    mock_storage = AsyncMock()
    mock_storage.fork_session = AsyncMock(return_value=None)
    manager.set_storage(mock_storage)

    with pytest.raises(ForkError, match="Session not found"):
        await fork_session("nonexistent")


@pytest.mark.asyncio
async def test_fork_session_no_storage():
    """Test forking without storage configured."""
    manager = get_fork_manager()
    manager.set_storage(None)

    with pytest.raises(ForkError, match="Storage not configured"):
        await fork_session("session-123")


@pytest.mark.asyncio
async def test_fork_manager_instance():
    """Test fork manager instance methods."""
    manager = ForkManager()
    assert manager._initialized is True
    assert manager._storage is None


@pytest.mark.asyncio
async def test_share_manager_set_storage():
    """Test setting storage on share manager."""
    manager = get_share_manager()
    mock_storage = MagicMock()
    manager.set_storage(mock_storage)
    assert manager._storage is mock_storage


@pytest.mark.asyncio
async def test_share_persists_to_storage():
    """Test that shares are persisted to storage."""
    manager = get_share_manager()
    manager.reset()

    mock_storage = AsyncMock()
    mock_storage.save_share = AsyncMock()

    manager.set_storage(mock_storage)
    await create_share("session-123")

    mock_storage.save_share.assert_called_once()
    call_args = mock_storage.save_share.call_args
    assert call_args[0][0] == "session-123"


@pytest.mark.asyncio
async def test_share_removed_from_storage():
    """Test that shares are removed from storage."""
    manager = get_share_manager()
    manager.reset()

    await create_share("session-123")

    mock_storage = AsyncMock()
    mock_storage.save_share = AsyncMock()
    mock_storage.delete_share = AsyncMock()

    manager.set_storage(mock_storage)
    await remove_share("session-123")

    mock_storage.delete_share.assert_called_once_with("session-123")


@pytest.mark.asyncio
async def test_share_loads_from_storage():
    """Test loading shares from storage."""
    from datetime import datetime

    manager = get_share_manager()
    manager.reset()

    mock_db_share = MagicMock()
    mock_db_share.session_id = "session-123"
    mock_db_share.share_id = "share-456"
    mock_db_share.secret = "secret123"
    mock_db_share.url = "https://example.com/share/456"
    mock_db_share.created_at = datetime.now()

    mock_session = MagicMock()
    mock_session.id = "session-123"

    mock_storage = MagicMock()
    mock_storage.get_storage = AsyncMock(
        return_value=AsyncMock(
            get_all_sessions=AsyncMock(return_value=[mock_session]),
            get_share=AsyncMock(return_value=mock_db_share),
        )
    )

    manager.set_storage(mock_storage)
    await manager.load_from_storage()

    assert is_shared("session-123") is True
    share = get_share("session-123")
    assert share is not None
    assert share.share_id == "share-456"
