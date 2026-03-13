"""Effect system - Reactive programming primitives."""

import asyncio
import threading
from typing import Any, Callable, Generic, TypeVar, Optional, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from weakref import WeakSet
import logging


logger = logging.getLogger(__name__)

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


class Signal:
    """A simple signal that can be triggered and waited on."""

    def __init__(self):
        self._resolves: list[Callable] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def trigger(self):
        """Trigger the signal."""
        for resolve in self._resolves:
            resolve()
        self._resolves.clear()

    async def wait(self) -> None:
        """Wait for the signal to be triggered."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        future = self._loop.create_future()

        def resolve():
            if not future.done():
                future.set_result(None)

        self._resolves.append(resolve)

        try:
            await future
        except asyncio.CancelledError:
            self._resolves.remove(resolve)
            raise

    def wait_sync(self, timeout: float = None) -> bool:
        """Wait synchronously for the signal."""
        event = threading.Event()

        def resolve():
            event.set()

        self._resolves.append(resolve)

        return event.wait(timeout=timeout)


class Trigger:
    """A trigger that can fire once and be awaited."""

    def __init__(self):
        self._future: Optional[asyncio.Future] = None

    def fire(self):
        """Fire the trigger."""
        if self._future is not None and not self._future.done():
            self._future.set_result(True)

    def reset(self):
        """Reset the trigger for reuse."""
        loop = asyncio.get_event_loop()
        self._future = loop.create_future()

    async def wait(self) -> bool:
        """Wait for the trigger to fire."""
        if self._future is None:
            self.reset()
        return await self._future

    def __await__(self):
        return self.wait().__await__()


class Ref(Generic[T]):
    """A mutable reference with change tracking."""

    def __init__(self, initial_value: T):
        self._value = initial_value
        self._callbacks: list[Callable[[T, T], None]] = []

    @property
    def value(self) -> T:
        return self._value

    @value.setter
    def value(self, new_value: T):
        old_value = self._value
        self._value = new_value
        for callback in self._callbacks:
            callback(old_value, new_value)

    def subscribe(self, callback: Callable[[T, T], None]) -> Callable[[], None]:
        """Subscribe to changes."""
        self._callbacks.append(callback)

        def unsubscribe():
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    def get(self) -> T:
        return self._value

    def set(self, value: T):
        self.value = value

    def update(self, fn: Callable[[T], T]):
        """Apply a function to the current value."""
        self.value = fn(self._value)


class Observable(Generic[T]):
    """An observable that can be subscribed to."""

    def __init__(self, value: Optional[T] = None):
        self._value = value
        self._subscribers: list[Callable[[T], Any]] = []

    @property
    def value(self) -> Optional[T]:
        return self._value

    def subscribe(self, callback: Callable[[T], Any]) -> Callable[[], None]:
        """Subscribe to the observable."""
        self._subscribers.append(callback)

        def unsubscribe():
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def emit(self, value: T):
        """Emit a new value to all subscribers."""
        self._value = value
        for subscriber in self._subscribers:
            try:
                result = subscriber(value)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                logger.error(f"Error in subscriber: {e}")

    def __call__(self, value: T):
        self.emit(value)


class Computed(Generic[T]):
    """A computed value that auto-updates when dependencies change."""

    def __init__(self, compute_fn: Callable[[], T], dependencies: list[Observable] = None):
        self._compute_fn = compute_fn
        self._dependencies = dependencies or []
        self._value: Optional[T] = None
        self._subscribers: list[Callable[[T], Any]] = []
        self._disposers: list[Callable[[], None]] = []

        self._setup_dependencies()
        self._recompute()

    def _setup_dependencies(self):
        """Setup dependency tracking."""
        for dep in self._dependencies:

            def make_callback(dep):
                def callback(_):
                    self._recompute()

                return callback

            unsub = dep.subscribe(make_callback(dep))
            self._disposers.append(unsub)

    def _recompute(self):
        """Recompute the value."""
        try:
            new_value = self._compute_fn()
            old_value = self._value
            self._value = new_value

            if old_value != new_value:
                for subscriber in self._subscribers:
                    try:
                        subscriber(new_value)
                    except Exception as e:
                        logger.error(f"Error in computed subscriber: {e}")
        except Exception as e:
            logger.error(f"Error computing value: {e}")

    @property
    def value(self) -> T:
        return self._value

    def subscribe(self, callback: Callable[[T], Any]) -> Callable[[], None]:
        """Subscribe to changes."""
        self._subscribers.append(callback)

        def unsubscribe():
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def dispose(self):
        """Dispose of the computed value."""
        for disposer in self._disposers:
            disposer()
        self._disposers.clear()


class Effect:
    """An effect that runs when its dependencies change."""

    def __init__(self, fn: Callable[[], Any], dependencies: list[Observable] = None):
        self._fn = fn
        self._dependencies = dependencies or []
        self._disposers: list[Callable[[], None]] = []
        self._running = False

        self._setup_dependencies()

    def _setup_dependencies(self):
        """Setup dependency tracking."""
        for dep in self._dependencies:

            def make_callback(dep):
                def callback(new_value):
                    self.run()

                return callback

            unsub = dep.subscribe(make_callback(dep))
            self._disposers.append(unsub)

    def run(self):
        """Run the effect."""
        self._running = True
        try:
            result = self._fn()
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception as e:
            logger.error(f"Error running effect: {e}")
        finally:
            self._running = False

    def dispose(self):
        """Dispose of the effect."""
        for disposer in self._disposers:
            disposer()
        self._disposers.clear()


class Lazy(Generic[T]):
    """A lazily evaluated value."""

    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._value: Optional[T] = None
        self._evaluated = False

    @property
    def value(self) -> T:
        if not self._evaluated:
            self._value = self._factory()
            self._evaluated = True
        return self._value

    def reset(self):
        """Reset the lazy value."""
        self._value = None
        self._evaluated = False


class Deferred(Generic[T]):
    """A deferred value that can be resolved later."""

    def __init__(self):
        self._future: Optional[asyncio.Future] = None

    def resolve(self, value: T):
        """Resolve the deferred value."""
        if self._future is not None and not self._future.done():
            self._future.set_result(value)

    def reject(self, error: Exception):
        """Reject the deferred value."""
        if self._future is not None and not self._future.done():
            self._future.set_exception(error)

    async def wait(self) -> T:
        """Wait for the deferred value."""
        if self._future is None:
            loop = asyncio.get_event_loop()
            self._future = loop.create_future()
        return await self._future

    @property
    def done(self) -> bool:
        return self._future is not None and self._future.done()

    @property
    def result(self) -> Optional[T]:
        if self._future is not None and self._future.done():
            return self._future.result()
        return None


class Resource(Generic[T]):
    """A resource that must be disposed."""

    def __init__(self, acquire: Callable[[], T], release: Callable[[T], None] = None):
        self._acquire = acquire
        self._release = release
        self._value: Optional[T] = None
        self._acquired = False

    def __enter__(self) -> T:
        self._value = self._acquire()
        self._acquired = True
        return self._value

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._acquired and self._release is not None:
            self._release(self._value)
            self._acquired = False

    @property
    def value(self) -> T:
        if not self._acquired:
            self._value = self._acquire()
            self._acquired = True
        return self._value


class Cache(Generic[T]):
    """A simple cache with TTL."""

    def __init__(self, ttl: float = 60.0):
        self._cache: dict[str, tuple[T, float]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[T]:
        """Get a value from cache."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            import time

            if time.time() - timestamp < self._ttl:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: T):
        """Set a value in cache."""
        import time

        self._cache[key] = (value, time.time())

    def delete(self, key: str):
        """Delete a value from cache."""
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        """Clear the cache."""
        self._cache.clear()


class Atomic(Generic[T]):
    """An atomic value with thread-safe operations."""

    def __init__(self, initial_value: T):
        self._value = initial_value
        self._lock = threading.Lock()

    @property
    def value(self) -> T:
        with self._lock:
            return self._value

    @value.setter
    def value(self, new_value: T):
        with self._lock:
            self._value = new_value

    def update(self, fn: Callable[[T], T]) -> T:
        """Atomically update the value."""
        with self._lock:
            new_value = fn(self._value)
            self._value = new_value
            return new_value

    def compare_and_swap(self, expected: T, new_value: T) -> bool:
        """Compare and swap operation."""
        with self._lock:
            if self._value == expected:
                self._value = new_value
                return True
            return False


class State(Generic[T]):
    """A simple state container with history."""

    def __init__(self, initial_value: T):
        self._history: list[T] = [initial_value]
        self._index = 0

    @property
    def value(self) -> T:
        return self._history[self._index]

    def set(self, value: T):
        """Set a new value, truncating future history."""
        self._history = self._history[: self._index + 1]
        self._history.append(value)
        self._index += 1

    def undo(self) -> Optional[T]:
        """Go back one state."""
        if self._index > 0:
            self._index -= 1
            return self.value
        return None

    def redo(self) -> Optional[T]:
        """Go forward one state."""
        if self._index < len(self._history) - 1:
            self._index += 1
            return self.value
        return None

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._history) - 1


def signal():
    """Create a simple signal that can be triggered and waited on."""
    return Signal()


def trigger() -> Trigger:
    """Create a fire-and-forget trigger."""
    return Trigger()


def ref(initial_value: T) -> Ref[T]:
    """Create a mutable reference."""
    return Ref(initial_value)


def observable(initial_value: T = None) -> Observable[T]:
    """Create an observable."""
    return Observable(initial_value)


def computed(compute_fn: Callable[[], T], dependencies: list[Observable] = None) -> Computed[T]:
    """Create a computed value."""
    return Computed(compute_fn, dependencies)


def effect(fn: Callable[[], Any], dependencies: list[Observable] = None) -> Effect:
    """Create an effect."""
    return Effect(fn, dependencies)


def lazy(factory: Callable[[], T]) -> Lazy[T]:
    """Create a lazy value."""
    return Lazy(factory)


def deferred() -> Deferred[T]:
    """Create a deferred value."""
    return Deferred()
