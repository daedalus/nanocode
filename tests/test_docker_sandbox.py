"""Tests for the Docker Sandbox."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanocode.sandbox.docker import (
    DockerSandboxProvider,
    SandboxMode,
    SandboxConfig,
)


class TestSandboxMode:
    """Tests for SandboxMode enum."""

    def test_modes_exist(self):
        """Test that all modes are defined."""
        assert SandboxMode.READ_ONLY
        assert SandboxMode.READ_WRITE


class TestSandboxConfig:
    """Tests for SandboxConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = SandboxConfig()
        assert config.image == "nanocode-sandbox:latest"
        assert config.mode == SandboxMode.READ_WRITE
        assert config.memory_limit == "2g"
        assert config.cpu_limit == 2.0
        assert config.pid_limit == 200
        assert config.cap_drop == ["ALL"]

    def test_to_docker_args(self):
        """Test converting to docker arguments."""
        config = SandboxConfig()
        args = config.to_docker_args()

        assert "--memory" in args
        assert "2g" in args
        assert "--cpus" in args
        assert "2.0" in args
        assert "--pids-limit" in args
        assert "200" in args
        assert "--cap-drop" in args
        assert "ALL" in args

    def test_to_docker_args_read_only(self):
        """Test docker arguments for read-only mode."""
        config = SandboxConfig(read_only_rootfs=True)
        args = config.to_docker_args()

        assert "--read-only" in args

    def test_to_docker_args_with_volumes(self):
        """Test docker arguments with volumes."""
        config = SandboxConfig(volumes={"/host": "/container"})
        args = config.to_docker_args()

        assert "-v" in args
        assert "/host:/container" in args

    def test_to_docker_args_with_tmpfs(self):
        """Test docker arguments with tmpfs."""
        config = SandboxConfig(tmpfs={"/tmp": "size=100M"})
        args = config.to_docker_args()

        assert "--tmpfs" in args
        assert "/tmp:size=100M" in args


class TestDockerSandboxProvider:
    """Tests for DockerSandboxProvider."""

    def test_init(self):
        """Test initialization."""
        provider = DockerSandboxProvider()
        assert provider._sandbox_config.image == "nanocode-sandbox:latest"

    def test_init_with_config(self):
        """Test initialization with custom config."""
        config = MagicMock()
        config.sandbox_image = "custom-image:latest"
        config.sandbox_workdir = "/app"
        config.memory_limit = "4g"

        provider = DockerSandboxProvider(config)
        assert provider._sandbox_config.image == "custom-image:latest"
        assert provider._sandbox_config.memory_limit == "4g"

    def test_get_mode(self):
        """Test getting sandbox mode."""
        provider = DockerSandboxProvider()
        provider._container_modes["session-1"] = SandboxMode.READ_ONLY

        assert provider.get_mode("session-1") == SandboxMode.READ_ONLY
        assert provider.get_mode("session-2") is None

    def test_container_modes_tracking(self):
        """Test container modes are tracked."""
        provider = DockerSandboxProvider()
        provider._containers["s1"] = "abc123"
        provider._container_modes["s1"] = SandboxMode.READ_WRITE

        assert "s1" in provider._containers
        assert "s1" in provider._container_modes


class TestSandboxConfigEdgeCases:
    """Tests for SandboxConfig edge cases."""

    def test_empty_volumes(self):
        """Test with empty volumes."""
        config = SandboxConfig(volumes={})
        args = config.to_docker_args()
        assert "-v" not in args

    def test_multiple_volumes(self):
        """Test with multiple volumes."""
        config = SandboxConfig(volumes={"/a": "/b", "/c": "/d"})
        args = config.to_docker_args()
        assert args.count("-v") == 2

    def test_network_mode(self):
        """Test network mode configuration."""
        config = SandboxConfig(network_mode="host")
        args = config.to_docker_args()
        assert "--network" in args
        assert "host" in args
