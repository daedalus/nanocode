"""Blaxel sandbox provider - uses Blaxel API for persistent sandboxes.

Provides near-instant resume (~25ms) via Blaxel's perpetual sandbox platform:
- Sandboxes persist forever, automatically scaling to zero when idle
- Resume from standby in under 25ms (even after weeks)
- Full filesystem & memory snapshots preserved across suspend/resume
- Requires BLAXEL_API_KEY environment variable.

API Docs: https://docs.blaxel.ai/
"""

import os
from typing import Any

import httpx

from nanocode.sandbox import register_sandbox_provider
from nanocode.sandbox.base import Sandbox, SandboxProvider


class BlaxelSandboxProvider(SandboxProvider):
    """Sandbox provider using Blaxel API.

    Features:
    - Automatic scale-to-zero after 15s inactivity
    - 25ms resume from standby
    - Persistent filesystem & memory (processes survive suspend)
    - No Docker required

    Environment Variables:
        BLAXEL_API_KEY: Your Blaxel API key
        BLAXEL_BASE_URL: Override API base URL (default: https://api.blaxel.ai/v0)
    """

    def __init__(self, config: Any = None):
        """Initialize Blaxel provider.

        Config options:
            api_key: Blaxel API key (or use env var BLAXEL_API_KEY)
            base_url: API base URL (default: https://api.blaxel.ai/v0)
            image: Sandbox image (default: blaxel/base-image:latest)
            memory: Memory in MB (default: 4096)
            default_region: Default region (default: us-pdx-1)
        """
        self.config = config or {}
        self._api_key = self.config.get("blaxel_api_key") or os.environ.get("BLAXEL_API_KEY")
        if not self._api_key:
            raise ValueError(
                "Blaxel API key required. Set BLAXEL_API_KEY env var or config.blaxel_api_key"
            )

        self._base_url = self.config.get("blaxel_base_url", "https://api.blaxel.ai/v0")
        self._image = self.config.get("sandbox_image", "blaxel/base-image:latest")
        self._memory = self.config.get("sandbox_memory", 4096)
        self._region = self.config.get("default_region", "us-pdx-1")

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
        )
        self._sandboxes: dict[str, dict] = {}  # session_id -> sandbox_info

    async def create(self, session_id: str, **kwargs) -> Sandbox:
        """Create or get existing sandbox via Blaxel API.

        Blaxel's createIfNotExist=true flag handles idempotent creation.
        """
        sandbox_name = f"nanocode-{session_id}"
        url = f"/sandboxes/{sandbox_name}"

        # Try to get existing sandbox first
        try:
            resp = await self._client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                self._sandboxes[session_id] = data
                return Sandbox(sandbox_id=session_id, provider=self)
        except Exception:
            pass

        # Create new sandbox
        payload = {
            "metadata": {
                "session_id": session_id,
                "created_by": "nanocode",
            },
            "spec": {
                "image": kwargs.get("image", self._image),
                "memory": kwargs.get("memory", self._memory),
            },
        }

        try:
            resp = await self._client.put(url, json=payload)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Failed to create sandbox: {resp.text}")
            data = resp.json()
            self._sandboxes[session_id] = data
            return Sandbox(sandbox_id=session_id, provider=self)
        except Exception as e:
            raise RuntimeError(f"Blaxel create failed: {e}")

    async def suspend(self, sandbox_id: str):
        """Suspend sandbox (scales to zero after 15s of inactivity).

        Note: Blaxel auto-suspends after 15s idle, so this is optional.
        We can explicitly stop it via the API.
        """
        if sandbox_id not in self._sandboxes:
            return

        sandbox_name = f"nanocode-{sandbox_id}"
        url = f"/sandboxes/{sandbox_name}/stop"

        try:
            resp = await self._client.put(url)
            if resp.status_code not in (200, 202):
                raise RuntimeError(f"Failed to stop sandbox: {resp.text}")
        except Exception as e:
            raise RuntimeError(f"Blaxel stop failed: {e}")

    async def resume(self, sandbox_id: str):
        """Resume sandbox (~25ms resume from standby).

        Starts the sandbox if it's in standby mode.
        """
        if sandbox_id not in self._sandboxes:
            return

        sandbox_name = f"nanocode-{sandbox_id}"
        url = f"/sandboxes/{sandbox_name}/start"

        try:
            resp = await self._client.put(url)
            if resp.status_code not in (200, 202):
                raise RuntimeError(f"Failed to start sandbox: {resp.text}")
        except Exception as e:
            raise RuntimeError(f"Blaxel start failed: {e}")

    async def destroy(self, sandbox_id: str):
        """Destroy sandbox permanently."""
        if sandbox_id not in self._sandboxes:
            return

        sandbox_name = f"nanocode-{sandbox_id}"
        url = f"/sandboxes/{sandbox_name}"

        try:
            resp = await self._client.delete(url)
            if resp.status_code not in (200, 204):
                raise RuntimeError(f"Failed to delete sandbox: {resp.text}")
        except Exception as e:
            raise RuntimeError(f"Blaxel delete failed: {e}")
        finally:
            del self._sandboxes[sandbox_id]

    async def execute(
        self, sandbox_id: str, command: str, cwd: str = None, env: dict = None
    ) -> dict:
        """Execute a command in the Blaxel sandbox.

        Uses Blaxel's code execution API or SSH tunnel.
        For now, we use the /exec endpoint if available.
        """
        if sandbox_id not in self._sandboxes:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Sandbox not found for session {sandbox_id}",
                "exit_code": -1,
            }

        sandbox_name = f"nanocode-{sandbox_id}"
        url = f"/sandboxes/{sandbox_name}/exec"

        payload = {
            "command": command,
            "workdir": cwd or "/workspace",
        }
        if env:
            payload["env"] = env

        try:
            resp = await self._client.post(url, json=payload)
            if resp.status_code != 200:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Exec failed: {resp.text}",
                    "exit_code": -1,
                }

            data = resp.json()
            return {
                "success": data.get("exit_code", 0) == 0,
                "stdout": data.get("stdout", ""),
                "stderr": data.get("stderr", ""),
                "exit_code": data.get("exit_code", 0),
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    async def read_file(self, sandbox_id: str, path: str) -> str:
        """Read a file from the Blaxel sandbox."""
        if sandbox_id not in self._sandboxes:
            raise FileNotFoundError(f"Sandbox not found for session {sandbox_id}")

        sandbox_name = f"nanocode-{sandbox_id}"
        url = f"/sandboxes/{sandbox_name}/files{path}"

        try:
            resp = await self._client.get(url)
            if resp.status_code != 200:
                raise FileNotFoundError(f"File not found: {path}")
            return resp.text
        except Exception as e:
            raise FileNotFoundError(f"Could not read {path}: {e}")

    async def write_file(self, sandbox_id: str, path: str, content: str) -> bool:
        """Write a file to the Blaxel sandbox."""
        if sandbox_id not in self._sandboxes:
            raise OSError(f"Sandbox not found for session {sandbox_id}")

        sandbox_name = f"nanocode-{sandbox_id}"
        url = f"/sandboxes/{sandbox_name}/files{path}"

        try:
            resp = await self._client.put(url, content=content.encode("utf-8"))
            return resp.status_code in (200, 201, 204)
        except Exception as e:
            raise OSError(f"Could not write {path}: {e}")

    async def list_sandboxes(self) -> list[dict]:
        """List all sandboxes managed by this provider."""
        try:
            resp = await self._client.get("/sandboxes")
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("sandboxes", [])
        except Exception:
            return []

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


# Register with the provider registry
register_sandbox_provider("blaxel", BlaxelSandboxProvider)
