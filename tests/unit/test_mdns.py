"""Tests for mDNS (multicast DNS) service discovery."""

import pytest

from agent_smith.mdns import (
    DiscoveredService,
    MDNSService,
    MDNSManager,
    get_manager,
)


class TestDiscoveredService:
    """Test discovered service dataclass."""

    def test_create_service(self):
        """Test creating a discovered service."""
        service = DiscoveredService(
            name="agent-smith-8080",
            host="agent-smith-8080.local",
            port=8080,
            service_type="_agent-smith._tcp.local.",
            properties={"path": "/"},
        )

        assert service.name == "agent-smith-8080"
        assert service.host == "agent-smith-8080.local"
        assert service.port == 8080
        assert service.properties["path"] == "/"

    def test_discovered_at_default(self):
        """Test discovered_at is set automatically."""
        service = DiscoveredService(
            name="test",
            host="test.local",
            port=8080,
            service_type="_http._tcp.local.",
            properties={},
        )

        assert service.discovered_at is not None


class TestMDNSService:
    """Test MDNS service class."""

    @pytest.fixture
    def service(self):
        """Create an MDNS service."""
        return MDNSService(service_name="test-agent")

    def test_service_creation(self, service):
        """Test creating an MDNS service."""
        assert service.service_name == "test-agent"
        assert service._zeroconf is None
        assert len(service._discovered) == 0

    def test_add_listener(self, service):
        """Test adding a listener."""
        called = []

        def listener(svc):
            called.append(svc)

        service.add_listener(listener)

        assert len(service._listeners) == 1

    def test_remove_listener(self, service):
        """Test removing a listener."""

        def listener(svc):
            pass

        service.add_listener(listener)
        service.remove_listener(listener)

        assert len(service._listeners) == 0

    def test_get_discovered_empty(self, service):
        """Test getting discovered services when none exist."""
        discovered = service.get_discovered()

        assert discovered == []

    def test_get_service_not_found(self, service):
        """Test getting a non-existent service."""
        result = service.get_service("nonexistent")

        assert result is None


class TestMDNSManager:
    """Test MDNS manager."""

    @pytest.fixture
    def manager(self):
        """Create an MDNS manager."""
        return MDNSManager()

    def test_manager_creation(self, manager):
        """Test creating an MDNS manager."""
        assert len(manager._services) == 0
        assert manager._running is False

    def test_get_or_create(self, manager):
        """Test getting or creating a service."""
        service = manager.get_or_create("default")

        assert service is not None
        assert service.service_name == "default"

    def test_get_or_create_same_instance(self, manager):
        """Test getting same instance."""
        service1 = manager.get_or_create("default")
        service2 = manager.get_or_create("default")

        assert service1 is service2

    def test_get_discovered_empty(self, manager):
        """Test getting discovered from non-existent service."""
        discovered = manager.get_discovered("nonexistent")

        assert discovered == []


class TestGetManager:
    """Test get_manager function."""

    def test_get_manager(self):
        """Test getting the default manager."""
        manager = get_manager()

        assert manager is not None
        assert isinstance(manager, MDNSManager)

    def test_get_manager_same_instance(self):
        """Test getting same manager instance."""
        manager1 = get_manager()
        manager2 = get_manager()

        assert manager1 is manager2
