"""mDNS (multicast DNS) service discovery.

This module provides mDNS service discovery for finding remote agents
on the local network, similar to opencode's implementation.

Uses the python-zeroconf library (Bonjour/Avahi compatible).
"""

import asyncio
import socket
from typing import Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DiscoveredService:
    """A service discovered via mDNS."""

    name: str
    host: str
    port: int
    service_type: str
    properties: dict
    discovered_at: datetime = None

    def __post_init__(self):
        if self.discovered_at is None:
            self.discovered_at = datetime.now()


class MDNSService:
    """mDNS service for publishing and discovering services."""

    SERVICE_TYPE = "_agent-smith._tcp.local."
    DEFAULT_PORT = 8080

    def __init__(self, service_name: str = "agent-smith"):
        self.service_name = service_name
        self._zeroconf = None
        self._publisher = None
        self._browser = None
        self._discovered: dict[str, DiscoveredService] = {}
        self._listeners: list[Callable[[DiscoveredService], None]] = []
        self._running = False

    async def start(self):
        """Start the mDNS service."""
        try:
            import zeroconf

            self._zeroconf = zeroconf.Zeroconf()
            self._running = True
        except ImportError:
            print("mDNS requires python-zeroconf: pip install zeroconf")
            raise
        except Exception as e:
            print(f"Failed to start mDNS: {e}")
            raise

    async def stop(self):
        """Stop the mDNS service."""
        self._running = False

        if self._browser:
            try:
                self._browser.cancel()
            except Exception:
                pass
            self._browser = None

        if self._publisher:
            try:
                self._publisher.close()
            except Exception:
                pass
            self._publisher = None

        if self._zeroconf:
            try:
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None

        self._discovered.clear()

    def publish(self, port: int = None, name: str = None) -> bool:
        """Publish this service via mDNS.

        Args:
            port: Port to advertise (default: 8080)
            name: Service name (default: agent-smith-{port})

        Returns:
            True if publishing succeeded
        """
        if not self._zeroconf:
            return False

        port = port or self.DEFAULT_PORT
        name = name or f"{self.service_name}-{port}"

        try:
            import zeroconf as zc

            desc = {"path": "/"}
            service_info = zc.ServiceInfo(
                type_=self.SERVICE_TYPE,
                name=f"{name}.{self.SERVICE_TYPE}",
                server=f"{name}.local.",
                port=port,
                properties=desc,
            )

            self._zeroconf.register_service(service_info)
            self._publisher = service_info
            return True

        except Exception as e:
            print(f"Failed to publish mDNS service: {e}")
            return False

    def unpublish(self):
        """Unpublish this service."""
        if self._publisher and self._zeroconf:
            try:
                self._zeroconf.unregister_service(self._publisher)
                self._publisher = None
            except Exception as e:
                print(f"Failed to unpublish mDNS service: {e}")

    def start_discovery(self):
        """Start discovering services."""
        if not self._zeroconf:
            return

        try:
            import zeroconf as zc

            class ServiceListener(zc.ServiceListener):
                def __init__(inner_self, mdns: MDNSService):
                    inner_self._mdns = mdns

                def add_service(inner_self, zc: zc.Zeroconf, type_: str, name: str):
                    info = zc.get_service_info(type_, name)
                    if info:
                        service = DiscoveredService(
                            name=name.replace(f".{type_}", ""),
                            host=info.server,
                            port=info.port,
                            service_type=type_,
                            properties=dict(info.properties) if info.properties else {},
                        )
                        inner_self._mdns._discovered[name] = service
                        for listener in inner_self._mdns._listeners:
                            try:
                                listener(service)
                            except Exception:
                                pass

                def remove_service(inner_self, zc: zc.Zeroconf, type_: str, name: str):
                    if name in inner_self._mdns._discovered:
                        del inner_self._mdns._discovered[name]

                def update_service(inner_self, zc: zc.Zeroconf, type_: str, name: str):
                    inner_self.add_service(zc, type_, name)

            self._listener = ServiceListener(self)
            self._browser = zc.ServiceBrowser(
                self._zeroconf,
                self.SERVICE_TYPE,
                self._listener,
            )

        except Exception as e:
            print(f"Failed to start mDNS discovery: {e}")

    def stop_discovery(self):
        """Stop discovering services."""
        if self._browser:
            try:
                self._browser.cancel()
            except Exception:
                pass
            self._browser = None
        self._listener = None

    def add_listener(self, callback: Callable[[DiscoveredService], None]):
        """Add a listener for discovered services."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[DiscoveredService], None]):
        """Remove a listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def get_discovered(self) -> list[DiscoveredService]:
        """Get list of discovered services."""
        return list(self._discovered.values())

    def get_service(self, name: str) -> Optional[DiscoveredService]:
        """Get a specific discovered service by name."""
        for service in self._discovered.values():
            if name in service.name or service.name in name:
                return service
        return None


class MDNSManager:
    """Manager for mDNS services across the application."""

    def __init__(self):
        self._services: dict[str, MDNSService] = {}
        self._running = False

    async def start(self):
        """Start the mDNS manager."""
        self._running = True

    async def stop(self):
        """Stop the mDNS manager."""
        self._running = False
        for service in list(self._services.values()):
            await service.stop()
        self._services.clear()

    def get_or_create(self, name: str = "default") -> MDNSService:
        """Get or create an mDNS service."""
        if name not in self._services:
            self._services[name] = MDNSService(service_name=name)
        return self._services[name]

    async def publish(self, name: str = "default", port: int = None) -> bool:
        """Publish a service."""
        service = self.get_or_create(name)
        if not service._zeroconf:
            await service.start()
        return service.publish(port)

    def discover(self, name: str = "default") -> MDNSService:
        """Start discovering services."""
        service = self.get_or_create(name)
        if not service._zeroconf:
            import asyncio

            asyncio.create_task(service.start())
        service.start_discovery()
        return service

    def get_discovered(self, name: str = "default") -> list[DiscoveredService]:
        """Get discovered services."""
        service = self._services.get(name)
        if service:
            return service.get_discovered()
        return []


_default_manager: Optional[MDNSManager] = None


def get_manager() -> MDNSManager:
    """Get the default mDNS manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = MDNSManager()
    return _default_manager


async def publish_service(port: int = 8080, name: str = None) -> bool:
    """Quick helper to publish a service."""
    manager = get_manager()
    await manager.start()
    return await manager.publish("default", port)


def discover_services() -> list[DiscoveredService]:
    """Quick helper to discover services."""
    manager = get_manager()
    service = manager.discover("default")
    return service.get_discovered()
