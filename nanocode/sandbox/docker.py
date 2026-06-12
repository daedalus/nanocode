"""Docker sandbox provider - runs commands in Docker containers.

Provides isolation via Docker containers with resource limits:
- One container per session (or reuse)
- Suspend = pause container (fast, ~25ms with Blaxel-style approach)
- Resume = unpause container
- Destroy = stop + remove container
- Two modes: read-only rootfs (dynamic tools), read-write (terminal commands)
- Resource limits: memory, CPU, PIDs, capabilities

Note: This is optional and requires Docker to be installed.
"""

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nanocode.sandbox.base import Sandbox, SandboxProvider


class SandboxMode(StrEnum):
    """Sandbox execution modes."""

    READ_ONLY = "read-only"  # For dynamic tools (safe execution)
    READ_WRITE = "read-write"  # For terminal commands (full access)


@dataclass
class SandboxConfig:
    """Configuration for Docker sandbox."""

    image: str = "nanocode-sandbox:latest"
    workdir: str = "/workspace"
    mode: SandboxMode = SandboxMode.READ_WRITE
    memory_limit: str = "2g"
    cpu_limit: float = 2.0
    pid_limit: int = 200
    cap_drop: list[str] = field(default_factory=lambda: ["ALL"])
    volumes: dict[str, str] = field(default_factory=dict)
    read_only_rootfs: bool = False
    tmpfs: dict[str, str] = field(default_factory=lambda: {"/tmp": "size=100M"})
    network_mode: str = "none"  # No network by default for security

    def to_docker_args(self) -> list[str]:
        """Convert config to docker create arguments."""
        args = [
            "--memory", self.memory_limit,
            "--cpus", str(self.cpu_limit),
            "--pids-limit", str(self.pid_limit),
            "--read-only" if self.read_only_rootfs else "--read-write",
            "--network", self.network_mode,
        ]

        # Drop capabilities
        for cap in self.cap_drop:
            args.extend(["--cap-drop", cap])

        # Volume mounts
        for host_path, container_path in self.volumes.items():
            args.extend(["-v", f"{host_path}:{container_path}"])

        # Tmpfs mounts
        for mount_path, options in self.tmpfs.items():
            args.extend(["--tmpfs", f"{mount_path}:{options}"])

        return args


class DockerSandboxProvider(SandboxProvider):
    """Sandbox provider using Docker containers with resource limits.

    Each session gets its own container for isolation.
    Uses 'docker create/pause/unpause/rm' for lifecycle management.

    Supports two modes:
    - read-only: For dynamic tools (safe execution)
    - read-write: For terminal commands (full access)
    """

    def __init__(self, config: Any = None):
        """Initialize with optional config.

        Config options:
            image: Docker image to use (default: 'nanocode-sandbox:latest')
            workdir: Working directory in container (default: '/workspace')
            volumes: Volume mounts (dict: host_path -> container_path)
            mode: SandboxMode (read-only or read-write)
            memory_limit: Memory limit (default: '2g')
            cpu_limit: CPU limit (default: 2.0)
            pid_limit: PID limit (default: 200)
        """
        self.config = config or {}
        self._containers: dict[str, str] = {}  # session_id -> container_id
        self._container_modes: dict[str, SandboxMode] = {}  # session_id -> mode
        self._sandbox_config = SandboxConfig(
            image=getattr(config, "sandbox_image", "nanocode-sandbox:latest"),
            workdir=getattr(config, "sandbox_workdir", "/workspace"),
            mode=getattr(config, "sandbox_mode", SandboxMode.READ_WRITE),
            memory_limit=getattr(config, "memory_limit", "2g"),
            cpu_limit=getattr(config, "cpu_limit", 2.0),
            pid_limit=getattr(config, "pid_limit", 200),
        )

    async def create(
        self,
        session_id: str,
        mode: SandboxMode | None = None,
        **kwargs,
    ) -> Sandbox:
        """Create a new Docker container for a session.

        Args:
            session_id: Session identifier
            mode: Sandbox mode (read-only or read-write)
            **kwargs: Additional configuration overrides

        Returns:
            Sandbox instance
        """
        container_name = f"nanocode-{session_id}"
        sandbox_mode = mode or self._sandbox_config.mode

        # Build docker create command
        cmd = ["docker", "create", "--name", container_name]

        # Add resource limits
        cmd.extend(self._sandbox_config.to_docker_args())

        # Override read-only based on mode
        if sandbox_mode == SandboxMode.READ_ONLY:
            cmd.extend(["--read-only", "--tmpfs", "/tmp:size=100M"])
            # Add writable layers for common paths
            cmd.extend(["--tmpfs", "/var/run:size=10M"])
            cmd.extend(["--tmpfs", "/var/log:size=50M"])

        # Add volumes
        for host_path, container_path in self._sandbox_config.volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

        # Add workdir and image
        cmd.extend([
            "--workdir", self._sandbox_config.workdir,
            self._sandbox_config.image,
            "tail", "-f", "/dev/null",  # Keep container running
        ])

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
            self._container_modes[session_id] = sandbox_mode

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

    def get_mode(self, session_id: str) -> SandboxMode | None:
        """Get the mode for a session's sandbox."""
        return self._container_modes.get(session_id)

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
