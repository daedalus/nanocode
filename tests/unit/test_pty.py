"""Tests for PTY functionality."""

import pytest
import asyncio
from nanocode.pty import PtyManager, PtyStatus


@pytest.mark.asyncio
async def test_pty_create():
    """Test creating a PTY session."""
    info = await PtyManager.create(
        command="/bin/bash",
        args=["-c", "echo hello"],
        title="test",
        cwd="/tmp",
    )

    assert info is not None
    assert info.title == "test"
    assert info.command == "/bin/bash"
    assert info.status == PtyStatus.RUNNING
    assert info.pid > 0

    await asyncio.sleep(0.2)
    data = PtyManager.read_buffer(info.id)
    assert "hello" in data

    await PtyManager.remove(info.id)


@pytest.mark.asyncio
async def test_pty_list():
    """Test listing PTY sessions."""
    info1 = await PtyManager.create(args=["-c", "sleep 10"])
    info2 = await PtyManager.create(args=["-c", "sleep 10"])

    sessions = PtyManager.list()
    assert len(sessions) >= 2

    await PtyManager.remove(info1.id)
    await PtyManager.remove(info2.id)


@pytest.mark.asyncio
async def test_pty_write():
    """Test writing to a PTY session."""
    info = await PtyManager.create(args=["-c", "cat"])

    await PtyManager.write(info.id, "test input\n")
    await asyncio.sleep(0.2)

    data = PtyManager.read_buffer(info.id)
    assert "test input" in data

    await PtyManager.remove(info.id)


@pytest.mark.asyncio
async def test_pty_resize():
    """Test resizing a PTY terminal."""
    info = await PtyManager.create()

    await PtyManager.resize(info.id, 80, 24)
    await PtyManager.resize(info.id, 120, 40)

    info2 = PtyManager.get(info.id)
    assert info2.id == info.id

    await PtyManager.remove(info.id)


@pytest.mark.asyncio
async def test_pty_get():
    """Test getting PTY session info."""
    info = await PtyManager.create(args=["-c", "echo test"])

    retrieved = PtyManager.get(info.id)
    assert retrieved is not None
    assert retrieved.id == info.id
    assert retrieved.command == "/bin/bash"

    await PtyManager.remove(info.id)


@pytest.mark.asyncio
async def test_pty_remove():
    """Test removing a PTY session."""
    info = await PtyManager.create(args=["-c", "sleep 10"])

    await PtyManager.remove(info.id)

    retrieved = PtyManager.get(info.id)
    assert retrieved is None or retrieved.status == PtyStatus.EXITED
