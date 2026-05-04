"""LocalSandbox provider - no sandboxing, runs directly on host.

This is the default provider that maintains backward compatibility:
- Commands execute on the host via subprocess
- File operations use the local filesystem
- No isolation (same as current nanocode behavior)
"""

import asyncio
import os
from pathlib import Path
from typing import Any

from nanocode.sandbox.base import Sandbox, SandboxProvider


class LocalSandboxProvider(SandboxProvider):
    """Sandbox provider that runs everything locally (no isolation).

    This is the default provider that maintains backward compatibility
    with the current nanocode behavior.
    """

    def __init__(self, config: Any = None):
        """Initialize with optional config."""
        self.config = config
        self._sandboxes: dict[str, Sandbox] = {}

    async def create(self, session_id: str, **kwargs) -> Sandbox:
        """Create a new sandbox (no-op for local - returns a Sandbox object).

        For LocalSandbox, this just creates a Sandbox object that uses
        the host's filesystem and subprocess.
        """
        sandbox = Sandbox(sandbox_id=session_id, provider=self)
        self._sandboxes[session_id] = sandbox
        return sandbox

    async def suspend(self, sandbox_id: str):
        """Suspend sandbox (no-op for local - can't suspend host processes)."""
        if sandbox_id in self._sandboxes:
            self._sandboxes[sandbox_id].status = "suspended"

    async def resume(self, sandbox_id: str):
        """Resume sandbox (no-op for local)."""
        if sandbox_id in self._sandboxes:
            self._sandboxes[sandbox_id].status = "running"

    async def destroy(self, sandbox_id: str):
        """Destroy sandbox (no-op for local - just remove from tracking)."""
        if sandbox_id in self._sandboxes:
            del self._sandboxes[sandbox_id]

    async def execute(
        self, sandbox_id: str, command: str, cwd: str = None, env: dict = None
    ) -> dict:
        """Execute a command on the host.

        Args:
            sandbox_id: The sandbox ID (unused for local)
            command: The command to execute
            cwd: Working directory (defaults to cwd)
            env: Environment variables

        Returns:
            dict with keys: success, stdout, stderr, exit_code
        """
        workdir = Path(cwd) if cwd else Path.cwd()

        # Use sanitized environment

        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "USER": os.environ.get("USER", ""),
            "SHELL": os.environ.get("SHELL", "/bin/bash"),
            "TERM": os.environ.get("TERM", "xterm-256color"),
        }
        if env:
            safe_env.update(env)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workdir),
                env=safe_env,
            )
            stdout, stderr = await proc.communicate()

            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    async def read_file(self, sandbox_id: str, path: str) -> str:
        """Read a file from the local filesystem."""
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception as e:
            raise FileNotFoundError(f"Could not read {path}: {e}")

    async def write_file(self, sandbox_id: str, path: str, content: str) -> bool:
        """Write a file to the local filesystem."""
        try:
            Path(path).write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            raise OSError(f"Could not write {path}: {e}")

    async def list_sandboxes(self) -> list[dict]:
        """List all sandboxes (just returns tracked ones for local)."""
        return [
            {"id": sid, "status": sb.status}
            for sid, sb in self._sandboxes.items()
        ]
