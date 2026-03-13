"""Tests for event bus functionality."""

import pytest
from agent_smith.bus import (
    EventBus,
    Event,
    EventType,
    get_event_bus,
    subscribe,
    publish,
    once,
    define_event,
)


def test_event_creation():
    """Test creating an event."""
    event = Event(type="test.event", properties={"key": "value"})
    assert event.type == "test.event"
    assert event.properties == {"key": "value"}


def test_event_bus_singleton():
    """Test that event bus is a singleton."""
    bus1 = EventBus()
    bus2 = EventBus()
    assert bus1 is bus2


def test_subscribe_and_publish():
    """Test basic subscribe and publish."""
    bus = EventBus()
    bus.reset()

    received = []

    def handler(event):
        received.append(event)

    bus.subscribe("test.event", handler)
    bus.publish(Event(type="test.event", properties={"data": "hello"}))

    assert len(received) == 1
    assert received[0].type == "test.event"
    assert received[0].properties["data"] == "hello"


def test_unsubscribe():
    """Test unsubscribe functionality."""
    bus = EventBus()
    bus.reset()

    received = []

    def handler(event):
        received.append(event)

    unsubscribe = bus.subscribe("test.event", handler)
    bus.publish(Event(type="test.event"))
    assert len(received) == 1

    unsubscribe()
    bus.publish(Event(type="test.event"))
    assert len(received) == 1


def test_wildcard_subscription():
    """Test wildcard subscription catches all events."""
    bus = EventBus()
    bus.reset()

    received = []

    def handler(event):
        received.append(event)

    bus.subscribe("*", handler)
    bus.publish(Event(type="event.one"))
    bus.publish(Event(type="event.two"))
    bus.publish(Event(type="event.three"))

    assert len(received) == 3


def test_multiple_subscribers():
    """Test multiple subscribers to same event."""
    bus = EventBus()
    bus.reset()

    received1 = []
    received2 = []

    bus.subscribe("test.event", lambda e: received1.append(e))
    bus.subscribe("test.event", lambda e: received2.append(e))

    bus.publish(Event(type="test.event", properties={"value": 42}))

    assert len(received1) == 1
    assert len(received2) == 1
    assert received1[0].properties["value"] == 42


def test_once_subscription():
    """Test subscription that fires only once."""
    bus = EventBus()
    bus.reset()

    received = []

    def handler(event):
        received.append(event)

    bus.once("test.event", handler)
    bus.publish(Event(type="test.event"))
    bus.publish(Event(type="test.event"))

    assert len(received) == 1


def test_event_history():
    """Test event history tracking."""
    bus = EventBus()
    bus.reset()
    bus._max_history = 5

    for i in range(10):
        bus.publish(Event(type=f"event.{i}"))

    history = bus.get_history(limit=3)
    assert len(history) == 3
    assert history[0].type == "event.7"
    assert history[2].type == "event.9"


def test_event_history_filter():
    """Test filtering event history by type."""
    bus = EventBus()
    bus.reset()

    bus.publish(Event(type="type.a"))
    bus.publish(Event(type="type.b"))
    bus.publish(Event(type="type.a"))
    bus.publish(Event(type="type.a"))

    history = bus.get_history(event_type="type.a")
    assert len(history) == 3


def test_clear_history():
    """Test clearing event history."""
    bus = EventBus()
    bus.reset()

    bus.publish(Event(type="test.event"))
    assert len(bus.get_history()) == 1

    bus.clear_history()
    assert len(bus.get_history()) == 0


def test_unsubscribe_all():
    """Test unsubscribing all from specific type."""
    bus = EventBus()
    bus.reset()

    bus.subscribe("test.event", lambda e: None)
    bus.subscribe("test.event", lambda e: None)
    bus.subscribe("other.event", lambda e: None)

    assert bus.get_subscribers("test.event") == 2

    bus.unsubscribe_all("test.event")
    assert bus.get_subscribers("test.event") == 0
    assert bus.get_subscribers("other.event") == 1


def test_global_functions():
    """Test global convenience functions."""
    get_event_bus().reset()

    received = []

    subscribe("global.event", lambda e: received.append(e))
    publish(Event(type="global.event", properties={"test": True}))

    assert len(received) == 1


def test_event_types_enum():
    """Test using EventType enum."""
    bus = EventBus()
    bus.reset()

    received = []
    bus.subscribe(EventType.SESSION_CREATED.value, lambda e: received.append(e))

    bus.publish(Event(type=EventType.SESSION_CREATED.value, properties={"session_id": "abc123"}))

    assert len(received) == 1
    assert received[0].properties["session_id"] == "abc123"


def test_define_event():
    """Test defining custom event type."""

    @dataclass
    class CustomProperties:
        name: str
        value: int

    event_def = define_event("custom.event", CustomProperties)
    assert event_def.type == "custom.event"


def test_get_subscribers_count():
    """Test getting subscriber count."""
    bus = EventBus()
    bus.reset()

    assert bus.get_subscribers("new.event") == 0

    bus.subscribe("new.event", lambda e: None)
    assert bus.get_subscribers("new.event") == 1

    bus.subscribe("new.event", lambda e: None)
    assert bus.get_subscribers("new.event") == 2


def test_publish_with_no_subscribers():
    """Test publishing to event with no subscribers doesn't error."""
    bus = EventBus()
    bus.reset()

    # Should not raise
    result = bus.publish(Event(type="no.subscribers"))
    assert result == []


def test_callback_exception_handling():
    """Test that exceptions in callbacks don't break publishing."""
    bus = EventBus()
    bus.reset()

    received = []

    def bad_handler(event):
        raise ValueError("Test error")

    def good_handler(event):
        received.append(event)

    bus.subscribe("error.event", bad_handler)
    bus.subscribe("error.event", good_handler)

    bus.publish(Event(type="error.event"))

    assert len(received) == 1  # Should still receive the event


from dataclasses import dataclass


def test_async_publish():
    """Test async callback handling."""
    import asyncio

    bus = EventBus()
    bus.reset()

    results = []

    async def async_handler(event):
        await asyncio.sleep(0.01)
        results.append(event)

    bus.subscribe("async.event", async_handler)
    bus.publish(Event(type="async.event"))

    # Callbacks are not awaited in publish, use publish_sync for that
    assert len(results) == 0

    # Now test sync version
    results2 = []
    bus.subscribe("sync.event", lambda e: results2.append(e))
    bus.publish_sync(Event(type="sync.event"))
    assert len(results2) == 1


def test_buses_independence():
    """Test that creating new EventBus instances work independently when reset."""
    bus1 = EventBus()
    bus2 = EventBus()

    # They share state, but we can reset
    bus1.reset()
    bus2.reset()

    bus1.subscribe("unique.event", lambda e: None)

    # Both point to same singleton, so this will have subscriber
    assert bus2.get_subscribers("unique.event") == 1
