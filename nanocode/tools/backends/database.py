"""Database filesystem backend - stores skills and memories in SQLite."""

from datetime import datetime

from nanocode.tools.backends.base import FileSystemBackend


class DatabaseBackend(FileSystemBackend):
    """Filesystem backend that reads/writes to SQLite database.

    Maps path-like access to database records:
    - /skills/<name>/SKILL.md  -> Skill record with name=<name>
    - /memory/MEMORY.md      -> Memory record with key='MEMORY.md'

    Paths are virtual: they look like files to the agent but live in DB.
    """

    def __init__(self, session, scope: str = "user", scope_id: str = None):
        """Initialize with a SQLAlchemy async session.

        Args:
            session: SQLAlchemy async session (nanocode storage session)
            scope: 'user', 'org', or 'project'
            scope_id: ID for the scope (user_id, org_id, project_id)
        """
        self.session = session
        self.scope = scope
        self.scope_id = scope_id

    async def _get_skill_by_path(self, path: str):
        """Resolve a path to a Skill DB record."""
        from sqlalchemy import select

        from nanocode.storage.models import Skill

        parts = [p for p in path.split("/") if p]
        if parts[-1] == "SKILL.md" and len(parts) >= 2:
            skill_name = parts[-2]
        else:
            skill_name = parts[-1].replace(".md", "")

        conditions = [
            Skill.name == skill_name,
            Skill.scope == self.scope,
        ]
        if self.scope_id:
            conditions.append(Skill.scope_id == self.scope_id)
        else:
            conditions.append(Skill.scope_id.is_(None))

        stmt = select(Skill).where(*conditions)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_memory_by_path(self, path: str):
        """Resolve a path to a Memory DB record."""
        from sqlalchemy import select

        from nanocode.storage.models import Memory

        parts = [p for p in path.split("/") if p]
        key = parts[-1] if parts else "MEMORY.md"

        conditions = [
            Memory.key == key,
            Memory.scope == self.scope,
        ]
        if self.scope_id:
            conditions.append(Memory.scope_id == self.scope_id)
        else:
            conditions.append(Memory.scope_id.is_(None))

        stmt = select(Memory).where(*conditions)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_skill(self, path: str, content: str = ""):
        """Get existing skill or create a new one."""
        from sqlalchemy import select

        from nanocode.storage.models import Skill

        parts = [p for p in path.split("/") if p]
        if parts[-1] == "SKILL.md" and len(parts) >= 2:
            skill_name = parts[-2]
        else:
            skill_name = parts[-1].replace(".md", "")

        conditions = [
            Skill.name == skill_name,
            Skill.scope == self.scope,
        ]
        if self.scope_id:
            conditions.append(Skill.scope_id == self.scope_id)
        else:
            conditions.append(Skill.scope_id.is_(None))

        stmt = select(Skill).where(*conditions)
        result = await self.session.execute(stmt)
        skill = result.scalar_one_or_none()

        if not skill:
            now = datetime.now()
            skill = Skill(
                id=self._new_id(),
                name=skill_name,
                description="",
                content=content,
                scope=self.scope,
                scope_id=self.scope_id,
                created_at=now,
                updated_at=now,
            )
            self.session.add(skill)
            await self.session.flush()
        return skill

    async def _get_or_create_memory(self, path: str, content: str = ""):
        """Get existing memory or create a new one."""
        from sqlalchemy import select

        from nanocode.storage.models import Memory

        parts = [p for p in path.split("/") if p]
        key = parts[-1] if parts else "MEMORY.md"

        conditions = [
            Memory.key == key,
            Memory.scope == self.scope,
        ]
        if self.scope_id:
            conditions.append(Memory.scope_id == self.scope_id)
        else:
            conditions.append(Memory.scope_id.is_(None))

        stmt = select(Memory).where(*conditions)
        result = await self.session.execute(stmt)
        memory = result.scalar_one_or_none()

        if not memory:
            now = datetime.now()
            memory = Memory(
                id=self._new_id(),
                key=key,
                content=content,
                scope=self.scope,
                scope_id=self.scope_id,
                version=1,
                created_at=now,
                updated_at=now,
            )
            self.session.add(memory)
            await self.session.flush()
        return memory

    def _new_id(self) -> str:
        import uuid
        return str(uuid.uuid4())

    def _is_skill_path(self, path: str) -> bool:
        normalized = path.lstrip("/")
        return normalized.startswith("skills/")

    def _is_memory_path(self, path: str) -> bool:
        normalized = path.lstrip("/")
        return normalized.startswith("memory/")

    async def read(self, path: str, offset: int = None, limit: int = None) -> dict:
        try:
            if self._is_skill_path(path):
                skill = await self._get_skill_by_path(path)
                if not skill:
                    return {
                        "success": True,
                        "content": "",
                        "metadata": {
                            "path": path,
                            "lines": 0,
                            "total_lines": 0,
                            "bytes": 0,
                            "tokens_estimate": 0,
                            "new_file": True,
                        },
                    }
                content = skill.content
            elif self._is_memory_path(path):
                memory = await self._get_memory_by_path(path)
                if not memory:
                    return {
                        "success": True,
                        "content": "",
                        "metadata": {
                            "path": path,
                            "lines": 0,
                            "total_lines": 0,
                            "bytes": 0,
                            "tokens_estimate": 0,
                            "new_file": True,
                        },
                    }
                content = memory.content
            else:
                return {"success": False, "content": None, "error": f"Unknown virtual path: {path}"}

            lines = content.splitlines()
            total_lines = len(lines)
            if offset:
                lines = lines[offset -1 :]
            if limit:
                lines = lines[:limit]
            text = "\n".join(lines)
            bytes_val = len(text.encode("utf-8"))
            tokens_est = max(1, bytes_val // 4)
            return {
                "success": True,
                "content": text,
                "metadata": {
                    "path": path,
                    "lines": len(lines),
                    "total_lines": total_lines,
                    "bytes": bytes_val,
                    "tokens_estimate": tokens_est,
                },
            }
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}

    async def write(self, path: str, content: str) -> dict:
        try:
            if self._is_skill_path(path):
                skill = await self._get_or_create_skill(path, content)
                skill.content = content
                skill.updated_at = datetime.now()
                await self.session.flush()
                await self.session.refresh(skill)
            elif self._is_memory_path(path):
                memory = await self._get_or_create_memory(path, content)
                memory.content = content
                memory.version = (memory.version or 1) + 1
                memory.updated_at = datetime.now()
                await self.session.flush()
                await self.session.refresh(memory)
            else:
                return {"success": False, "content": None, "error": f"Unknown virtual path: {path}"}

            return {
                "success": True,
                "content": f"Written to {path}",
                "metadata": {"path": path, "bytes": len(content.encode("utf-8"))},
            }
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}

    async def edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
        try:
            if self._is_skill_path(path):
                skill = await self._get_skill_by_path(path)
                if not skill:
                    return {"success": False, "content": None, "error": f"Skill not found: {path}"}
                content = skill.content
            elif self._is_memory_path(path):
                memory = await self._get_memory_by_path(path)
                if not memory:
                    return {"success": False, "content": None, "error": f"Memory not found: {path}"}
                content = memory.content
            else:
                return {"success": False, "content": None, "error": f"Unknown virtual path: {path}"}

            occurrence_count = content.count(old_string)
            if occurrence_count == 0:
                return {"success": False, "content": None, "error": f"old_string not found: {old_string}"}
            if not replace_all and occurrence_count > 1:
                return {
                    "success": False,
                    "content": None,
                    "error": f"Found {occurrence_count} matches. Set replace_all=True to replace all.",
                }
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements = occurrence_count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements = 1

            if self._is_skill_path(path):
                skill.content = new_content
                skill.updated_at = datetime.now()
            else:
                memory.content = new_content
                memory.version = (memory.version or 1) + 1
                memory.updated_at = datetime.now()

            await self.session.flush()
            return {
                "success": True,
                "content": f"Successfully edited {path}. Replaced {replacements} occurrence(s).",
                "metadata": {"path": path, "replacements": replacements, "replaceAll": replace_all},
            }
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}

    async def exists(self, path: str) -> bool:
        if self._is_skill_path(path):
            skill = await self._get_skill_by_path(path)
            return skill is not None
        elif self._is_memory_path(path):
            memory = await self._get_memory_by_path(path)
            return memory is not None
        return False

    async def list_dir(self, path: str = "") -> list[dict]:
        from sqlalchemy import select

        from nanocode.storage.models import Memory, Skill

        results = []
        try:
            if not path or path.strip("/") in ("skills", ""):
                conditions = [
                    Skill.scope == self.scope,
                ]
                if self.scope_id:
                    conditions.append(Skill.scope_id == self.scope_id)
                else:
                    conditions.append(Skill.scope_id.is_(None))

                stmt = select(Skill).where(*conditions)
                result = await self.session.execute(stmt)
                for skill in result.scalars().all():
                    results.append({
                        "name": skill.name,
                        "path": f"/skills/{skill.name}/SKILL.md",
                        "is_dir": False,
                    })
            if not path or path.strip("/") in ("memory", ""):
                conditions = [
                    Memory.scope == self.scope,
                ]
                if self.scope_id:
                    conditions.append(Memory.scope_id == self.scope_id)
                else:
                    conditions.append(Memory.scope_id.is_(None))

                stmt = select(Memory).where(*conditions)
                result = await self.session.execute(stmt)
                for memory in result.scalars().all():
                    results.append({
                        "name": memory.key,
                        "path": f"/memory/{memory.key}",
                        "is_dir": False,
                    })
        except Exception:
            pass
        return results

    async def delete(self, path: str) -> dict:
        try:
            if self._is_skill_path(path):
                skill = await self._get_skill_by_path(path)
                if skill:
                    await self.session.delete(skill)
                    await self.session.flush()
                    return {"success": True, "content": f"Deleted skill: {path}"}
            elif self._is_memory_path(path):
                memory = await self._get_memory_by_path(path)
                if memory:
                    await self.session.delete(memory)
                    await self.session.flush()
                    return {"success": True, "content": f"Deleted memory: {path}"}
            return {"success": False, "content": None, "error": f"Not found: {path}"}
        except Exception as e:
            return {"success": False, "content": None, "error": str(e)}
