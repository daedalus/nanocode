"""Event bus system for pub/sub messaging."""

import logging
from typing import Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum
from weakref import WeakSet
import asyncio


logger = logging.getLogger(__name__)


class EventType(Enum):
    """Event types enum for common events."""

    SESSION_CREATED = "session.created"
    SESSION_DELETED = "session.deleted"
    SESSION_UPDATED = "session.updated"
    TOOL_EXECUTED = "tool.executed"
    TOOL_ERROR = "tool.error"
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"
    AGENT_ERROR = "agent.error"
    SERVER_STARTED = "server.started"
    SERVER_STOPPED = "server.stopped"
    SERVER_ERROR = "server.error"
    CONFIG_CHANGED = "config.changed"
    PTY_CREATED = "pty.created"
    PTY_UPDATED = "pty.updated"
    PTY_EXITED = "pty.exited"
    PTY_DELETED = "pty.deleted"
    MCP_CONNECTED = "mcp.connected"
    MCP_DISCONNECTED = "mcp.disconnected"
    LSP_STARTED = "lsp.started"
    LSP_STOPPED = "lsp.stopped"


@dataclass
class Event:
    """Base event class."""

    type: str
    properties: dict = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


@dataclass
class BusEvent:
    """Typed event definition."""

    type: str
    properties_schema: Optional[type] = None


class EventBus:
    """Event bus for pub/sub messaging."""

    _instance: Optional["EventBus"] = None

    def __new__(cls) -> "EventBus":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._subscriptions: dict[str, list[Callable]] = {}
        self._wildcard_subscriptions: list[Callable] = []
        self._event_history: list[Event] = []
        self._max_history = 100
        self._initialized = True

    def reset(self):
        """Reset the event bus (useful for testing)."""
        self._subscriptions.clear()
        self._wildcard_subscriptions.clear()
        self._event_history.clear()

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Event], None],
    ) -> Callable[[], None]:
        """
        Subscribe to an event type.

        Returns an unsubscribe function.
        """
        if event_type == "*":
            self._wildcard_subscriptions.append(callback)
            logger.debug("Subscribed to wildcard events")
        else:
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = []
            self._subscriptions[event_type].append(callback)
            logger.debug(f"Subscribed to event: {event_type}")

        def unsubscribe():
            if event_type == "*":
                if callback in self._wildcard_subscriptions:
                    self._wildcard_subscriptions.remove(callback)
            else:
                if (
                    event_type in self._subscriptions
                    and callback in self._subscriptions[event_type]
                ):
                    self._subscriptions[event_type].remove(callback)
            logger.debug(f"Unsubscribed from event: {event_type}")

        return unsubscribe

    def once(
        self,
        event_type: str,
        callback: Callable[[Event], None],
    ) -> Callable[[], None]:
        """Subscribe to an event type for a single invocation."""

        def wrapped(event: Event):
            callback(event)
            unsubscribe()

        unsubscribe = self.subscribe(event_type, wrapped)
        return unsubscribe

    def publish(self, event: Event) -> list[Any]:
        """
        Publish an event to all subscribers.

        Returns a list of futures from async callbacks.
        """
        logger.debug(f"Publishing event: {event.type}")

        results = []
        pending = []

        # Notify specific subscribers
        if event.type in self._subscriptions:
            for callback in self._subscriptions[event.type]:
                try:
                    result = callback(event)
                    if asyncio.iscoroutine(result):
                        pending.append(result)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error in event callback for {event.type}: {e}")

        # Notify wildcard subscribers
        for callback in self._wildcard_subscriptions:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    pending.append(result)
                results.append(result)
            except Exception as e:
                logger.error(f"Error in wildcard event callback: {e}")

        # Add to history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Wait for async callbacks
        if pending:
            # Note: We don't await here to avoid blocking
            # Callers can use asyncio.gather if they need to wait
            pass

        return results

    def publish_sync(self, event: Event) -> list[Any]:
        """Publish an event synchronously, awaiting async callbacks."""
        logger.debug(f"Publishing event sync: {event.type}")

        results = []

        # Notify specific subscribers
        if event.type in self._subscriptions:
            for callback in self._subscriptions[event.type]:
                try:
                    result = callback(event)
                    if asyncio.iscoroutine(result):
                        # Run in new event loop if needed
                        try:
                            loop = asyncio.get_running_loop()
                            # Schedule and wait
                            import concurrent.futures

                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                future = pool.submit(asyncio.run, result)
                                results.append(future.result())
                        except RuntimeError:
                            results.append(asyncio.run(result))
                    else:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Error in event callback for {event.type}: {e}")

        # Notify wildcard subscribers
        for callback in self._wildcard_subscriptions:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    results.append(asyncio.run(result))
                else:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error in wildcard event callback: {e}")

        # Add to history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        return results

    def unsubscribe_all(self, event_type: Optional[str] = None):
        """Unsubscribe all callbacks for an event type, or all if None."""
        if event_type is None:
            self._subscriptions.clear()
            self._wildcard_subscriptions.clear()
            logger.debug("Unsubscribed from all events")
        elif event_type == "*":
            self._wildcard_subscriptions.clear()
            logger.debug("Unsubscribed from wildcard events")
        else:
            self._subscriptions.pop(event_type, None)
            logger.debug(f"Unsubscribed from event: {event_type}")

    def get_subscribers(self, event_type: str) -> int:
        """Get the number of subscribers for an event type."""
        specific = len(self._subscriptions.get(event_type, []))
        wildcard = len(self._wildcard_subscriptions)
        return specific + wildcard

    def get_history(self, event_type: Optional[str] = None, limit: int = 10) -> list[Event]:
        """Get event history, optionally filtered by type."""
        history = self._event_history

        if event_type:
            history = [e for e in history if e.type == event_type]

        return history[-limit:]

    def clear_history(self):
        """Clear event history."""
        self._event_history.clear()


# Global event bus instance
_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def subscribe(event_type: str, callback: Callable[[Event], None]) -> Callable[[], None]:
    """Subscribe to an event on the global bus."""
    return get_event_bus().subscribe(event_type, callback)


def once(event_type: str, callback: Callable[[Event], None]) -> Callable[[], None]:
    """Subscribe once to an event on the global bus."""
    return get_event_bus().once(event_type, callback)


def publish(event: Event) -> list[Any]:
    """Publish an event on the global bus."""
    return get_event_bus().publish(event)


def publish_sync(event: Event) -> list[Any]:
    """Publish an event synchronously on the global bus."""
    return get_event_bus().publish_sync(event)


def define_event(type: str, properties_schema: type = None) -> BusEvent:
    """Define a new event type."""
    return BusEvent(type=type, properties_schema=properties_schema)
