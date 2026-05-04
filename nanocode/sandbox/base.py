"""Sandbox module - lifecycle management for agent sandboxes.

Implements Phase 6 from the Mendral blog post:
- Sandboxes become cattle (can suspend/resume, die without losing session)
- Provision sandboxes only when needed
- Suspend when idle, resume only for workspace operations
"""

from abc import ABC, abstractmethod


class Sandbox:
    """Represents a running sandbox instance."""

    def __init__(self, sandbox_id: str, provider: "SandboxProvider"):
        self.id = sandbox_id
        self.provider = provider
        self.status = "running"  # running, suspended, stopped

    async def execute(self, command: str, cwd: str = None, env: dict = None) -> dict:
        """Execute a command in the sandbox."""
        return await self.provider.execute(self.id, command, cwd=cwd, env=env)

    async def read_file(self, path: str) -> str:
        """Read a file from the sandbox."""
        return await self.provider.read_file(self.id, path)

    async def write_file(self, path: str, content: str) -> bool:
        """Write a file to the sandbox."""
        return await self.provider.write_file(self.id, path, content)

    async def suspend(self):
        """Suspend the sandbox (pause execution)."""
        await self.provider.suspend(self.id)
        self.status = "suspended"

    async def resume(self):
        """Resume a suspended sandbox."""
        await self.provider.resume(self.id)
        self.status = "running"

    async def destroy(self):
        """Destroy the sandbox permanently."""
        await self.provider.destroy(self.id)
        self.status = "stopped"


class SandboxProvider(ABC):
    """Abstract base class for sandbox providers.

    Implementations:
    - LocalSandbox: No sandboxing, runs directly on host (default)
    - DockerSandbox: Docker container per session
    - BlaxelSandbox: Integration with Blaxel API (25ms resume)
    """

    @abstractmethod
    async def create(self, session_id: str, **kwargs) -> Sandbox:
        """Create a new sandbox for a session."""
        pass

    @abstractmethod
    async def suspend(self, sandbox_id: str):
        """Suspend a running sandbox."""
        pass

    @abstractmethod
    async def resume(self, sandbox_id: str):
        """Resume a suspended sandbox."""
        pass

    @abstractmethod
    async def destroy(self, sandbox_id: str):
        """Destroy a sandbox permanently."""
        pass

    @abstractmethod
    async def execute(self, sandbox_id: str, command: str, cwd: str = None, env: dict = None) -> dict:
        """Execute a command in the sandbox.

        Returns:
            dict with keys: success (bool), stdout (str), stderr (str), exit_code (int)
        """
        pass

    @abstractmethod
    async def read_file(self, sandbox_id: str, path: str) -> str:
        """Read a file from the sandbox."""
        pass

    @abstractmethod
    async def write_file(self, sandbox_id: str, path: str, content: str) -> bool:
        """Write a file to the sandbox."""
        pass

    @abstractmethod
    async def list_sandboxes(self) -> list[dict]:
        """List all sandboxes managed by this provider."""
        pass
