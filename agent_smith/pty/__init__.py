"""PTY (Pseudo-Terminal) support for nanocode."""

import os
import pty
import select
import subprocess
import fcntl
import termios
import struct
import uuid
import asyncio
import threading
import warnings
from typing import Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


class PtyStatus(Enum):
    RUNNING = "running"
    EXITED = "exited"


@dataclass
class PtyInfo:
    """Information about a PTY session."""

    id: str
    title: str
    command: str
    args: list[str]
    cwd: str
    status: PtyStatus
    pid: int
    exit_code: Optional[int] = None


@dataclass
class PtySession:
    """Active PTY session."""

    info: PtyInfo
    master_fd: int
    process: Optional[subprocess.Popen]
    buffer: str = ""
    buffer_cursor: int = 0
    cursor: int = 0
    subscribers: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PtyManager:
    """Manages PTY sessions."""

    BUFFER_LIMIT = 1024 * 1024 * 2  # 2MB
    sessions: dict[str, PtySession] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        command: str = None,
        args: list[str] = None,
        cwd: str = None,
        title: str = None,
        env: dict = None,
    ) -> PtyInfo:
        """Create a new PTY session."""
        command = command or cls._get_shell()
        args = args or []
        cwd = cwd or os.getcwd()

        if command.endswith("sh") and "-l" not in args:
            args.append("-l")

        # Set up environment
        full_env = os.environ.copy()
        full_env.update(env or {})
        full_env["TERM"] = "xterm-256color"
        full_env["AGENT_SMITH_TERMINAL"] = "1"

        # Create pseudo-terminal
        master_fd, slave_fd = pty.openpty()

        # Fork process
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            pid = os.fork()

        if pid == 0:
            # Child process
            os.close(master_fd)
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            os.close(slave_fd)

            os.chdir(cwd)
            os.execvpe(command, [command] + args, full_env)
        else:
            # Parent process
            os.close(slave_fd)

            # Set non-blocking mode
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            session_id = str(uuid.uuid4())
            info = PtyInfo(
                id=session_id,
                title=title or f"Terminal {session_id[-4:]}",
                command=command,
                args=args,
                cwd=cwd,
                status=PtyStatus.RUNNING,
                pid=pid,
            )

            session = PtySession(
                info=info,
                master_fd=master_fd,
                process=None,  # Process managed by pid, not subprocess
            )

            async with cls._lock:
                cls.sessions[session_id] = session

            # Start reader thread
            cls._start_reader(session_id)

            return info

    @classmethod
    def _get_shell(cls) -> str:
        """Get the preferred shell."""
        return os.environ.get("SHELL", "/bin/bash")

    @classmethod
    def _start_reader(cls, session_id: str):
        """Start a background thread to read PTY output."""

        def reader():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            while True:
                session = cls.sessions.get(session_id)
                if not session:
                    break

                try:
                    ready, _, _ = select.select([session.master_fd], [], [], 0.1)
                    if ready:
                        try:
                            data = os.read(session.master_fd, 4096)
                            if data:
                                loop.run_until_complete(cls._handle_output(session_id, data))
                            else:
                                break
                        except OSError:
                            break
                except Exception:
                    break

                # Check if process exited
                try:
                    pid, status = os.waitpid(session.info.pid, os.WNOHANG)
                    if pid != 0:
                        exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                        loop.run_until_complete(cls._handle_exit(session_id, exit_code))
                        break
                except ChildProcessError:
                    break

            loop.close()

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()

    @classmethod
    async def _handle_output(cls, session_id: str, data: bytes):
        """Handle PTY output data."""
        session = cls.sessions.get(session_id)
        if not session:
            return

        text = data.decode("utf-8", errors="replace")
        session.cursor += len(text)
        session.buffer += text

        # Trim buffer if too large
        if len(session.buffer) > cls.BUFFER_LIMIT:
            excess = len(session.buffer) - cls.BUFFER_LIMIT
            session.buffer = session.buffer[excess:]
            session.buffer_cursor += excess

    @classmethod
    async def _handle_exit(cls, session_id: str, exit_code: int):
        """Handle PTY process exit."""
        session = cls.sessions.get(session_id)
        if not session:
            return

        session.info.status = PtyStatus.EXITED
        session.info.exit_code = exit_code

    @classmethod
    async def write(cls, session_id: str, data: str):
        """Write data to PTY."""
        session = cls.sessions.get(session_id)
        if not session or session.info.status != PtyStatus.RUNNING:
            return

        try:
            os.write(session.master_fd, data.encode("utf-8"))
        except OSError:
            pass

    @classmethod
    async def resize(cls, session_id: str, cols: int, rows: int):
        """Resize PTY terminal."""
        session = cls.sessions.get(session_id)
        if not session or session.info.status != PtyStatus.RUNNING:
            return

        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.fcntl(session.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    @classmethod
    def get(cls, session_id: str) -> Optional[PtyInfo]:
        """Get PTY session info."""
        session = cls.sessions.get(session_id)
        return session.info if session else None

    @classmethod
    def list(cls) -> list[PtyInfo]:
        """List all PTY sessions."""
        return [s.info for s in cls.sessions.values()]

    @classmethod
    async def remove(cls, session_id: str):
        """Remove/kill a PTY session."""
        session = cls.sessions.get(session_id)
        if not session:
            return

        try:
            os.kill(session.info.pid, 9)
        except OSError:
            pass

        try:
            os.close(session.master_fd)
        except OSError:
            pass

        async with cls._lock:
            cls.sessions.pop(session_id, None)

    @classmethod
    def read_buffer(cls, session_id: str, cursor: int = 0, length: int = None) -> str:
        """Read from session buffer."""
        session = cls.sessions.get(session_id)
        if not session:
            return ""

        start = session.buffer_cursor
        end = session.cursor

        if cursor >= 0:
            offset = max(0, cursor - start)
        else:
            offset = 0

        if offset >= len(session.buffer):
            return ""

        data = session.buffer[offset:]
        if length:
            data = data[:length]

        return data
