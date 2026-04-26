"""Built-in tools for file operations, shell, and more."""

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from nanocode.context import TokenCounter
from nanocode.flock import DEFAULT_STALE_MS, Flock
from nanocode.todo_service import get_todo_service
from nanocode.tools import Tool, ToolRegistry, ToolResult

if TYPE_CHECKING:
    from nanocode.flock import FlockLease


def atomic_write(file_path: Path, content: str) -> None:
    """Write content to a file atomically using temp file + rename."""
    file_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp"
    )
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        os.rename(temp_path, str(file_path))
    except Exception:
        os.close(fd)
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def atomic_read(file_path: Path) -> str:
    """Read file content atomically using copy to temp file."""
    import shutil

    temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp")
    try:
        os.close(temp_fd)

        with open(file_path, "rb") as src:
            with open(temp_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

        with open(temp_path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


async def flock_read(
    file_path: Path,
    stale_ms: int = DEFAULT_STALE_MS,
) -> tuple[str, "FlockLease"]:
    """Read a file with flock protection.

    Returns (content, lease) - must release lease after read.
    Handles non-existing files (returns empty string).
    """
    fl = Flock(stale_ms=stale_ms)
    key = f"file-read:{file_path}"
    lease = await fl.acquire(key)
    content = ""
    if file_path.exists():
        content = file_path.read_text(errors="ignore")
    return content, lease


async def flock_write(
    file_path: Path,
    content: str,
    stale_ms: int = DEFAULT_STALE_MS,
) -> "FlockLease":
    """Write a file with flock protection.

    Returns lease - must release lease after write.
    Creates parent directories if needed.
    """
    fl = Flock(stale_ms=stale_ms)
    key = f"file-write:{file_path}"
    lease = await fl.acquire(key)
    if file_path.parent.exists() or file_path.parent == Path("."):
        file_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(file_path, content)
    return lease


async def flock_read_write(
    file_path: Path,
    transform: callable,
    stale_ms: int = DEFAULT_STALE_MS,
) -> None:
    """Read, transform, and write a file under flock protection.

    This is a convenience wrapper that handles read-before-write pattern
    similar to opencode's Flock.withLock pattern.
    Creates parent directories if needed.
    """
    fl = Flock(stale_ms=stale_ms)
    key = f"file:{file_path}"

    async with fl.with_lock(key) as lease:
        content = ""
        if file_path.exists():
            content = file_path.read_text(errors="ignore")
        new_content = transform(content)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(file_path, new_content)


class BashTool(Tool):
    """Execute shell commands."""

    def __init__(self, allowed_commands: list[str] = None):
        super().__init__(
            name="bash",
            description="Execute shell commands in the terminal. Returns command output. Use pty=true for interactive commands.",
        )
        self.allowed_commands = allowed_commands or []
        self.blocked_patterns = ["rm -rf /", "dd if=", ":(){:|:&};:", "mkfs"]
        self.pty_session: str | None = None
        self.parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "workdir": {"type": "string", "description": "Working directory"},
                "timeout": {
                    "type": "integer",
                    "default": 60,
                    "description": "Timeout in seconds",
                },
                "pty": {
                    "type": "boolean",
                    "default": False,
                    "description": "Use PTY for interactive commands",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self, command: str, workdir: str = None, timeout: int = 60, pty: bool = False
    ) -> ToolResult:
        """Execute a shell command."""
        import logging

        logger = logging.getLogger("nanocode.bash")
        logger.debug(f"Executing: {command[:100]}")

        for pattern in self.blocked_patterns:
            if pattern in command:
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Blocked command pattern: {pattern}",
                )

        logger.debug(f"BashTool: running subprocess for '{command[:50]}...'")
        if pty:
            return await self._execute_pty(command, workdir)

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

    async def _execute_pty(self, command: str, workdir: str = None) -> ToolResult:
        """Execute command in a PTY session."""
        from nanocode.pty import PtyManager

        session_id = self.pty_session
        if not session_id or PtyManager.get(session_id) is None:
            info = await PtyManager.create(cwd=workdir)
            session_id = info.id
            self.pty_session = session_id

        await PtyManager.write(session_id, command + "\n")

        import time

        start = time.time()
        output = ""

        while time.time() - start < 60:
            await asyncio.sleep(0.1)
            data = PtyManager.read_buffer(session_id)
            if data and len(data) > len(output):
                output = data
                if "$ " in output or "# " in output:
                    break

        return ToolResult(
            success=True,
            content=output,
            metadata={"session_id": session_id},
        )


class BashSessionManager:
    """Manages persistent bash sessions with state tracking."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def create(self, session_id: str, cwd: str = None, env: dict = None) -> None:
        self._sessions[session_id] = {
            "cwd": cwd or os.getcwd(),
            "env": dict(env) if env else dict(os.environ),
            "created_at": asyncio.get_event_loop().time(),
        }

    def get(self, session_id: str) -> dict:
        return self._sessions.get(session_id)

    def update_cwd(self, session_id: str, cwd: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["cwd"] = cwd

    def update_env(self, session_id: str, key: str, value: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["env"][key] = value

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list(self) -> list[dict]:
        return [{"id": sid, **info} for sid, info in self._sessions.items()]


_bash_session_manager = BashSessionManager()


class BashSessionTool(Tool):
    """Persistent bash session handler with environment and working directory tracking."""

    def __init__(self):
        super().__init__(
            name="bash_session",
            description="Manage persistent bash sessions with environment variable and working directory tracking",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action: create, run, get, set_env, list, delete",
                    "enum": ["create", "run", "get", "set_env", "list", "delete"],
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (for run, get, set_env, delete)",
                },
                "command": {
                    "type": "string",
                    "description": "Command to run (for action=run)",
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory (for action=create)",
                },
                "env": {
                    "type": "object",
                    "description": "Environment variables (for action=create or set_env)",
                },
                "key": {
                    "type": "string",
                    "description": "Environment variable key (for action=set_env)",
                },
                "value": {
                    "type": "string",
                    "description": "Environment variable value (for action=set_env)",
                },
                "timeout": {
                    "type": "integer",
                    "default": 60,
                    "description": "Timeout in seconds",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        session_id: str = None,
        command: str = None,
        workdir: str = None,
        env: dict = None,
        key: str = None,
        value: str = None,
        timeout: int = 60,
    ) -> ToolResult:
        """Handle bash session actions."""
        try:
            if action == "create":
                import uuid

                new_session_id = session_id or str(uuid.uuid4())[:8]
                _bash_session_manager.create(new_session_id, workdir, env)
                session_info = _bash_session_manager.get(new_session_id)
                return ToolResult(
                    success=True,
                    content=f"Created bash session: {new_session_id}",
                    metadata={
                        "session_id": new_session_id,
                        "cwd": session_info["cwd"],
                        "env": session_info["env"],
                    },
                )

            elif action == "run":
                if not session_id:
                    return ToolResult(
                        success=False, content=None, error="session_id required for run"
                    )
                session = _bash_session_manager.get(session_id)
                if not session:
                    return ToolResult(
                        success=False,
                        content=None,
                        error=f"Session {session_id} not found",
                    )

                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=session["cwd"],
                    env=session["env"],
                )

                if "cd " in command:
                    new_cwd = (
                        command.replace("cd", "")
                        .strip()
                        .split(";")[0]
                        .split("||")[0]
                        .split("&&")[0]
                    )
                    if new_cwd and not new_cwd.startswith("-"):
                        try:
                            resolved_cwd = Path(session["cwd"]) / new_cwd
                            if resolved_cwd.is_dir():
                                _bash_session_manager.update_cwd(
                                    session_id, str(resolved_cwd.resolve())
                                )
                        except Exception:
                            pass

                output = result.stdout
                if result.stderr:
                    output += f"\nSTDERR: {result.stderr}"

                return ToolResult(
                    success=result.returncode == 0,
                    content=output or "(command completed with no output)",
                    metadata={
                        "returncode": result.returncode,
                        "cwd": _bash_session_manager.get(session_id)["cwd"],
                    },
                )

            elif action == "get":
                if not session_id:
                    return ToolResult(
                        success=False, content=None, error="session_id required for get"
                    )
                session = _bash_session_manager.get(session_id)
                if not session:
                    return ToolResult(
                        success=False,
                        content=None,
                        error=f"Session {session_id} not found",
                    )
                return ToolResult(
                    success=True, content=session, metadata={"session_id": session_id}
                )

            elif action == "set_env":
                if not session_id or not key:
                    return ToolResult(
                        success=False,
                        content=None,
                        error="session_id and key required for set_env",
                    )
                session = _bash_session_manager.get(session_id)
                if not session:
                    return ToolResult(
                        success=False,
                        content=None,
                        error=f"Session {session_id} not found",
                    )
                _bash_session_manager.update_env(session_id, key, value or "")
                return ToolResult(
                    success=True,
                    content=f"Set {key}={value}",
                    metadata={
                        "session_id": session_id,
                        "env": _bash_session_manager.get(session_id)["env"],
                    },
                )

            elif action == "list":
                sessions = _bash_session_manager.list()
                return ToolResult(
                    success=True, content=sessions, metadata={"count": len(sessions)}
                )

            elif action == "delete":
                if not session_id:
                    return ToolResult(
                        success=False,
                        content=None,
                        error="session_id required for delete",
                    )
                _bash_session_manager.remove(session_id)
                return ToolResult(
                    success=True, content=f"Deleted session: {session_id}"
                )

            else:
                return ToolResult(
                    success=False, content=None, error=f"Unknown action: {action}"
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
        self.parameters = {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., **/*.py, *.txt)",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (optional)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, path: str = None) -> ToolResult:
        """Find files matching pattern."""
        try:
            search_path = Path(path) if path else self.root_dir

            resolved_pattern = pattern
            if os.path.isabs(pattern):
                try:
                    pattern_path = Path(pattern)
                    resolved_pattern = str(pattern_path.relative_to(search_path))
                except ValueError:
                    pass

            files = list(search_path.glob(resolved_pattern))
            file_list = [str(f.relative_to(search_path)) for f in files]
            return ToolResult(
                success=True,
                content="\n".join(file_list) if file_list else "",
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
        self.parameters = {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (optional)",
                },
                "include": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., *.py)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self, pattern: str, path: str = None, include: str = None
    ) -> ToolResult:
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
                            results.append(
                                {
                                    "file": str(file_path.relative_to(search_path)),
                                    "matches": matches,
                                }
                            )
                    except Exception:
                        continue

            return ToolResult(
                success=True,
                content=results,
                metadata={"files_with_matches": len(results)},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class SedTool(Tool):
    """Stream editor for performing text transformations."""

    def __init__(self, root_dir: str = None):
        super().__init__(
            name="sed",
            description="Perform text substitution on files (like sed command)",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    async def execute(
        self,
        path: str,
        search: str,
        replace: str,
        global_flag: bool = False,
    ) -> ToolResult:
        """Perform sed-like substitution on a file."""
        try:
            file_path = self.root_dir / path
            if not file_path.exists():
                return ToolResult(success=False, content=None, error="File not found")

            content = file_path.read_text(errors="ignore")

            if global_flag:
                new_content = content.replace(search, replace)
            else:
                new_content = content.replace(search, replace, 1)

            if content == new_content:
                return ToolResult(
                    success=False,
                    content=None,
                    error="Pattern not found in file",
                )

            file_path.write_text(new_content)

            count = (
                content.count(search)
                if global_flag
                else (1 if search in content else 0)
            )
            return ToolResult(
                success=True,
                content=f"Replaced {count} occurrence(s) in {file_path}",
                metadata={"path": str(file_path), "count": count},
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class DiffTool(Tool):
    """Show differences between two files."""

    def __init__(self, root_dir: str = None):
        super().__init__(
            name="diff",
            description="Show differences between two files or a file and a snapshot",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    async def execute(
        self,
        path1: str,
        path2: str = None,
        original_content: str = None,
    ) -> ToolResult:
        """Show diff between files."""
        import difflib

        try:
            file1 = self.root_dir / path1

            if not file1.exists():
                return ToolResult(
                    success=False, content=None, error=f"File not found: {path1}"
                )

            content1 = file1.read_text(errors="ignore")
            lines1 = content1.splitlines()

            file2_path = None
            if path2:
                file2 = self.root_dir / path2
                if not file2.exists():
                    return ToolResult(
                        success=False, content=None, error=f"File not found: {path2}"
                    )
                content2 = file2.read_text(errors="ignore")
                lines2 = content2.splitlines()
                label1 = path1
                label2 = path2
                file2_path = str(file2)
            elif original_content is not None:
                lines2 = original_content.splitlines()
                label1 = path1
                label2 = "(original)"
            else:
                return ToolResult(
                    success=False,
                    content=None,
                    error="Either path2 or original_content must be provided",
                )

            diff = difflib.unified_diff(
                lines2,
                lines1,
                fromfile=label2,
                tofile=label1,
                lineterm="",
            )
            diff_lines = list(diff)

            if not diff_lines:
                return ToolResult(
                    success=True,
                    content="No differences",
                    metadata={"files": (str(file1), file2_path)},
                )

            return ToolResult(
                success=True,
                content="\n".join(diff_lines),
                metadata={
                    "files": (str(file1), file2_path),
                    "added": sum(1 for line in diff_lines if line.startswith("+")),
                    "removed": sum(1 for line in diff_lines if line.startswith("-")),
                },
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class ReadFileTool(Tool):
    """Read file contents."""

    def __init__(self, root_dir: str = None, read_tracker=None, write_unlock_tracker=None):
        super().__init__(
            name="read",
            description="Read file content. ALWAYS reads fresh content. UNLOCKS file for writing on first read. After write, must READ again.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to read (required)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (1-indexed, optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of lines to read (optional)",
                    },
                },
                "required": ["path"],
            },
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self._read_tracker: set = read_tracker if isinstance(read_tracker, set) else set()
        self._write_unlock: set = write_unlock_tracker if isinstance(write_unlock_tracker, set) else set()

    async def execute(
        self,
        path: str,
        limit: int = None,
        offset: int = None,
    ) -> ToolResult:
        """Read a file. ALWAYS reads fresh content."""
        try:
            file_path = self.root_dir / path
            resolved = str(file_path.resolve())

            self._read_tracker.add(resolved)
            self._write_unlock.add(resolved)

            if not file_path.exists():
                parent_dir = file_path.parent
                if not parent_dir.exists():
                    try:
                        parent_dir.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        return ToolResult(success=False, content=None, error="Cannot create parent directory")

                return ToolResult(
                    success=True,
                    content="",
                    metadata={
                        "path": str(file_path),
                        "lines": 0,
                        "total_lines": 0,
                        "bytes": 0,
                        "tokens_estimate": 0,
                        "new_file": True,
                    },
)

            content = file_path.read_text(errors="ignore")

            lines = content.splitlines()
            total_lines = len(lines)
            if offset:
                lines = lines[offset - 1 :]
            if limit:
                lines = lines[:limit]

            text = "\n".join(lines)
            bytes_val = len(text.encode("utf-8"))
            tokens_est = max(1, bytes_val // 4)

            return ToolResult(
                success=True,
                content=text,
                metadata={
                    "path": str(file_path),
                    "lines": len(lines),
                    "total_lines": total_lines,
                    "bytes": bytes_val,
                    "tokens_estimate": tokens_est,
                },
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class FstatTool(Tool):
    """Get file statistics before reading - must be called first."""

    def __init__(self, root_dir: str = None):
        super().__init__(
            name="fstat",
            description="Get file stats (lines, bytes, tokens) BEFORE reading. MUST call this first to decide reading strategy. Lightweight - doesn't read full file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to the file"},
                },
                "required": ["path"],
            },
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    async def execute(self, path: str) -> ToolResult:
        """Get file stats - lightweight without reading full content."""
        try:
            file_path = self.root_dir / path
            if not file_path.exists():
                return ToolResult(success=False, content=None, error="File not found")

            # Get file size without reading full content
            file_size = file_path.stat().st_size
            bytes_val = file_size

            # Count lines from file object (more efficient)
            with open(file_path, "rb") as f:
                line_count = sum(1 for _ in f) if file_size < 1024 * 1024 else None

            if line_count is None:
                # For big files, estimate from size
                line_count = max(1, file_size // 80)

            total_tokens = max(1, bytes_val // 4)

            return ToolResult(
                success=True,
                content=f"lines={line_count}, bytes={bytes_val}, tokens~{total_tokens}",
                metadata={
                    "total_lines": line_count,
                    "bytes": bytes_val,
                    "tokens": total_tokens,
                },
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class WriteFileTool(Tool):
    """Write content to a file."""

    def __init__(self, root_dir: str = None, read_tracker=None, write_unlock_tracker=None):
        super().__init__(
            name="write",
            description="Write to a file. File must have been READ first. After write, must READ again before next write.",
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self._read_tracker: set = read_tracker if isinstance(read_tracker, set) else set()
        self._write_unlock: set = write_unlock_tracker if isinstance(write_unlock_tracker, set) else set()

    async def execute(
        self, path: str = None, content: str = "", filePath: str = None, mode: str = "w"
    ) -> ToolResult:
        """Write to a file atomically."""
        path = path or filePath
        try:
            file_path = self.root_dir / path
            resolved = str(file_path.resolve())

            if resolved not in self._read_tracker:
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"File not read yet. Use read tool first: {path}",
                )

            if resolved not in self._write_unlock:
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"File not unlocked for write. Use read tool first: {path}",
                )

            atomic_write(file_path, content)
            self._write_unlock.discard(resolved)

            lines = content.split("\n")
            preview = "\n".join(lines[:20])
            if len(lines) > 20:
                preview += f"\n... ({len(lines) - 20} more lines)"

            return ToolResult(
                success=True,
                content=f"Written to {file_path}:\n{preview}",
                metadata={
                    "path": str(file_path),
                    "bytes": len(content.encode("utf-8")),
                    "content": content,
                },
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
        """Edit a file atomically."""
        try:
            file_path = self.root_dir / path
            if not file_path.exists():
                return ToolResult(success=False, content=None, error="File not found")

            full_path = str(file_path.resolve())

            if self.file_tracker and not self.file_tracker.is_modified(full_path):
                cached = self.file_tracker.get(full_path)
                content = cached.content if cached else atomic_read(file_path)
            else:
                content = atomic_read(file_path)

            if old not in content:
                return ToolResult(
                    success=False, content=None, error="Old string not found in file"
                )

            new_content = content.replace(old, new, 1)
            atomic_write(file_path, new_content)

            if self.file_tracker:
                self.file_tracker.invalidate(full_path)

            old_bytes = len(old.encode("utf-8"))
            new_bytes = len(new.encode("utf-8"))

            preview = "\n".join(new_content.split("\n")[:20])
            if len(new_content.split("\n")) > 20:
                preview += f"\n... ({len(new_content.split('\\n')) - 20} more lines)"

            return ToolResult(
                success=True,
                content=f"Edited {file_path}:\n{preview}",
                metadata={
                    "path": str(file_path),
                    "bytes_read": old_bytes,
                    "bytes_written": new_bytes,
                    "content": new_content,
                },
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

    async def execute(
        self, path: str = None, url: str = None, format: str = "text"
    ) -> ToolResult:
        """Fetch URL content."""
        target_url = url or path

        from nanocode.tools import logger

        logger.debug(f"WebFetchTool.execute: path={path!r}, url={url!r}, target_url={target_url!r}")

        if not target_url:
            return ToolResult(success=False, content=None, error="URL is required")

        # Ensure URL has protocol
        if not target_url.startswith(("http://", "https://")):
            target_url = "https://" + target_url

        logger.debug(f"WebFetchTool: fetching {target_url}")

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(target_url, timeout=30.0)
                logger.debug(f"WebFetchTool: got response status={response.status_code}")
                response.raise_for_status()

                if format == "text":
                    content = response.text
                elif format == "html":
                    content = response.text
                else:
                    content = response.text

                return ToolResult(
                    success=True,
                    content=content,
                    metadata={"url": target_url, "status": response.status_code},
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
                    results.append(
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "snippet": r.get("snippet", ""),
                        }
                    )

                return ToolResult(
                    success=True,
                    content=results,
                    metadata={"query": query, "count": len(results)},
                )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class TodoTool(Tool):
    """Manage task list - supports adding/updating multiple todos at once."""

    def __init__(self, todo_service=None):
        super().__init__(
            name="todo",
            description="Manage a todo list for tracking tasks",
        )
        self.todo_service = todo_service

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "todo",
                "description": "Manage a todo list for tracking tasks. Use this to track your progress on multi-step tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["read", "write"],
                            "description": "Action: 'read' to query current todos, 'write' to update todos",
                        },
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "Brief description of the task",
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": [
                                            "pending",
                                            "in_progress",
                                            "completed",
                                            "cancelled",
                                        ],
                                        "description": "Current status",
                                    },
                                    "priority": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                        "description": "Priority level",
                                    },
                                },
                                "required": ["content", "status", "priority"],
                            },
                            "description": "The updated todo list (for 'write' action)",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, action: str = "read", todos: list = None) -> ToolResult:
        """Manage todos - read or write the entire list."""
        if self.todo_service is None:
            from nanocode.todo_service import get_todo_service

            self.todo_service = get_todo_service()

        if action == "read":
            from nanocode.core import get_current_session_id

            session_id = get_current_session_id() or "default"
            items = self.todo_service.get_todos(session_id)
            todos_list = [
                {"content": t.content, "status": t.status, "priority": t.priority}
                for t in items
            ]
            stats = self.todo_service.get_stats(session_id)
            return ToolResult(
                success=True,
                content=f"{stats['pending']} pending, {stats['in_progress']} in progress, {stats['completed']} done",
                metadata={"todos": todos_list, "stats": stats},
            )
        elif action == "write" and todos is not None:
            from nanocode.core import get_current_session_id

            session_id = get_current_session_id() or "default"
            self.todo_service.update_todos(session_id, todos)
            pending = sum(1 for t in todos if t.get("status") == "pending")
            completed = sum(1 for t in todos if t.get("status") == "completed")
            return ToolResult(
                success=True,
                content=f"Updated todo list: {pending} pending, {completed} done",
                metadata={"todos": todos},
            )
        else:
            return ToolResult(
                success=False,
                content="Invalid action",
                error="Invalid action. Use 'read' or 'write'.",
            )


class LSPTool(Tool):
    """LSP operations tool."""

    def __init__(self, lsp_manager=None):
        super().__init__(
            name="lsp",
            description="Perform LSP operations like go-to-definition, find-references, hover, and more",
        )
        self.lsp_manager = lsp_manager

    async def execute(
        self,
        operation: str,
        file_path: str,
        line: int = 1,
        character: int = 1,
        query: str = None,
    ) -> ToolResult:
        """Perform LSP operation."""
        if self.lsp_manager is None:
            return ToolResult(
                success=False, content=None, error="LSP manager not configured"
            )

        try:
            from nanocode.lsp import file_uri_to_path, path_to_file_uri

            file_path = str(Path(file_path).resolve())
            uri = path_to_file_uri(file_path)

            client = self.lsp_manager.get_server_for_file(file_path)
            if client is None:
                client = await self.lsp_manager.auto_start_for_file(file_path)

            if client is None:
                return ToolResult(
                    success=False,
                    content=None,
                    error="No LSP server available for this file type",
                )

            if isinstance(client, tuple):
                client = client[0]

            if operation == "definition":
                result = await client.text_document__definition(
                    uri, line - 1, character - 1
                )
                if not result:
                    return ToolResult(success=True, content="No definition found")
                locations = []
                for loc in result:
                    locations.append(
                        {
                            "file": file_uri_to_path(loc.uri),
                            "range": loc.range,
                        }
                    )
                return ToolResult(
                    success=True, content=locations, metadata={"count": len(locations)}
                )

            elif operation == "references":
                result = await client.text_document__references(
                    uri, line - 1, character - 1
                )
                if not result:
                    return ToolResult(success=True, content="No references found")
                locations = []
                for loc in result:
                    locations.append(
                        {
                            "file": file_uri_to_path(loc.uri),
                            "range": loc.range,
                        }
                    )
                return ToolResult(
                    success=True, content=locations, metadata={"count": len(locations)}
                )

            elif operation == "hover":
                result = await client.text_document__hover(uri, line - 1, character - 1)
                content = result.contents
                if isinstance(content, dict):
                    content = content.get("value", str(content))
                elif isinstance(content, list):
                    content = "\n".join(str(c) for c in content)
                return ToolResult(
                    success=True, content=content, metadata={"range": result.range}
                )

            elif operation == "completion":
                result = await client.text_document__completion(
                    uri, line - 1, character - 1
                )
                if not result:
                    return ToolResult(success=True, content=[])
                items = []
                for item in result:
                    items.append(
                        {
                            "label": item.label,
                            "kind": item.kind,
                            "detail": item.detail,
                        }
                    )
                return ToolResult(
                    success=True, content=items, metadata={"count": len(items)}
                )

            elif operation == "symbols":
                result = await client.text_document__symbol(uri)
                if not result:
                    return ToolResult(success=True, content="No symbols found")
                symbols = []
                for sym in result:
                    symbols.append(
                        {
                            "name": sym.name,
                            "kind": sym.kind,
                            "location": {
                                "file": file_uri_to_path(sym.location.uri),
                                "range": sym.location.range,
                            },
                        }
                    )
                return ToolResult(
                    success=True, content=symbols, metadata={"count": len(symbols)}
                )

            elif operation == "workspace_symbol":
                if not query:
                    return ToolResult(
                        success=False,
                        content=None,
                        error="query is required for workspace_symbol",
                    )
                result = await client.workspace__symbol(query)
                if not result:
                    return ToolResult(success=True, content="No symbols found")
                symbols = []
                for sym in result:
                    symbols.append(
                        {
                            "name": sym.name,
                            "kind": sym.kind,
                            "location": {
                                "file": file_uri_to_path(sym.location.uri),
                                "range": sym.location.range,
                            },
                        }
                    )
                return ToolResult(
                    success=True, content=symbols, metadata={"count": len(symbols)}
                )

            elif operation == "implementation":
                result = await client.text_document__implementation(
                    uri, line - 1, character - 1
                )
                if not result:
                    return ToolResult(success=True, content="No implementation found")
                locations = []
                for loc in result:
                    locations.append(
                        {
                            "file": file_uri_to_path(loc.uri),
                            "range": loc.range,
                        }
                    )
                return ToolResult(
                    success=True, content=locations, metadata={"count": len(locations)}
                )

            elif operation == "diagnostics":
                result = await client.text_document__diagnostics(uri)
                if not result:
                    return ToolResult(success=True, content="No diagnostics")
                diags = []
                for diag in result:
                    diags.append(
                        {
                            "message": diag.message,
                            "severity": diag.severity,
                            "range": diag.range,
                            "code": diag.code,
                        }
                    )
                return ToolResult(
                    success=True, content=diags, metadata={"count": len(diags)}
                )

            else:
                return ToolResult(
                    success=False, content=None, error=f"Unknown operation: {operation}"
                )

        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class PtyCreateTool(Tool):
    """Create a new PTY session."""

    def __init__(self):
        super().__init__(
            name="pty_create",
            description="Create a new PTY (pseudo-terminal) session",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run (default: system shell)",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command arguments",
                },
                "cwd": {"type": "string", "description": "Working directory"},
                "title": {"type": "string", "description": "Terminal title"},
                "rows": {
                    "type": "integer",
                    "default": 24,
                    "description": "Terminal rows",
                },
                "cols": {
                    "type": "integer",
                    "default": 80,
                    "description": "Terminal columns",
                },
            },
        }

    async def execute(
        self,
        command: str = None,
        args: list = None,
        cwd: str = None,
        title: str = None,
        rows: int = 24,
        cols: int = 80,
    ) -> ToolResult:
        """Create a new PTY session."""
        try:
            from nanocode.pty import PtyManager

            info = await PtyManager.create(
                command=command,
                args=args,
                cwd=cwd,
                title=title,
            )

            await PtyManager.resize(info.id, cols, rows)

            return ToolResult(
                success=True,
                content={
                    "id": info.id,
                    "title": info.title,
                    "command": info.command,
                    "cwd": info.cwd,
                    "pid": info.pid,
                    "status": info.status.value,
                },
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class PtyListTool(Tool):
    """List all PTY sessions."""

    def __init__(self):
        super().__init__(
            name="pty_list",
            description="List all active PTY sessions",
        )

    async def execute(self) -> ToolResult:
        """List all PTY sessions."""
        try:
            from nanocode.pty import PtyManager

            sessions = PtyManager.list()
            return ToolResult(
                success=True,
                content=[
                    {
                        "id": s.id,
                        "title": s.title,
                        "status": s.status.value,
                        "pid": s.pid,
                    }
                    for s in sessions
                ],
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class PtyWriteTool(Tool):
    """Write to a PTY session."""

    def __init__(self):
        super().__init__(
            name="pty_write",
            description="Write input to a PTY session",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "PTY session ID"},
                "data": {
                    "type": "string",
                    "description": "Data to write to the terminal",
                },
            },
            "required": ["id", "data"],
        }

    async def execute(self, id: str, data: str) -> ToolResult:
        """Write to a PTY session."""
        try:
            from nanocode.pty import PtyManager

            await PtyManager.write(id, data)
            return ToolResult(success=True, content="Data written")
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class PtyResizeTool(Tool):
    """Resize a PTY terminal."""

    def __init__(self):
        super().__init__(
            name="pty_resize",
            description="Resize a PTY terminal",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "PTY session ID"},
                "rows": {"type": "integer", "description": "Number of rows"},
                "cols": {"type": "integer", "description": "Number of columns"},
            },
            "required": ["id", "rows", "cols"],
        }

    async def execute(self, id: str, rows: int, cols: int) -> ToolResult:
        """Resize a PTY terminal."""
        try:
            from nanocode.pty import PtyManager

            await PtyManager.resize(id, cols, rows)
            return ToolResult(success=True, content=f"Resized to {cols}x{rows}")
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class PtyReadTool(Tool):
    """Read output from a PTY session."""

    def __init__(self):
        super().__init__(
            name="pty_read",
            description="Read terminal output from a PTY session",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "PTY session ID"},
                "cursor": {
                    "type": "integer",
                    "description": "Cursor position to read from",
                },
                "length": {"type": "integer", "description": "Maximum length to read"},
            },
            "required": ["id"],
        }

    async def execute(self, id: str, cursor: int = 0, length: int = None) -> ToolResult:
        """Read from a PTY session."""
        try:
            from nanocode.pty import PtyManager

            data = PtyManager.read_buffer(id, cursor, length)
            info = PtyManager.get(id)

            return ToolResult(
                success=True,
                content=data,
                metadata={
                    "cursor": info.cursor if info else cursor,
                    "status": info.status.value if info else "unknown",
                },
            )
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class PtyRemoveTool(Tool):
    """Remove a PTY session."""

    def __init__(self):
        super().__init__(
            name="pty_remove",
            description="Kill a PTY session",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "PTY session ID"},
            },
            "required": ["id"],
        }

    async def execute(self, id: str) -> ToolResult:
        """Remove a PTY session."""
        try:
            from nanocode.pty import PtyManager

            manager = PtyManager.get_instance()
            await manager.kill_session(id)
            return ToolResult(success=True, content=f"Killed PTY session {id}")
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class BatchTool(Tool):
    """Execute multiple tools in parallel."""

    def __init__(self, tool_executor=None):
        super().__init__(
            name="batch",
            description="Execute multiple tool calls in parallel. Maximum 25 tools per batch.",
        )
        self.tool_executor = tool_executor
        self.parameters = {
            "type": "object",
            "properties": {
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "description": "The name of the tool to execute",
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Parameters for the tool",
                            },
                        },
                        "required": ["tool", "parameters"],
                    },
                    "description": "Array of tool calls to execute in parallel",
                },
            },
            "required": ["tool_calls"],
        }

    async def execute(self, tool_calls: list) -> ToolResult:
        """Execute multiple tools in parallel."""
        if not self.tool_executor:
            return ToolResult(
                success=False,
                content=None,
                error="Tool executor not available for batch execution",
            )

        if len(tool_calls) > 25:
            return ToolResult(
                success=False,
                content=None,
                error=f"Maximum of 25 tools allowed in batch, got {len(tool_calls)}",
            )

        disallowed = {"batch", "invalid", "apply_patch"}
        results = []

        async def execute_call(call):
            tool_name = call.get("tool")
            params = call.get("parameters", {})

            if tool_name in disallowed:
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": f"Tool '{tool_name}' is not allowed in batch",
                }

            try:
                result = await self.tool_executor.execute(tool_name, params)
                return {"success": result.success, "tool": tool_name, "result": result}
            except Exception as e:
                return {"success": False, "tool": tool_name, "error": str(e)}

        results = await asyncio.gather(*[execute_call(call) for call in tool_calls])

        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful

        output_parts = []
        for r in results:
            if r["success"]:
                result = r.get("result")
                if result and result.content:
                    output_parts.append(f"**{r['tool']}**: {result.content}")
            else:
                output_parts.append(
                    f"**{r['tool']}**: FAILED - {r.get('error', 'unknown error')}"
                )

        output = (
            "\n".join(output_parts)
            if output_parts
            else (
                "All tools executed successfully."
                if failed == 0
                else f"Executed {successful}/{len(results)} tools successfully."
            )
        )

        return ToolResult(
            success=True,
            content=output,
            metadata={
                "total": len(results),
                "successful": successful,
                "failed": failed,
                "results": results,
            },
        )


class MultiEditTool(Tool):
    """Edit multiple locations in a file."""

    def __init__(self):
        super().__init__(
            name="multiedit",
            description="Make multiple edits to a file in sequence",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "The path to the file to modify",
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldString": {
                                "type": "string",
                                "description": "The text to replace",
                            },
                            "newString": {
                                "type": "string",
                                "description": "The text to replace it with",
                            },
                            "replaceAll": {
                                "type": "boolean",
                                "description": "Replace all occurrences (default false)",
                            },
                        },
                        "required": ["oldString", "newString"],
                    },
                    "description": "Array of edit operations to perform sequentially",
                },
            },
            "required": ["filePath", "edits"],
        }

    async def execute(self, filePath: str, edits: list) -> ToolResult:
        """Execute multiple edits on a file."""
        edit_tool = EditFileTool()
        results = []

        for edit in edits:
            result = await edit_tool.execute(
                path=filePath,
                old=edit.get("oldString", ""),
                new=edit.get("newString", ""),
            )
            results.append(result)

            if not result.success:
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Edit failed: {result.error}",
                    metadata={"results": results},
                )

        return ToolResult(
            success=True,
            content=f"Successfully applied {len(edits)} edits to {filePath}",
            metadata={"results": results, "edits_applied": len(edits)},
        )


class ApplyPatchTool(Tool):
    """Apply a unified diff patch to files using opencode patch format."""

    def __init__(self):
        super().__init__(
            name="apply_patch",
            description="Apply a patch to files. Supports: *** Add File:, *** Delete File:, *** Update File: with *** Begin/End Patch markers.",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "patchText": {
                    "type": "string",
                    "description": "The full patch text with *** Begin Patch, *** Add File:/*** Delete File:/*** Update File:, *** End Patch markers",
                },
            },
            "required": ["patchText"],
        }

    async def execute(self, patchText: str) -> ToolResult:
        """Apply a patch using opencode format."""
        import re

        patchText = patchText.strip()
        lines = patchText.split("\n")
        files_changed = []
        errors = []

        begin_marker = "*** Begin Patch ***"
        end_marker = "*** End Patch ***"

        begin_idx = -1
        end_idx = -1
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped == begin_marker:
                begin_idx = idx
            if stripped == end_marker:
                end_idx = idx
                break

        if begin_idx == -1 or end_idx == -1 or begin_idx >= end_idx:
            return ToolResult(
                success=False,
                content=None,
                error="Invalid patch format: missing *** Begin Patch / *** End Patch markers",
            )

        i = begin_idx + 1
        while i < end_idx:
            line = lines[i].strip()

            if line.startswith("*** Add File:"):
                file_path = line[len("*** Add File:"):].strip()
                if not file_path:
                    i += 1
                    continue

                content_lines = []
                i += 1
                while i < end_idx and not lines[i].strip().startswith("***"):
                    content_lines.append(lines[i])
                    i += 1

                content = "\n".join(content_lines)
                try:
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    with open(file_path, "w") as f:
                        f.write(content)
                    files_changed.append(file_path)
                except Exception as e:
                    errors.append(f"Error adding {file_path}: {e}")

            elif line.startswith("*** Delete File:"):
                file_path = line[len("*** Delete File:"):].strip()
                if file_path:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        files_changed.append(file_path)
                    except Exception as e:
                        errors.append(f"Error deleting {file_path}: {e}")
                i += 1

            elif line.startswith("*** Update File:"):
                file_path = line[len("*** Update File:"):].strip()
                if not file_path:
                    i += 1
                    continue

                move_path = None
                if i + 1 < end_idx and lines[i + 1].strip().startswith("*** Move to:"):
                    move_path = lines[i + 1].strip()[len("*** Move to:"):].strip()
                    i += 2

                old_content = ""
                if os.path.exists(file_path):
                    with open(file_path) as f:
                        old_content = f.read()

                new_lines = []
                i += 1
                while i < end_idx:
                    l = lines[i].strip()
                    if l.startswith("***"):
                        break
                    if l == "*** End of File":
                        i += 1
                        break
                    new_lines.append(lines[i])
                    i += 1

                new_content = self._apply_opencode_patch(old_content, new_lines)

                target_path = move_path or file_path
                try:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "w") as f:
                        f.write(new_content)

                    if move_path and move_path != file_path:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    files_changed.append(target_path)
                except Exception as e:
                    errors.append(f"Error updating {file_path}: {e}")

            else:
                i += 1

        if errors:
            return ToolResult(
                success=False,
                content=None,
                error="\n".join(errors),
                metadata={"files_changed": files_changed},
            )

        output_parts = [f"Applied patch to {len(files_changed)} file(s)"]
        for f in files_changed:
            lines_list = []
            try:
                with open(f) as file:
                    for idx, line in enumerate(file):
                        if idx >= 30:
                            lines_list.append(f"... ({idx - 30} more lines)")
                            break
                        lines_list.append(line.rstrip())
            except Exception:
                lines_list = ["(could not read)"]
            output_parts.append(f"\n--- {f} ---\n" + "\n".join(lines_list))

        return ToolResult(
            success=True,
            content="\n".join(output_parts),
            metadata={"files_changed": files_changed},
        )

    def _apply_opencode_patch(self, old_content: str, patch_lines: list) -> str:
        """Apply opencode-style patch to content."""
        import re

        old_lines = old_content.split("\n") if old_content else []
        result_lines = []
        i = 0
        old_idx = 0

        while i < len(patch_lines):
            line = patch_lines[i]

            if not line:
                i += 1
                continue

            hunk_match = re.match(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", line)
            if hunk_match:
                old_start = int(hunk_match.group(1)) - 1
                old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
                i += 1

                result_lines.extend(old_lines[:old_start])
                remaining_old = old_lines[old_start + old_count:]

                while i < len(patch_lines):
                    pl = patch_lines[i]
                    if not pl or pl.startswith("@@") or pl.startswith("***"):
                        break
                    if pl.startswith(" "):
                        result_lines.append(pl[1:])
                        if remaining_old:
                            remaining_old.pop(0)
                    elif pl.startswith("-"):
                        if remaining_old:
                            remaining_old.pop(0)
                    elif pl.startswith("+"):
                        result_lines.append(pl[1:])
                    i += 1

                old_lines = remaining_old
                continue

            result_lines.append(line)
            i += 1

        result_lines.extend(old_lines)
        return "\n".join(result_lines)


class QuestionTool(Tool):
    """Ask the user questions and get answers."""

    def __init__(self):
        super().__init__(
            name="question",
            description="Ask the user questions and wait for their answers",
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The question to ask",
                            },
                            "header": {
                                "type": "string",
                                "description": "Short header for the question",
                            },
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                },
                                "description": "Optional multiple choice options",
                            },
                        },
                        "required": ["question"],
                    },
                    "description": "Questions to ask the user",
                },
            },
            "required": ["questions"],
        }

    async def execute(self, questions: list) -> ToolResult:
        """Ask questions (placeholder - requires UI integration)."""
        formatted = [f'"{q.get("question", "")}"' for q in questions]
        return ToolResult(
            success=True,
            content=f"Questions asked: {', '.join(formatted)}. (Question tool requires UI integration for actual user input)",
            metadata={"questions": questions},
        )


def create_builtin_tools(
    config: dict = None, file_tracker=None, lsp_manager=None
) -> list[Tool]:
    from nanocode.tools.builtin.exa_search import ExaFetchTool, ExaSearchTool
    from nanocode.tools.builtin.free_search import FreeExaSearchTool, OpenWebSearchTool

    exa_config = config.get("exa", {}) if config else {}
    
    # Shared unlocked files set - read tool adds, write tool checks
    unlocked_files: set = set()

    tools = [
        BashTool(),
        BashSessionTool(),
        GlobTool(),
        GrepTool(),
        ReadFileTool(read_tracker=unlocked_files, write_unlock_tracker=unlocked_files),
        WriteFileTool(read_tracker=unlocked_files, write_unlock_tracker=unlocked_files),
        EditFileTool(),
        FstatTool(),
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
        TodoTool(todo_service=get_todo_service()),
        # LSP tool
        LSPTool(lsp_manager=lsp_manager),
        # PTY tools
        PtyCreateTool(),
        PtyListTool(),
        PtyWriteTool(),
        PtyResizeTool(),
        PtyReadTool(),
        PtyRemoveTool(),
        # New tools
        BatchTool(),
        MultiEditTool(),
        ApplyPatchTool(),
        QuestionTool(),
        # Text tools
        SedTool(),
        DiffTool(),
    ]
    return tools


def register_builtin_tools(
    registry: ToolRegistry, config: dict = None, file_tracker=None, lsp_manager=None
):
    """Register all built-in tools."""
    from nanocode.tools import ToolExecutor

    executor = ToolExecutor(registry)
    for tool in create_builtin_tools(config, file_tracker, lsp_manager):
        if isinstance(tool, BatchTool):
            tool.tool_executor = executor
        registry.register(tool)

    try:
        from nanocode.skills import create_skills_manager
        from nanocode.tools.builtin.skill import register_skill_tools

        skills_manager = create_skills_manager()
        register_skill_tools(registry, skills_manager)
    except ImportError:
        pass

    try:
        from nanocode.snapshot import create_snapshot_manager
        from nanocode.tools.builtin.snapshot import register_snapshot_tools

        snapshot_manager = create_snapshot_manager()
        register_snapshot_tools(registry, snapshot_manager)
    except ImportError:
        pass
