"""Session storage operations."""

import uuid
import os
from datetime import datetime
from typing import Optional, AsyncIterator
from pathlib import Path

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Project, Session, Message, MessagePart, Todo
from .database import Database, get_db


class SessionStorage:
    """Handles persistent session storage."""

    def __init__(self, db: Database):
        self.db = db

    async def create_project(self, name: str, directory: str) -> Project:
        """Create a new project."""
        async with self.db.session() as session:
            project = Project(
                id=str(uuid.uuid4()),
                name=name,
                directory=os.path.abspath(directory),
            )
            session.add(project)
            await session.flush()
            return project

    async def get_project(self, project_id: str) -> Optional[Project]:
        """Get a project by ID."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Project).where(Project.id == project_id)
            )
            return result.scalar_one_or_none()

    async def get_project_by_directory(self, directory: str) -> Optional[Project]:
        """Get a project by directory."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Project).where(Project.directory == os.path.abspath(directory))
            )
            return result.scalar_one_or_none()

    async def get_or_create_project(self, directory: str, name: str = None) -> Project:
        """Get or create a project for a directory."""
        directory = os.path.abspath(directory)
        project = await self.get_project_by_directory(directory)
        if project:
            return project
        
        if name is None:
            name = os.path.basename(directory) or "default"
        return await self.create_project(name, directory)

    async def create_session(
        self,
        project_id: str,
        title: str = None,
        directory: str = None,
        parent_id: str = None,
    ) -> Session:
        """Create a new session."""
        async with self.db.session() as session:
            session_obj = Session(
                id=str(uuid.uuid4()),
                project_id=project_id,
                title=title or f"Session - {datetime.now().isoformat()}",
                directory=directory or os.getcwd(),
                parent_id=parent_id,
            )
            session.add(session_obj)
            await session.flush()
            return session_obj

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session).where(Session.id == session_id)
            )
            return result.scalar_one_or_none()

    async def get_sessions(self, project_id: str, limit: int = 50) -> list[Session]:
        """Get sessions for a project."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session)
                .where(Session.project_id == project_id)
                .order_by(Session.updated_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def update_session(self, session_id: str, **kwargs) -> Optional[Session]:
        """Update a session."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session).where(Session.id == session_id)
            )
            session_obj = result.scalar_one_or_none()
            if session_obj:
                for key, value in kwargs.items():
                    if hasattr(session_obj, key):
                        setattr(session_obj, key, value)
                await session.flush()
            return session_obj

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Session).where(Session.id == session_id)
            )
            return result.rowcount > 0

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_call_id: str = None,
        tokens: int = 0,
        metadata: dict = None,
    ) -> Message:
        """Add a message to a session."""
        async with self.db.session() as session:
            message = Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role=role,
                content=content,
                tool_call_id=tool_call_id,
                tokens=tokens,
                metadata=metadata,
            )
            session.add(message)
            
            result = await session.execute(
                select(Session).where(Session.id == session_id)
            )
            session_obj = result.scalar_one_or_none()
            if session_obj:
                session_obj.updated_at = datetime.now()
            
            await session.flush()
            return message

    async def get_messages(self, session_id: str) -> list[Message]:
        """Get all messages for a session."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at)
            )
            return list(result.scalars().all())

    async def delete_message(self, message_id: str) -> bool:
        """Delete a message."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Message).where(Message.id == message_id)
            )
            return result.rowcount > 0

    async def clear_messages(self, session_id: str) -> int:
        """Clear all messages from a session."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Message).where(Message.session_id == session_id)
            )
            return result.rowcount

    async def add_todo(
        self,
        session_id: str,
        content: str,
        position: int = 0,
        priority: str = "medium",
    ) -> Todo:
        """Add a todo to a session."""
        async with self.db.session() as session:
            todo = Todo(
                session_id=session_id,
                position=position,
                content=content,
                status="pending",
                priority=priority,
            )
            session.add(todo)
            await session.flush()
            return todo

    async def get_todos(self, session_id: str) -> list[Todo]:
        """Get all todos for a session."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Todo)
                .where(Todo.session_id == session_id)
                .order_by(Todo.position)
            )
            return list(result.scalars().all())

    async def update_todo(
        self,
        session_id: str,
        position: int,
        status: str = None,
        content: str = None,
    ) -> Optional[Todo]:
        """Update a todo."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Todo).where(
                    Todo.session_id == session_id,
                    Todo.position == position,
                )
            )
            todo = result.scalar_one_or_none()
            if todo:
                if status:
                    todo.status = status
                if content:
                    todo.content = content
                await session.flush()
            return todo

    async def delete_todo(self, session_id: str, position: int) -> bool:
        """Delete a todo."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Todo).where(
                    Todo.session_id == session_id,
                    Todo.position == position,
                )
            )
            return result.rowcount > 0


async def get_storage() -> SessionStorage:
    """Get a session storage instance."""
    db = await get_db()
    return SessionStorage(db)
