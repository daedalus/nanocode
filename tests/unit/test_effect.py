"""Tests for effect system functionality."""

import pytest
import asyncio
import time
from agent_smith.effect import (
    Signal,
    Trigger,
    Ref,
    Observable,
    Computed,
    Effect,
    Lazy,
    Deferred,
    Resource,
    Cache,
    Atomic,
    State,
    signal,
    trigger,
    ref,
    observable,
    computed,
    effect,
    lazy,
    deferred,
)


def test_signal_trigger():
    """Test signal trigger and wait."""
    sig = Signal()
    results = []

    async def waiter():
        await sig.wait()
        results.append("done")

    async def main():
        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        sig.trigger()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(main())
    assert "done" in results


def test_signal_wait_sync():
    """Test synchronous wait on signal."""
    sig = Signal()

    def trigger_after():
        time.sleep(0.01)
        sig.trigger()

    import threading

    t = threading.Thread(target=trigger_after)
    t.start()

    result = sig.wait_sync(timeout=1.0)
    t.join()

    assert result is True


def test_trigger_fire():
    """Test trigger firing."""
    trig = Trigger()
    results = []

    async def waiter():
        result = await trig.wait()
        results.append("fired")

    async def main():
        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        trig.fire()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(main())
    assert "fired" in results


def test_ref_get_set():
    """Test ref get and set."""
    r = ref(10)
    assert r.value == 10
    assert r.get() == 10

    r.set(20)
    assert r.value == 20

    r.value = 30
    assert r.value == 30


def test_ref_update():
    """Test ref update function."""
    r = ref(10)
    r.update(lambda x: x * 2)
    assert r.value == 20


def test_ref_subscribe():
    """Test ref subscribe to changes."""
    r = ref(0)
    changes = []

    def callback(old, new):
        changes.append((old, new))

    r.subscribe(callback)
    r.set(10)
    r.set(20)

    assert len(changes) == 2
    assert changes[0] == (0, 10)
    assert changes[1] == (10, 20)


def test_observable_emit():
    """Test observable emit."""
    obs = observable(0)
    received = []

    def subscriber(value):
        received.append(value)

    obs.subscribe(subscriber)
    obs.emit(1)
    obs.emit(2)
    obs.emit(3)

    assert received == [1, 2, 3]


def test_observable_unsubscribe():
    """Test observable unsubscribe."""
    obs = observable(0)
    received = []

    def subscriber(value):
        received.append(value)

    unsub = obs.subscribe(subscriber)
    obs.emit(1)
    unsub()
    obs.emit(2)

    assert received == [1]


def test_computed_value():
    """Test computed value."""
    counter = observable(0)

    def compute():
        return counter.value * 2

    comp = computed(compute, [counter])

    assert comp.value == 0
    counter.emit(5)
    assert comp.value == 10


def test_computed_subscribes_to_deps():
    """Test computed subscribes to dependencies."""
    counter = observable(0)
    changes = []

    def compute():
        return counter.value * 2

    comp = computed(compute, [counter])
    comp.subscribe(lambda v: changes.append(v))

    counter.emit(5)
    counter.emit(10)

    assert 10 in changes
    assert 20 in changes


def test_effect_runs_on_change():
    """Test effect runs when dependency changes."""
    counter = observable(0)
    run_count = []

    def effect_fn():
        run_count.append(counter.value)

    eff = effect(effect_fn, [counter])
    eff.run()

    assert run_count == [0]

    counter.emit(1)
    assert run_count == [0, 1]


def test_lazy_evaluation():
    """Test lazy evaluation."""
    call_count = 0

    def factory():
        nonlocal call_count
        call_count += 1
        return 42

    lz = lazy(factory)

    assert call_count == 0
    assert lz.value == 42
    assert call_count == 1
    assert lz.value == 42
    assert call_count == 1


def test_lazy_reset():
    """Test lazy reset."""
    call_count = 0

    def factory():
        nonlocal call_count
        call_count += 1
        return 42

    lz = lazy(factory)
    _ = lz.value
    lz.reset()
    _ = lz.value

    assert call_count == 2


def test_deferred_resolve():
    """Test deferred value resolution."""
    df = deferred()
    results = []

    async def waiter():
        results.append(await df.wait())

    async def main():
        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.01)
        df.resolve("success")
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(main())
    assert results == ["success"]


def test_deferred_reject():
    """Test deferred value rejection."""
    df = deferred()
    results = []

    async def waiter():
        try:
            await df.wait()
        except Exception as e:
            results.append(str(e))

    async def main():
        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.01)
        df.reject(ValueError("test error"))
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(main())
    assert "test error" in results[0]


def test_resource_context_manager():
    """Test resource as context manager."""
    acquired = []
    released = []

    def acquire():
        acquired.append(True)
        return "resource"

    def release(res):
        released.append(res)

    with Resource(acquire, release) as res:
        assert res == "resource"
        assert len(acquired) == 1

    assert len(released) == 1
    assert released[0] == "resource"


def test_cache_ttl():
    """Test cache with TTL."""
    cache = Cache(ttl=0.1)

    cache.set("key", "value")
    assert cache.get("key") == "value"

    time.sleep(0.15)
    assert cache.get("key") is None


def test_cache_delete():
    """Test cache delete."""
    cache = Cache()
    cache.set("key", "value")
    cache.delete("key")
    assert cache.get("key") is None


def test_atomic_value():
    """Test atomic value."""
    atomic = Atomic(10)

    assert atomic.value == 10

    atomic.value = 20
    assert atomic.value == 20


def test_atomic_update():
    """Test atomic update."""
    atomic = Atomic(10)

    result = atomic.update(lambda x: x * 2)

    assert result == 20
    assert atomic.value == 20


def test_atomic_compare_and_swap():
    """Test atomic compare and swap."""
    atomic = Atomic(10)

    assert atomic.compare_and_swap(10, 20) is True
    assert atomic.value == 20

    assert atomic.compare_and_swap(10, 30) is False
    assert atomic.value == 20


def test_state_undo():
    """Test state undo."""
    s = State(0)

    s.set(10)
    s.set(20)

    assert s.value == 20
    assert s.can_undo is True

    s.undo()
    assert s.value == 10


def test_state_redo():
    """Test state redo."""
    s = State(0)

    s.set(10)
    s.set(20)
    s.undo()

    assert s.can_redo is True

    s.redo()
    assert s.value == 20


def test_convenience_functions():
    """Test convenience functions."""
    s = signal()
    assert isinstance(s, Signal)

    t = trigger()
    assert isinstance(t, Trigger)

    r = ref(1)
    assert isinstance(r, Ref)

    o = observable(1)
    assert isinstance(o, Observable)

    l = lazy(lambda: 1)
    assert isinstance(l, Lazy)

    d = deferred()
    assert isinstance(d, Deferred)


def test_observable_callable():
    """Test observable is callable."""
    obs = observable(0)

    received = []
    obs.subscribe(lambda v: received.append(v))

    obs(5)
    assert received == [5]


def test_ref_update_via_set():
    """Test ref update via set method."""
    r = ref(0)
    r.set(5)
    assert r.value == 5
