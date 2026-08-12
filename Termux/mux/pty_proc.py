"""
PTY management.

Each pane owns one pseudoterminal pair:
    master fd — multiplexer reads/writes through this
    slave  fd — the child shell's stdin/stdout/stderr

The child is spawned with os.fork() + os.execve() in the slave's session,
making the slave the controlling terminal.  SIGWINCH is sent to notify the
child of size changes.

All pty operations are POSIX-only (Linux / macOS).
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import signal
import struct
import termios
import tty
from typing import Callable


class PtyProcess:
    """
    One pseudoterminal child process (shell).

    Usage:
        pty_proc = PtyProcess.spawn("/bin/bash", rows=24, cols=80)
        pty_proc.write(b"echo hello\n")
        data = pty_proc.read(4096)
        pty_proc.resize(30, 100)
        pty_proc.kill()
    """

    def __init__(self, master_fd: int, pid: int):
        self.master_fd = master_fd
        self.pid       = pid
        self._alive    = True

    @classmethod
    def spawn(
        cls,
        shell:  str,
        rows:   int,
        cols:   int,
        env:    dict | None = None,
        cwd:    str | None  = None,
    ) -> "PtyProcess":
        """
        Fork a child process attached to a new pty.

        The child becomes a new process group leader and session leader
        so that Ctrl-C is delivered only to the child.
        """
        if env is None:
            env = dict(os.environ)
            env["TERM"] = "xterm-256color"

        master_fd, slave_fd = pty.openpty()

        # Set initial window size on the slave before forking
        _set_winsize(slave_fd, rows, cols)

        pid = os.fork()
        if pid == 0:
            # Child
            try:
                os.close(master_fd)
                os.setsid()

                # Make slave the controlling terminal
                import fcntl as _fcntl
                _fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                if slave_fd > 2:
                    os.close(slave_fd)

                if cwd:
                    os.chdir(cwd)

                os.execve(shell, [shell], env)
            except Exception:
                os._exit(1)

        # Parent
        os.close(slave_fd)
        _set_nonblocking(master_fd)
        return cls(master_fd=master_fd, pid=pid)

    def read(self, n: int = 4096) -> bytes:
        """Read up to n bytes; returns b'' on EOF/error."""
        try:
            return os.read(self.master_fd, n)
        except (OSError, IOError) as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                self._alive = False
                return b""
            if exc.errno == errno.EAGAIN:
                return b""
            raise

    def write(self, data: bytes) -> int:
        """Write data to the pty master. Returns bytes written."""
        try:
            return os.write(self.master_fd, data)
        except (OSError, IOError) as exc:
            if exc.errno in (errno.EIO, errno.EBADF, errno.EPIPE):
                self._alive = False
                return 0
            raise

    def resize(self, rows: int, cols: int):
        """Notify the child of a terminal size change via TIOCSWINSZ."""
        try:
            _set_winsize(self.master_fd, rows, cols)
            os.kill(self.pid, signal.SIGWINCH)
        except (OSError, ProcessLookupError):
            pass

    def kill(self, sig: int = signal.SIGHUP):
        if self._alive:
            try:
                os.kill(self.pid, sig)
            except (ProcessLookupError, OSError):
                pass
            self._alive = False

    def wait(self) -> int:
        """Wait for the child to exit; returns its exit status."""
        try:
            _, status = os.waitpid(self.pid, os.WNOHANG)
            return os.WEXITSTATUS(status)
        except (ChildProcessError, OSError):
            return -1

    @property
    def alive(self) -> bool:
        if not self._alive:
            return False
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            if pid != 0:
                self._alive = False
                return False
        except (ChildProcessError, OSError):
            self._alive = False
            return False
        return True

    def fileno(self) -> int:
        return self.master_fd


def _set_winsize(fd: int, rows: int, cols: int):
    """Set terminal window size using TIOCSWINSZ ioctl."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _set_nonblocking(fd: int):
    """Put a file descriptor in non-blocking mode."""
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def get_terminal_size() -> tuple[int, int]:
    """Return (rows, cols) of the controlling terminal."""
    try:
        cols, rows = os.get_terminal_size()
        return rows, cols
    except OSError:
        return 24, 80
