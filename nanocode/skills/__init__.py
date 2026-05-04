"""Skills system - custom commands defined in .nanocode/skills/ or fetched from URLs."""

import asyncio
import fnmatch
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import frontmatter
import httpx

logger = logging.getLogger(__name__)


# Opencode-inspired constants for skill discovery
EXTERNAL_DIRS = [".claude", ".agents"]
OPENCODE_SKILL_PATTERN = "{skill,skills}/**/SKILL.md"
EXTERNAL_SKILL_PATTERN = "skills/**/SKILL.md"
SKILL_FILE_NAME = "SKILL.md"


def expand_path(pattern: str) -> str:
    """Expand path patterns (e.g., ~/ and $HOME/)."""
    if pattern.startswith("~/"):
        return os.path.expanduser(pattern)
    if pattern.startswith("~"):
        return os.path.expanduser(pattern)
    if pattern.startswith("$HOME/"):
        return os.path.expandvars(pattern)
    if pattern.startswith("$HOME"):
        return os.path.expandvars(pattern)
    return pattern


def match_pattern(pattern: str, value: str) -> bool:
    """Match a pattern against a value using wildcards."""
    pattern = expand_path(pattern)
    if pattern == "*":
        return True
    result = fnmatch.fnmatch(value, pattern)
    logger.debug(f"match_pattern('{pattern}', '{value}') -> {result}")
    return result


# TYPE_CHECKING imports to avoid circular dependencies
if TYPE_CHECKING:
    from nanocode.agents import AgentInfo


def _get_skills_cache_dir() -> Path:
    """Get cache directory for remote skills."""
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "nanocode" / "cache" / "skills"


# Opencode-inspired constants for skill discovery
EXTERNAL_DIRS = [".claude", ".agents"]
OPENCODE_SKILL_PATTERN = "{skill,skills}/**/SKILL.md"
EXTERNAL_SKILL_PATTERN = "skills/**/SKILL.md"
SKILL_FILE_NAME = "SKILL.md"


@dataclass
class Skill:
    """A skill definition."""

    name: str
    description: str
    content: str
    location: str


class SkillError(Exception):
    """Base exception for skill errors."""

    pass


class SkillNotFoundError(SkillError):
    """Raised when a skill is not found."""

    pass


class SkillInvalidError(SkillError):
    """Raised when a skill is invalid."""

    pass


class SkillsManager:
    """Manages custom skills/commands."""

    DEFAULT_SKILL_DIRS = [
        ".nanocode/skills",
        ".nanocode/commands",
        ".claude/skills",
        ".opencode/skills",
        ".codex/skills",
        ".gemini/skills",
        ".agents/skills",
        os.path.expanduser("~/.nanocode/skills"),
        os.path.expanduser("~/.claude/skills"),
        os.path.expanduser("~/.config/opencode/skills"),
        os.path.expanduser("~/.codex/skills"),
        os.path.expanduser("~/.gemini/skills"),
        os.path.expanduser("~/.agents/skills"),
    ]
    DEFAULT_SKILL_URLS = [
        "https://raw.githubusercontent.com/daedalus/skills/main/{skill}/SKILL.md",
    ]
    SKILL_FILE_NAME = "SKILL.md"

    def __init__(self, base_dir: str = None, config: dict = None, db_session=None):
        self.base_dir = base_dir or os.getcwd()
        self.config = config or {}
        self.skills: dict[str, Skill] = {}
        self._handlers: dict[str, Callable] = {}
        self._url_cache: dict[str, str] = {}
        self._db_session = db_session

    def discover_skills(self) -> list[Skill]:
        """Discover skills in the configured directories (opencode-inspired)."""
        discovered = []

        # Get base directory and worktree (using base_dir as worktree for simplicity)
        directory = self.base_dir
        worktree = self.base_dir

        # Get skill paths from config
        skill_paths = self.config.get("skills", {}).get("paths", [])

        # Track directories we've already scanned to avoid duplicates
        scanned_dirs = set()

        # Separate DEFAULT_SKILL_DIRS into home paths and relative paths
        import pathlib
        home_dir = str(pathlib.Path.home())
        home_paths = []  # Absolute paths that should be scanned from home
        relative_paths = []  # Relative paths to scan in project dirs

        for skill_dir in self.DEFAULT_SKILL_DIRS:
            expanded = expand_path(skill_dir)
            if os.path.isabs(expanded) and expanded.startswith(home_dir):
                # Absolute path under home directory
                home_paths.append(expanded)
            elif not os.path.isabs(skill_dir):
                # Relative path - add to relative paths list
                relative_paths.append(skill_dir)
            else:
                # Other absolute paths
                home_paths.append(expanded)

        # 1. Scan home directory skill paths
        for ext_path in set(home_paths):
            if os.path.isdir(ext_path) and ext_path not in scanned_dirs:
                scanned_dirs.add(ext_path)
                for root, dirs, files in os.walk(ext_path):
                    if SKILL_FILE_NAME in files:
                        skill_path = os.path.join(root, SKILL_FILE_NAME)
                        try:
                            skill = self._parse_skill_file(skill_path)
                            if skill:
                                discovered.append(skill)
                        except Exception:
                            pass

        # 2. Scan for skills in parent directories up to worktree
        current = directory
        while current != worktree and current != os.path.dirname(current):  # Stop at filesystem root
            for skill_dir in relative_paths:
                ext_path = os.path.join(current, skill_dir)
                if os.path.isdir(ext_path) and ext_path not in scanned_dirs:
                    scanned_dirs.add(ext_path)
                    for root, dirs, files in os.walk(ext_path):
                        if SKILL_FILE_NAME in files:
                            skill_path = os.path.join(root, SKILL_FILE_NAME)
                            try:
                                skill = self._parse_skill_file(skill_path)
                                if skill:
                                    discovered.append(skill)
                            except Exception:
                                pass
            current = os.path.dirname(current)
        
        # 3. Scan relative paths in base directory
        for skill_dir in relative_paths:
            scan_path = os.path.join(directory, skill_dir)
            if os.path.isdir(scan_path) and scan_path not in scanned_dirs:
                scanned_dirs.add(scan_path)
                for root, dirs, files in os.walk(scan_path):
                    if SKILL_FILE_NAME in files:
                        skill_path = os.path.join(root, SKILL_FILE_NAME)
                        try:
                            skill = self._parse_skill_file(skill_path)
                            if skill:
                                discovered.append(skill)
                        except Exception:
                            pass

        # 4. Scan configured skill paths
        for path_item in skill_paths:
            # Expand ~ to home directory
            if path_item.startswith("~/"):
                expanded_path = os.path.join(home_dir, path_item[2:])
            else:
                # Make relative paths absolute based on base directory
                if not os.path.isabs(path_item):
                    expanded_path = os.path.join(directory, path_item)
                else:
                    expanded_path = path_item
            
            if os.path.isdir(expanded_path) and expanded_path not in scanned_dirs:
                scanned_dirs.add(expanded_path)
                for root, dirs, files in os.walk(expanded_path):
                    if SKILL_FILE_NAME in files:
                        skill_path = os.path.join(root, SKILL_FILE_NAME)
                        try:
                            skill = self._parse_skill_file(skill_path)
                            if skill:
                                discovered.append(skill)
                        except Exception:
                            pass

        return discovered

    def _parse_skill_file(self, path: str) -> Skill | None:
        """Parse a skill.md file."""
        try:
            with open(path) as f:
                content = f.read()

            try:
                metadata, body = frontmatter.parse(content)
            except Exception:
                return None

            name = metadata.get("name", "")
            description = metadata.get("description", "")

            if not name:
                name = os.path.basename(os.path.dirname(path))
            if not description:
                # Don't use entire body as description - just use a truncated version
                # Take first 100 chars of body, stripped of newlines
                description = body.replace("\n", " ").strip()[:100] if body else ""

            return Skill(
                name=name,
                description=description,
                content=body,
                location=path,
            )
        except Exception:
            return None

    async def discover_skills_from_urls(self, urls: list[str] = None) -> list[Skill]:
        """Discover skills from URLs with index.json support (opencode-inspired)."""
        urls = urls or self.config.get("skills.urls", [])
        if not urls:
            urls = self.DEFAULT_SKILL_URLS

        discovered = []
        cache_dir = _get_skills_cache_dir()

        for url in urls:
            try:
                # Check if this is an index URL (doesn't contain {skill} placeholder)
                if "{skill}" not in url:
                    # Fetch index.json to get list of skills
                    index_url = url.rstrip("/") + "/index.json"
                    skills_list = await self._fetch_skills_from_index(index_url, cache_dir)
                    for skill_name in skills_list:
                        skill_url = url.rstrip("/") + f"/{skill_name}/{self.SKILL_FILE_NAME}"
                        skill = await self._fetch_skill_from_url(skill_url, cache_dir)
                        if skill:
                            discovered.append(skill)
                else:
                    # Original behavior for templated URLs
                    skill_names = ["sample"] if "{skill}" in url else ["custom"]
                    for skill_name in skill_names:
                        formatted_url = url.format(skill=skill_name)
                        skill = await self._fetch_skill_from_url(formatted_url, cache_dir)
                        if skill:
                            discovered.append(skill)
            except Exception as e:
                logger.warning(f"Failed to fetch skill from {url}: {e}")

        return discovered

    async def _fetch_skills_from_index(
        self, index_url: str, cache_dir: Path = None
    ) -> list[str]:
        """Fetch index.json and return list of skill names."""
        cache_dir = cache_dir or _get_skills_cache_dir()
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(index_url)
                response.raise_for_status()
                data = response.json()
                
                # Extract skill names from index (opencode format)
                skill_names = []
                if isinstance(data, dict) and "skills" in data:
                    for skill in data["skills"]:
                        if isinstance(skill, dict) and "name" in skill:
                            skill_names.append(skill["name"])
                        elif isinstance(skill, str):
                            skill_names.append(skill)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "name" in item:
                            skill_names.append(item["name"])
                        elif isinstance(item, str):
                            skill_names.append(item)
                
                return skill_names
        except Exception as e:
            logger.warning(f"Failed to fetch skills index from {index_url}: {e}")
            return []

    async def _fetch_skill_from_url(
        self, url: str, cache_dir: Path = None
    ) -> Skill | None:
        """Fetch and cache a skill from a URL."""
        cache_dir = cache_dir or _get_skills_cache_dir()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.text
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return None

        cached_path = None
        try:
            metadata, body = frontmatter.parse(content)
        except Exception:
            return None

        name = metadata.get("name", "")
        description = metadata.get("description", "")

        if not name:
            import hashlib

            name = hashlib.md5(url.encode()).hexdigest()[:8]

        skill = Skill(
            name=name,
            description=description or f"Remote skill from {url}",
            content=body,
            location=url,
        )

        os.makedirs(cache_dir, exist_ok=True)
        cached_path = cache_dir / f"{name}.md"
        with open(cached_path, "w") as f:
            f.write(content)

        self._url_cache[name] = str(cached_path)
        logger.info(f"Fetched and cached skill: {name} from {url}")

        return skill

    def get_cached_skill_path(self, name: str) -> str | None:
        """Get path to cached skill file."""
        return self._url_cache.get(name)

    def load_skills(self) -> int:
        """Load all discovered skills."""
        self.skills.clear()

        discovered = self.discover_skills()
        for skill in discovered:
            self.skills[skill.name] = skill
            logger.info(f"Skill available: {skill.name} ({skill.location})")

        # Sync to database if session available
        if self._db_session:
            try:
                import asyncio
                asyncio.ensure_future(self._sync_to_db(discovered))
            except Exception:
                pass

        return len(self.skills)

    async def load_skills_async(self) -> int:
        """Load all discovered skills including from URLs."""
        self.skills.clear()

        discovered = self.discover_skills()
        for skill in discovered:
            self.skills[skill.name] = skill
            logger.info(f"Skill loaded: {skill.name} ({skill.location})")

        try:
            urls = self.config.get("skills.urls", [])
            if urls:
                url_skills = await self.discover_skills_from_urls(urls)
                for skill in url_skills:
                    if skill.name not in self.skills:
                        self.skills[skill.name] = skill
                        logger.info(
                            f"Remote skill loaded: {skill.name} ({skill.location})"
                        )
        except Exception as e:
            logger.warning(f"Failed to load remote skills: {e}")

        # Sync to database if session available
        if self._db_session:
            await self._sync_to_db(list(self.skills.values()))

        return len(self.skills)

    async def _sync_to_db(self, skills: list[Skill]):
        """Sync discovered skills to the database."""
        if not self._db_session:
            return
        try:
            from nanocode.storage.models import Skill as DBSkill
            from sqlalchemy import select

            for skill in skills:
                stmt = select(DBSkill).where(
                    DBSkill.name == skill.name,
                    DBSkill.scope == "user",
                )
                result = await self._db_session.execute(stmt)
                db_skill = result.scalar_one_or_none()

                if not db_skill:
                    from datetime import datetime
                    import uuid
                    db_skill = DBSkill(
                        id=str(uuid.uuid4()),
                        name=skill.name,
                        description=skill.description,
                        content=skill.content,
                        scope="user",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    self._db_session.add(db_skill)
                else:
                    db_skill.content = skill.content
                    db_skill.description = skill.description
                    from datetime import datetime
                    db_skill.updated_at = datetime.now()

            await self._db_session.flush()
        except Exception as e:
            logger.warning(f"Failed to sync skills to DB: {e}")

    def get_skill(self, name: str) -> Skill:
        """Get a skill by name."""
        if name not in self.skills:
            raise SkillNotFoundError(f"Skill '{name}' not found")
        return self.skills[name]

    def list_skills(self, agent_info: Optional["AgentInfo"] = None) -> list[dict[str, str]]:
        """List all available skills, optionally filtered by agent permissions."""
        skills_list = []
        for skill in self.skills.values():
            # Check permissions if agent_info is provided
            if agent_info is not None:
                # Import here to avoid circular imports
                from nanocode.agents import PermissionAction, evaluate_permission
                action = evaluate_permission("skill", skill.name, agent_info.permission)
                if action == PermissionAction.DENY:
                    continue  # Skip this skill if denied
            
            skills_list.append({
                "name": skill.name, 
                "description": skill.description, 
                "location": skill.location
            })
        return skills_list

    def register_handler(self, name: str, handler: Callable):
        """Register a handler function for a skill."""
        self._handlers[name] = handler

    async def execute_skill(
        self,
        name: str,
        args: dict[str, Any] = None,
        context: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """Execute a skill."""
        skill = self.get_skill(name)
        args = args or {}
        context = context or {}

        if name in self._handlers:
            handler = self._handlers[name]
            if asyncio.iscoroutinefunction(handler):
                return await handler(skill, args, context)
            return handler(skill, args, context)

        return {
            "success": True,
            "skill": skill.name,
            "description": skill.description,
            "content": skill.content,
        }

    def create_tools(self, agent) -> list[dict]:
        """Create tool definitions from skills."""
        tools = []

        for name, skill in self.skills.items():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"skill_{name.replace('-', '_')}",
                        "description": skill.description,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "input": {
                                    "type": "string",
                                    "description": "Input to pass to the skill",
                                }
                            },
                            "required": ["input"],
                        },
                    },
                }
            )

        return tools


def create_skills_manager(base_dir: str = None, config: dict = None) -> SkillsManager:
    """Create and initialize a skills manager."""
    manager = SkillsManager(base_dir, config)
    manager.load_skills()
    return manager


async def create_skills_manager_async(
    base_dir: str = None, config: dict = None
) -> SkillsManager:
    """Create and initialize a skills manager with URL support."""
    manager = SkillsManager(base_dir, config)
    await manager.load_skills_async()
    return manager



