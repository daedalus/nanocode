"""Session sharing functionality."""

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import aiohttp

SHARE_API_BASE = os.environ.get("OPENCODE_SHARE_URL", "https://opncd.ai")
SHARE_DISABLED = os.environ.get("OPENCODE_DISABLE_SHARE", "").lower() in ("true", "1")


@dataclass
class ShareInfo:
    """Information about a shared session."""

    session_id: str
    share_id: str
    secret: str
    url: str
    created_at: datetime = field(default_factory=datetime.now)


class ShareError(Exception):
    """Base exception for share errors."""

    pass


class ShareDisabledError(ShareError):
    """Raised when sharing is disabled."""

    pass


class ShareNotFoundError(ShareError):
    """Raised when share is not found."""

    pass


class ShareQueue:
    """Queue for batching share sync operations."""

    def __init__(self, delay: float = 1.0):
        self._queue: dict[str, dict[str, Any]] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._delay = delay
        self._sync_callback = None

    def set_sync_callback(self, callback):
        """Set the callback for syncing data."""
        self._sync_callback = callback

    async def add(self, session_id: str, data: dict[str, Any]):
        """Add data to the sync queue."""
        if session_id not in self._queue:
            self._queue[session_id] = {}

        self._queue[session_id].update(data)

        if session_id in self._timers:
            self._timers[session_id].cancel()

        self._timers[session_id] = asyncio.create_task(self._flush(session_id))

    async def _flush(self, session_id: str):
        """Flush the queue after delay."""
        await asyncio.sleep(self._delay)

        if session_id in self._queue:
            data = self._queue.pop(session_id)
            if self._sync_callback:
                await self._sync_callback(session_id, data)

        self._timers.pop(session_id, None)

    async def flush_all(self):
        """Flush all pending data."""
        for timer in self._timers.values():
            timer.cancel()

        for session_id in list(self._queue.keys()):
            if session_id in self._timers:
                self._timers[session_id].cancel()

        self._queue.clear()
        self._timers.clear()


class ShareManager:
    """Manages session sharing."""

    _instance: Optional["ShareManager"] = None
    _shares: dict[str, ShareInfo] = {}
    _queue: ShareQueue = ShareQueue()
    _storage = None

    def __new__(cls) -> "ShareManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._session = None
        self._initialized = True
        self._queue.set_sync_callback(self._do_sync)

    def set_storage(self, storage):
        """Set the storage for persisting shares."""
        self._storage = storage

    def reset(self):
        """Reset the share manager."""
        self._shares.clear()
        self._queue = ShareQueue()
        self._queue.set_sync_callback(self._do_sync)

    async def load_from_storage(self):
        """Load shares from persistent storage."""
        if not self._storage:
            return

        try:
            db = await self._storage.get_storage()
            sessions = await db.get_all_sessions()
            for session in sessions:
                share = await db.get_share(session.id)
                if share:
                    self._shares[session.id] = ShareInfo(
                        session_id=share.session_id,
                        share_id=share.share_id,
                        secret=share.secret,
                        url=share.url,
                        created_at=share.created_at,
                    )
        except Exception:
            pass

    @property
    def disabled(self) -> bool:
        """Check if sharing is disabled."""
        return SHARE_DISABLED

    def is_shared(self, session_id: str) -> bool:
        """Check if a session is shared."""
        return session_id in self._shares

    def get_share(self, session_id: str) -> ShareInfo | None:
        """Get share info for a session."""
        return self._shares.get(session_id)

    def list_shares(self) -> list[ShareInfo]:
        """List all shares."""
        return list(self._shares.values())

    async def create(self, session_id: str) -> ShareInfo:
        """Create a share for a session."""
        if self.disabled:
            raise ShareDisabledError("Sharing is disabled")

        if session_id in self._shares:
            return self._shares[session_id]

        share_id = str(uuid.uuid4())
        secret = hashlib.sha256(os.urandom(32)).hexdigest()[:32]

        share_info = ShareInfo(
            session_id=session_id,
            share_id=share_id,
            secret=secret,
            url=f"{SHARE_API_BASE}/share/{share_id}",
        )

        self._shares[session_id] = share_info

        if self._storage:
            try:
                await self._storage.save_share(
                    session_id, share_id, secret, share_info.url
                )
            except Exception:
                pass

        try:
            await self._create_remote(session_id, share_info)
        except Exception:
            pass

        await self.full_sync(session_id)

        return share_info

    async def remove(self, session_id: str):
        """Remove a share for a session."""
        if session_id not in self._shares:
            if self._storage:
                try:
                    db_share = await self._storage.get_share(session_id)
                    if db_share:
                        share_info = ShareInfo(
                            session_id=session_id,
                            share_id=db_share.share_id,
                            secret=db_share.secret,
                            url=db_share.url,
                        )
                        try:
                            await self._remove_remote(share_info)
                        except Exception:
                            pass
                        await self._storage.delete_share(session_id)
                except Exception:
                    pass
            return

        share_info = self._shares.pop(session_id)

        if self._storage:
            try:
                await self._storage.delete_share(session_id)
            except Exception:
                pass

        try:
            await self._remove_remote(share_info)
        except Exception:
            pass

    async def sync(self, session_id: str, data: dict[str, Any]):
        """Queue data for syncing."""
        if self.disabled:
            return

        if session_id not in self._shares:
            return

        await self._queue.add(session_id, data)

    async def _do_sync(self, session_id: str, data: dict[str, Any]):
        """Perform the actual sync."""
        if session_id not in self._shares:
            return

        share_info = self._shares[session_id]

        try:
            await self._sync_remote(session_id, share_info, data)
        except Exception:
            pass

    async def full_sync(self, session_id: str):
        """Perform a full sync of session data."""
        pass

    async def _create_remote(self, session_id: str, share_info: ShareInfo):
        """Create share on remote server."""
        url = f"{SHARE_API_BASE}/api/share"

        payload = {
            "sessionID": session_id,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    raise ShareError(f"Failed to create share: {resp.status}")

                result = await resp.json()
                share_info.share_id = result.get("id", share_info.share_id)
                share_info.secret = result.get("secret", share_info.secret)
                share_info.url = result.get("url", share_info.url)

    async def _remove_remote(self, share_info: ShareInfo):
        """Remove share from remote server."""
        url = f"{SHARE_API_BASE}/api/share/{share_info.share_id}"

        payload = {
            "secret": share_info.secret,
        }

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, json=payload) as resp:
                if resp.status not in (200, 204, 404):
                    raise ShareError(f"Failed to remove share: {resp.status}")

    async def _sync_remote(
        self, session_id: str, share_info: ShareInfo, data: dict[str, Any]
    ):
        """Sync data to remote server."""
        url = f"{SHARE_API_BASE}/api/share/{share_info.share_id}/sync"

        payload = {
            "secret": share_info.secret,
            "data": list(data.values()),
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status not in (200, 204):
                    pass


_manager: ShareManager | None = None


def get_share_manager() -> ShareManager:
    """Get the global share manager."""
    global _manager
    if _manager is None:
        _manager = ShareManager()
    return _manager


def set_share_storage(storage):
    """Set the storage for persisting shares."""
    get_share_manager().set_storage(storage)


async def load_shares_from_storage():
    """Load shares from persistent storage."""
    await get_share_manager().load_from_storage()


async def create_share(session_id: str) -> ShareInfo:
    """Create a share for a session."""
    return await get_share_manager().create(session_id)


async def remove_share(session_id: str):
    """Remove a share for a session."""
    await get_share_manager().remove(session_id)


def get_share(session_id: str) -> ShareInfo | None:
    """Get share info for a session."""
    return get_share_manager().get_share(session_id)


def is_shared(session_id: str) -> bool:
    """Check if a session is shared."""
    return get_share_manager().is_shared(session_id)


def list_shares() -> list[ShareInfo]:
    """List all shares."""
    return get_share_manager().list_shares()


async def sync_share(session_id: str, data: dict[str, Any]):
    """Queue data for syncing to a shared session."""
    await get_share_manager().sync(session_id, data)


def generate_share_url(share_id: str) -> str:
    """Generate a share URL."""
    return f"{SHARE_API_BASE}/share/{share_id}"


class ForkError(Exception):
    """Base exception for fork errors."""

    pass


class ForkManager:
    """Manages session forking."""

    _instance: Optional["ForkManager"] = None
    _storage = None

    def __new__(cls) -> "ForkManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

    def set_storage(self, storage):
        """Set the storage for forking sessions."""
        self._storage = storage

    async def fork_session(self, session_id: str, new_title: str = None) -> str:
        """Fork/duplicate a session."""
        if not self._storage:
            raise ForkError("Storage not configured")

        new_session = await self._storage.fork_session(session_id, new_title)
        if not new_session:
            raise ForkError(f"Session not found: {session_id}")

        return new_session.id


_fork_manager: ForkManager | None = None


def get_fork_manager() -> ForkManager:
    """Get the global fork manager."""
    global _fork_manager
    if _fork_manager is None:
        _fork_manager = ForkManager()
    return _fork_manager


def set_fork_storage(storage):
    """Set the storage for forking sessions."""
    get_fork_manager().set_storage(storage)


async def fork_session(session_id: str, new_title: str = None) -> str:
    """Fork/duplicate a session and return the new session ID."""
    return await get_fork_manager().fork_session(session_id, new_title)
