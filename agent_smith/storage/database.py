"""Database connection and session management."""

import os
import asyncio
from typing import Optional
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from .models import Base


class Database:
    """Database connection manager."""

    _instance: Optional["Database"] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, db_path: str = None):
        if db_path is None:
            home = os.path.expanduser("~")
            data_dir = os.path.join(home, ".nanocode", "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "nanocode.db")

        self.db_path = db_path
        self._engine = None
        self._session_factory = None

    @classmethod
    async def get_instance(cls, db_path: str = None) -> "Database":
        """Get singleton database instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
                await cls._instance.connect()
            return cls._instance

    async def connect(self):
        """Connect to the database."""
        url = f"sqlite+aiosqlite:///{self.db_path}"
        self._engine = create_async_engine(
            url,
            echo=False,
            future=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        await self._create_tables()

    async def _create_tables(self):
        """Create all tables."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncSession:
        """Get a database session."""
        if self._session_factory is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self):
        """Close the database connection."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    @property
    def path(self) -> str:
        """Get the database file path."""
        return self.db_path


async def get_db() -> Database:
    """Get the database instance."""
    return await Database.get_instance()
