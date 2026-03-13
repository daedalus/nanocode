"""Built-in tools for file operations, shell, and more."""

import os
import json
import subprocess
import asyncio
from pathlib import Path
from typing import Optional

from agent_smith.tools import Tool, ToolResult, ToolRegistry


class BashTool(Tool):
    """Execute shell commands."""

    def __init__(self, allowed_commands: list[str] = None):
        super().__init__(
            name="bash",
            description="Execute shell commands in the terminal. Returns command output.",
        )
        self.allowed_commands = allowed_commands or []
        self.blocked_patterns = ["rm -rf /", "dd if=", ":(){:|:&};:", "mkfs"]

    async def execute(self, command: str, workdir: str = None, timeout: int = 60) -> ToolResult:
        """Execute a shell command."""
        for pattern in self.blocked_patterns:
            if pattern in command:
                return ToolResult(success=False, content=None, error=f"Blocked command pattern: {pattern}")

        try:
            work_path = Path(workdir) if workdir else Path.cwd()
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(work_path),
            )
            
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            
            return ToolResult(
                success=result.returncode == 0,
                content=output or "(command completed with no output)",
                metadata={"returncode": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content=None, error="Command timed out")
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class GlobTool(Tool):
    """Find files matching a glob pattern."""

    def __init__(self, root_dir: str = None):
        super().__init__(
            name="glob",
            description="Find files matching a glob pattern (e.g., **/*.py)",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    async def execute(self, pattern: str, path: str = None) -> ToolResult:
        """Find files matching pattern."""
        try:
            search_path = Path(path) if path else self.root_dir
            files = list(search_path.glob(pattern))
            return ToolResult(
                success=True,
                content=[str(f.relative_to(search_path)) for f in files],
                metadata={"count": len(files)},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class GrepTool(Tool):
    """Search file contents."""

    def __init__(self, root_dir: str = None):
        super().__init__(
            name="grep",
            description="Search for patterns in file contents",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    async def execute(self, pattern: str, path: str = None, include: str = None) -> ToolResult:
        """Search for pattern in files."""
        import re
        try:
            search_path = Path(path) if path else self.root_dir
            results = []
            
            if include:
                files = search_path.glob(include)
            else:
                files = [f for f in search_path.rglob("*") if f.is_file()]

            for file_path in files:
                if file_path.is_file():
                    try:
                        content = file_path.read_text(errors="ignore")
                        matches = []
                        for i, line in enumerate(content.splitlines(), 1):
                            if re.search(pattern, line):
                                matches.append(f"{i}: {line}")
                        if matches:
                            results.append({
                                "file": str(file_path.relative_to(search_path)),
                                "matches": matches[:10],
                            })
                    except:
                        continue

            return ToolResult(
                success=True,
                content=results,
                metadata={"files_with_matches": len(results)},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class ReadFileTool(Tool):
    """Read file contents with auto-refresh on modification."""

    def __init__(self, root_dir: str = None, file_tracker=None):
        super().__init__(
            name="read",
            description="Read contents of a file. Use force_refresh=true to bypass cache.",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.file_tracker = file_tracker

    async def execute(self, path: str, limit: int = None, offset: int = None, force_refresh: bool = False) -> ToolResult:
        """Read a file."""
        try:
            file_path = self.root_dir / path
            if not file_path.exists():
                return ToolResult(success=False, content=None, error="File not found")

            full_path = str(file_path.resolve())
            
            if self.file_tracker and not force_refresh:
                content, refreshed = self.file_tracker.get_or_read(full_path)
                was_cached = not refreshed
            else:
                content = file_path.read_text(errors="ignore")
                was_cached = False
                if self.file_tracker:
                    self.file_tracker.set(full_path, content)
            
            lines = content.splitlines()
            if offset:
                lines = lines[offset - 1:]
            if limit:
                lines = lines[:limit]
            
            return ToolResult(
                success=True,
                content="\n".join(lines),
                metadata={
                    "path": str(file_path),
                    "lines": len(lines),
                    "total_lines": len(content.splitlines()),
                    "cached": was_cached,
                },
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class WriteFileTool(Tool):
    """Write content to a file."""

    def __init__(self, root_dir: str = None, file_tracker=None):
        super().__init__(
            name="write",
            description="Write content to a file. Creates parent directories if needed.",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.file_tracker = file_tracker

    async def execute(self, path: str, content: str, mode: str = "w") -> ToolResult:
        """Write to a file."""
        try:
            file_path = self.root_dir / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            
            if self.file_tracker:
                self.file_tracker.invalidate(str(file_path.resolve()))
            
            return ToolResult(
                success=True,
                content=f"Written to {file_path}",
                metadata={"path": str(file_path), "size": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class EditFileTool(Tool):
    """Edit file contents."""

    def __init__(self, root_dir: str = None):
        super().__init__(
            name="edit",
            description="Edit a file by replacing old string with new string",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.file_tracker = None

    async def execute(self, path: str, old: str, new: str) -> ToolResult:
        """Edit a file."""
        try:
            file_path = self.root_dir / path
            if not file_path.exists():
                return ToolResult(success=False, content=None, error="File not found")

            full_path = str(file_path.resolve())
            
            if self.file_tracker and not self.file_tracker.is_modified(full_path):
                cached = self.file_tracker.get(full_path)
                content = cached.content if cached else file_path.read_text()
            else:
                content = file_path.read_text()
            
            if old not in content:
                return ToolResult(success=False, content=None, error="Old string not found in file")

            new_content = content.replace(old, new, 1)
            file_path.write_text(new_content)
            
            if self.file_tracker:
                self.file_tracker.invalidate(full_path)
            
            return ToolResult(
                success=True,
                content=f"Edited {file_path}",
                metadata={"path": str(file_path)},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class ListDirTool(Tool):
    """List directory contents."""

    def __init__(self, root_dir: str = None):
        super().__init__(
            name="ls",
            description="List directory contents",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    async def execute(self, path: str = None, show_hidden: bool = False) -> ToolResult:
        """List directory."""
        try:
            dir_path = Path(path) if path else self.root_dir
            if not dir_path.exists():
                return ToolResult(success=False, content=None, error="Directory not found")

            entries = []
            for entry in dir_path.iterdir():
                if not show_hidden and entry.name.startswith("."):
                    continue
                entry_type = "dir" if entry.is_dir() else "file"
                entries.append(f"{entry.name}/" if entry_type == "dir" else entry.name)

            return ToolResult(
                success=True,
                content="\n".join(sorted(entries)),
                metadata={"path": str(dir_path), "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class WebFetchTool(Tool):
    """Fetch web content."""

    def __init__(self):
        super().__init__(
            name="webfetch",
            description="Fetch content from a URL",
        )

    async def execute(self, url: str, format: str = "text") -> ToolResult:
        """Fetch URL content."""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30.0)
                response.raise_for_status()
                
                if format == "text":
                    content = response.text[:50000]
                elif format == "html":
                    content = response.text
                else:
                    content = response.text
                
                return ToolResult(
                    success=True,
                    content=content,
                    metadata={"url": url, "status": response.status_code},
                )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class WebSearchTool(Tool):
    """Search the web."""

    def __init__(self):
        super().__init__(
            name="websearch",
            description="Search the web for information",
        )

    async def execute(self, query: str, num_results: int = 5) -> ToolResult:
        """Search the web."""
        try:
            import httpx
            headers = {"Accept": "application/json"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.exa.ai/search",
                    params={"query": query, "num_results": num_results},
                    headers=headers,
                    timeout=30.0,
                )
                data = response.json()
                
                results = []
                for r in data.get("results", []):
                    results.append({
                        "title": r.get("title"),
                        "url": r.get("url"),
                        "snippet": r.get("snippet", "")[:200],
                    })
                
                return ToolResult(
                    success=True,
                    content=results,
                    metadata={"query": query, "count": len(results)},
                )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class TodoTool(Tool):
    """Manage task list."""

    def __init__(self):
        super().__init__(
            name="todo",
            description="Manage a todo list for tracking tasks",
        )
        self.tasks = {}

    async def execute(self, action: str, task: str = None, task_id: str = None) -> ToolResult:
        """Manage todos."""
        if action == "add":
            import uuid
            task_id = str(uuid.uuid4())[:8]
            self.tasks[task_id] = {"content": task, "status": "pending"}
            return ToolResult(success=True, content=f"Added task {task_id}: {task}")
        elif action == "list":
            return ToolResult(success=True, content=self.tasks)
        elif action == "complete" and task_id:
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = "completed"
                return ToolResult(success=True, content=f"Completed task {task_id}")
            return ToolResult(success=False, content=None, error=f"Task {task_id} not found")
        elif action == "delete" and task_id:
            self.tasks.pop(task_id, None)
            return ToolResult(success=True, content=f"Deleted task {task_id}")
        else:
            return ToolResult(success=False, content=None, error="Invalid action")


def create_builtin_tools(config: dict = None, file_tracker=None) -> list[Tool]:
    """Create all built-in tools."""
    from agent_smith.tools.builtin.exa_search import ExaSearchTool, ExaFetchTool
    from agent_smith.tools.builtin.free_search import FreeExaSearchTool, OpenWebSearchTool
    
    exa_config = config.get("exa", {}) if config else {}
    
    tools = [
        BashTool(),
        GlobTool(),
        GrepTool(),
        ReadFileTool(file_tracker=file_tracker),
        WriteFileTool(file_tracker=file_tracker),
        EditFileTool(),
        ListDirTool(),
        WebFetchTool(),
        WebSearchTool(),
        # Paid Exa tools (requires API key)
        ExaSearchTool(
            api_key=exa_config.get("api_key"),
            num_results=exa_config.get("num_results", 10),
        ),
        ExaFetchTool(api_key=exa_config.get("api_key")),
        # Free search tools (no API key required)
        FreeExaSearchTool(),
        OpenWebSearchTool(),
        TodoTool(),
    ]
    return tools


def register_builtin_tools(registry: ToolRegistry, config: dict = None, file_tracker=None):
    """Register all built-in tools."""
    for tool in create_builtin_tools(config, file_tracker):
        registry.register(tool)
    
    try:
        from agent_smith.skills import create_skills_manager
        from agent_smith.tools.builtin.skill import register_skill_tools
        
        skills_manager = create_skills_manager()
        register_skill_tools(registry, skills_manager)
    except ImportError:
        pass
    
    try:
        from agent_smith.snapshot import create_snapshot_manager
        from agent_smith.tools.builtin.snapshot import register_snapshot_tools
        
        snapshot_manager = create_snapshot_manager()
        register_snapshot_tools(registry, snapshot_manager)
    except ImportError:
        pass
