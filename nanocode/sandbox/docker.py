"""Docker sandbox provider - runs commands in Docker containers.

Provides isolation via Docker containers:
- One container per session (or reuse)
- Suspend = pause container (fast, ~25ms with Blaxel-style approach)
- Resume = unpause container
- Destroy = stop + remove container

Note: This is optional and requires Docker to be installed.
"""

import asyncio
from typing import Any

from nanocode.sandbox.base import Sandbox, SandboxProvider


class DockerSandboxProvider(SandboxProvider):
    """Sandbox provider using Docker containers.

    Each session gets its own container for isolation.
    Uses 'docker create/pause/unpause/rm' for lifecycle management.
    """

    def __init__(self, config: Any = None):
        """Initialize with optional config.

        Config options:
            image: Docker image to use (default: 'nanocode-sandbox:latest')
            workdir: Working directory in container (default: '/workspace')
            volumes: Volume mounts (dict: host_path -> container_path)
        """
        self.config = config or {}
        self._containers: dict[str, str] = {}  # session_id -> container_id
        self._image = getattr(config, "sandbox_image", "nanocode-sandbox:latest")
        self._workdir = getattr(config, "sandbox_workdir", "/workspace")

    async def create(self, session_id: str, **kwargs) -> Sandbox:
        """Create a new Docker container for a session.

        Uses 'docker create' to create a paused container,
        then 'docker start' to begin execution when needed.
        """
        container_name = f"nanocode-{session_id}"

        # Build docker create command
        cmd = [
            "docker", "create",
            "--name", container_name,
            "--workdir", self._workdir,
            self._image,
            "tail", "-f", "/dev/null",  # Keep container running
        ]

        # Add volume mounts if configured
        volumes = getattr(self.config, "sandbox_volumes", {})
        for host_path, container_path in volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise RuntimeError(f"Failed to create container: {stderr.decode()}")

            container_id = stdout.decode().strip()
            self._containers[session_id] = container_id

            # Start the container
            start_proc = await asyncio.create_subprocess_exec(
                "docker", "start", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await start_proc.communicate()

            if start_proc.returncode != 0:
                raise RuntimeError(f"Failed to start container: {container_id}")

            return Sandbox(sandbox_id=session_id, provider=self)

        except Exception as e:
            raise RuntimeError(f"Docker create failed: {e}")

    async def suspend(self, sandbox_id: str):
        """Suspend a running container (pause it).

        Uses 'docker pause' for fast suspend (~25ms resume possible).
        """
        if sandbox_id not in self._containers:
            return

        container_id = self._containers[sandbox_id]
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "pause", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            raise RuntimeError(f"Docker pause failed: {e}")

    async def resume(self, sandbox_id: str):
        """Resume a paused container (unpause it)."""
        if sandbox_id not in self._containers:
            return

        container_id = self._containers[sandbox_id]
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "unpause", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            raise RuntimeError(f"Docker unpause failed: {e}")

    async def destroy(self, sandbox_id: str):
        """Destroy a container permanently."""
        if sandbox_id not in self._containers:
            return

        container_id = self._containers[sandbox_id]
        try:
            # Stop and remove container
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            raise RuntimeError(f"Docker rm failed: {e}")
        finally:
            del self._containers[sandbox_id]

    async def execute(
        self, sandbox_id: str, command: str, cwd: str = None, env: dict = None
    ) -> dict:
        """Execute a command in the Docker container.

        Uses 'docker exec' to run commands inside the container.
        """
        if sandbox_id not in self._containers:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Container not found for session {sandbox_id}",
                "exit_code": -1,
            }

        container_id = self._containers[sandbox_id]

        # Build docker exec command
        cmd = ["docker", "exec"]
        if cwd:
            cmd.extend(["--workdir", cwd])
        if env:
            for key, value in env.items():
                cmd.extend(["--env", f"{key}={value}"])
        cmd.append(container_id)
        cmd.extend(["/bin/bash", "-c", command])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
        """Read a file from the Docker container."""
        if sandbox_id not in self._containers:
            raise FileNotFoundError(f"Container not found for session {sandbox_id}")

        container_id = self._containers[sandbox_id]
        cmd = ["docker", "exec", container_id, "cat", path]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise FileNotFoundError(f"File not found in container: {path}")

            return stdout.decode("utf-8", errors="replace")
        except Exception as e:
            raise FileNotFoundError(f"Could not read {path}: {e}")

    async def write_file(self, sandbox_id: str, path: str, content: str) -> bool:
        """Write a file to the Docker container."""
        if sandbox_id not in self._containers:
            raise OSError(f"Container not found for session {sandbox_id}")

        container_id = self._containers[sandbox_id]

        # Use 'docker exec' with 'tee' to write file
        cmd = ["docker", "exec", container_id, "tee", path]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(input=content.encode("utf-8"))

            return proc.returncode == 0
        except Exception as e:
            raise OSError(f"Could not write {path}: {e}")

    async def list_sandboxes(self) -> list[dict]:
        """List all Docker containers managed by this provider."""
        result = []
        for session_id, container_id in self._containers.items():
            # Check actual container status
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "inspect", "-f", "{{.State.Status}}", container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                status = stdout.decode().strip().strip('"')
            except Exception:
                status = "unknown"

            result.append({
                "session_id": session_id,
                "container_id": container_id,
                "status": status,
            })
        return result
