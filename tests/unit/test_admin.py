"""Unit tests for admin console module."""

import pytest
from unittest.mock import Mock, AsyncMock

from agent_smith.admin import AdminConsole, UsageStats


class TestUsageStats:
    """Tests for UsageStats dataclass."""

    def test_default_values(self):
        """Test default values."""
        stats = UsageStats()
        assert stats.total_sessions == 0
        assert stats.total_messages == 0
        assert stats.total_tokens_in == 0
        assert stats.total_tokens_out == 0
        assert stats.total_cost == 0.0
        assert stats.sessions_by_date == {}
        assert stats.tokens_by_model == {}

    def test_with_values(self):
        """Test with custom values."""
        stats = UsageStats(
            total_sessions=10,
            total_messages=100,
            total_tokens_in=50000,
            total_tokens_out=100000,
            total_cost=5.50,
            sessions_by_date={"2024-01-01": {"messages": 10, "tokens": 1000}},
            tokens_by_model={"gpt-4": {"in": 1000, "out": 2000, "cost": 0.10}},
        )
        assert stats.total_sessions == 10
        assert stats.total_messages == 100
        assert stats.total_tokens_in == 50000
        assert stats.total_tokens_out == 100000
        assert stats.total_cost == 5.50


class TestAdminConsole:
    """Tests for AdminConsole."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock()
        config._config = {
            "llm": {
                "providers": {
                    "openai": {"api_key": "sk-test123"},
                }
            }
        }
        config._config_path = "config.yaml"
        config.providers = {
            "openai": {"api_key": "sk-test123"},
        }
        return config

    def test_admin_console_init(self, mock_config):
        """Test admin console initialization."""
        console = AdminConsole(mock_config, host="127.0.0.1", port=7890)
        assert console.host == "127.0.0.1"
        assert console.port == 7890
        assert console.config == mock_config
        assert console.app is not None

    def test_admin_console_routes(self, mock_config):
        """Test that routes are registered."""
        console = AdminConsole(mock_config)

        routes = list(console.app.router.routes())
        paths = [str(r.resource) for r in routes]

        assert any("/" in p for p in paths)
        assert any("/dashboard" in p for p in paths)
        assert any("/sessions" in p for p in paths)
        assert any("/usage" in p for p in paths)
        assert any("/config" in p for p in paths)
        assert any("/keys" in p for p in paths)
        assert any("/health" in p for p in paths)

    @pytest.mark.asyncio
    async def test_health_endpoint(self, mock_config):
        """Test health check endpoint."""
        console = AdminConsole(mock_config)

        request = Mock()
        response = await console.handle_health(request)

        assert response.status == 200
        import json

        data = json.loads(response.text)
        assert data["status"] == "ok"
        assert data["service"] == "admin"

    @pytest.mark.asyncio
    async def test_dashboard_endpoint(self, mock_config):
        """Test dashboard endpoint."""
        console = AdminConsole(mock_config)

        request = Mock()
        response = await console.handle_dashboard(request)

        assert response.status == 200
        assert b"Agent Smith" in response.body

    @pytest.mark.asyncio
    async def test_sessions_endpoint(self, mock_config):
        """Test sessions endpoint."""
        console = AdminConsole(mock_config)

        request = Mock()
        request.query = {}

        response = await console.handle_sessions(request)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_usage_endpoint(self, mock_config):
        """Test usage endpoint."""
        console = AdminConsole(mock_config)

        request = Mock()

        response = await console.handle_usage(request)

        assert response.status == 200
        assert b"Usage" in response.body

    @pytest.mark.asyncio
    async def test_config_endpoint(self, mock_config):
        """Test config endpoint."""
        console = AdminConsole(mock_config)

        request = Mock()

        response = await console.handle_config(request)

        assert response.status == 200
        assert b"Configuration" in response.body

    @pytest.mark.asyncio
    async def test_keys_endpoint(self, mock_config):
        """Test keys endpoint."""
        console = AdminConsole(mock_config)

        request = Mock()

        response = await console.handle_keys(request)

        assert response.status == 200
        assert b"API Keys" in response.body

    def test_get_api_keys(self, mock_config):
        """Test getting API keys."""
        console = AdminConsole(mock_config)

        keys = console._get_api_keys()

        assert len(keys) == 1
        assert keys[0]["name"] == "openai"
        assert keys[0]["key"].startswith("sk-")  # Masked

    def test_get_api_keys_env_vars(self):
        """Test getting API keys with env var placeholders."""
        config = Mock()
        config._config = {
            "llm": {
                "providers": {
                    "openai": {"api_key": "${OPENAI_API_KEY}"},
                }
            }
        }
        config._config_path = "config.yaml"
        config.providers = {
            "openai": {"api_key": "${OPENAI_API_KEY}"},
        }

        console = AdminConsole(config)
        keys = console._get_api_keys()

        assert len(keys) == 0  # Env var placeholders are not shown

    @pytest.mark.asyncio
    async def test_add_key(self, mock_config):
        """Test adding API key."""
        console = AdminConsole(mock_config)

        request = Mock()
        request.post = AsyncMock(
            return_value={
                "name": "anthropic",
                "key": "sk-ant-new",
            }
        )

        await console.handle_add_key(request)

        assert mock_config.set.called

    @pytest.mark.asyncio
    async def test_delete_key(self, mock_config):
        """Test deleting API key."""
        console = AdminConsole(mock_config)

        request = Mock()
        request.post = AsyncMock(
            return_value={
                "name": "openai",
            }
        )

        await console.handle_delete_key(request)


class TestAdminConsoleRoutes:
    """Tests for admin route patterns."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock()
        config._config = {}
        config._config_path = "config.yaml"
        config.providers = {}
        return config

    def test_session_detail_route(self, mock_config):
        """Test session detail route pattern."""
        console = AdminConsole(mock_config)

        routes = list(console.app.router.routes())
        paths = [str(r.resource) for r in routes]

        assert any("/sessions/" in p for p in paths)

    def test_delete_session_route(self, mock_config):
        """Test delete session route pattern."""
        console = AdminConsole(mock_config)

        routes = list(console.app.router.routes())
        paths = [str(r.resource) for r in routes]

        assert any("/sessions/" in p and "delete" in p for p in paths)
