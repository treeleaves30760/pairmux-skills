"""Live-terminal facts for the eval fixtures, on POSIX and native Windows.

Setup copies this file next to the fixtures that record which live terminal they ran in. On POSIX
every function returns exactly what the fixtures always recorded (os.getppid, os.getsid,
os.ttyname, /dev/tty, termios). Windows has no sessions or tty names, so the same facts come from
the console the process is attached to (a pairmux built-in terminal is one ConPTY console):

* ppid -- the nearest ancestor that is not a Python launcher (py.exe or a venv redirector sits
  between a shell and the real interpreter on Windows), i.e. the shell that ran the command;
* sid  -- the session leader analogue: the top-most ancestor still attached to this console,
  which is the terminal's shell;
* tty  -- "console:<sid>", a stable name for that console.
"""

from __future__ import annotations

import os
import re
import sys
import time

IS_WINDOWS = os.name == "nt"
_LAUNCHER = re.compile(r"(?:pyw?|pythonw?(?:3(?:\.\d+)?)?(?:_d)?)\.exe")


def event_ns() -> int:
    """A system-wide monotonic timestamp that orders fixture events across processes.

    POSIX: time.monotonic_ns(), exactly as the fixtures always recorded. Windows before Python
    3.13 backs monotonic() with GetTickCount64 (~15.6 ms ticks), so back-to-back events would tie
    and fail the checks' strict ordering; perf_counter_ns() is QueryPerformanceCounter, which is
    likewise system-wide and monotonic, with sub-microsecond resolution."""
    return time.perf_counter_ns() if IS_WINDOWS else time.monotonic_ns()

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ENABLE_ECHO_INPUT = 0x0004

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    _kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.GetConsoleProcessList.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD)
    _kernel32.GetConsoleProcessList.restype = wintypes.DWORD
    _kernel32.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _kernel32.SetConsoleMode.argtypes = (wintypes.HANDLE, wintypes.DWORD)


def _process_table() -> dict[int, tuple[int, str]]:
    snapshot = _kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return {}
    table: dict[int, tuple[int, str]] = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return table


def _console_pids() -> set[int]:
    size = 64
    while True:
        buffer = (wintypes.DWORD * size)()
        count = int(_kernel32.GetConsoleProcessList(buffer, size))
        if count == 0:
            return set()
        if count <= size:
            return {int(buffer[index]) for index in range(count)}
        size = count + 16


def _windows_identity() -> tuple[int, int | None, str | None]:
    table = _process_table()
    me = os.getpid()
    parent = table.get(me, (os.getppid(), ""))[0]
    seen: set[int] = set()
    while parent in table and parent not in seen and _LAUNCHER.fullmatch(table[parent][1].lower()):
        seen.add(parent)
        parent = table[parent][0]
    console = _console_pids()
    if not console:
        return parent, None, None
    leader, visited = me, {me}
    while True:
        up = table.get(leader, (0, ""))[0]
        if up in console and up not in visited:
            visited.add(up)
            leader = up
            continue
        break
    return parent, leader, f"console:{leader}"


def identity(fd: int = 0) -> tuple[int, int | None, str | None]:
    """(ppid, sid, tty) of the live terminal; tty is None when fd is not a terminal."""
    if not IS_WINDOWS:
        return os.getppid(), os.getsid(0), os.ttyname(fd) if os.isatty(fd) else None
    ppid, sid, tty = _windows_identity()
    return ppid, sid, tty if os.isatty(fd) else None


def is_terminal_name(value: object) -> bool:
    """What a checker accepts as a recorded live terminal name on this platform."""
    return isinstance(value, str) and value.startswith("console:" if IS_WINDOWS else "/dev/")


def open_tty():
    """(reader, writer) on the controlling terminal itself, bypassing redirected stdio."""
    if IS_WINDOWS:
        return open("CONIN$", "r", encoding="utf-8"), open("CONOUT$", "w", encoding="utf-8")
    return open("/dev/tty", "r", encoding="utf-8"), open("/dev/tty", "w", encoding="utf-8")


def tty_name(reader) -> str:
    if IS_WINDOWS:
        return _windows_identity()[2] or "console:?"
    return os.ttyname(reader.fileno())


def _console_handle(reader):
    return msvcrt.get_osfhandle(reader.fileno())


def echo_enabled(reader) -> bool:
    if IS_WINDOWS:
        mode = wintypes.DWORD()
        if not _kernel32.GetConsoleMode(_console_handle(reader), ctypes.byref(mode)):
            raise OSError(ctypes.get_last_error(), "GetConsoleMode failed")
        return bool(mode.value & _ENABLE_ECHO_INPUT)
    import termios

    return bool(termios.tcgetattr(reader.fileno())[3] & termios.ECHO)


class EchoOff:
    """Disable terminal echo on reader for a password-style line read (termios ECHO / the
    console's ENABLE_ECHO_INPUT; line editing stays on, like getpass)."""

    def __init__(self, reader) -> None:
        self.reader = reader
        self.saved = None

    def __enter__(self):
        if IS_WINDOWS:
            mode = wintypes.DWORD()
            handle = _console_handle(self.reader)
            if not _kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                raise OSError(ctypes.get_last_error(), "GetConsoleMode failed")
            self.saved = mode.value
            if not _kernel32.SetConsoleMode(handle, mode.value & ~_ENABLE_ECHO_INPUT):
                raise OSError(ctypes.get_last_error(), "SetConsoleMode failed")
        else:
            import termios

            self.saved = termios.tcgetattr(self.reader.fileno())
            hidden = list(self.saved)
            hidden[3] &= ~termios.ECHO
            termios.tcsetattr(self.reader.fileno(), termios.TCSANOW, hidden)
        return self

    def __exit__(self, *_exc) -> None:
        if self.saved is None:
            return
        if IS_WINDOWS:
            _kernel32.SetConsoleMode(_console_handle(self.reader), self.saved)
        else:
            import termios

            termios.tcsetattr(self.reader.fileno(), termios.TCSANOW, self.saved)


class KeyReader:
    """Single keypresses from the live terminal without waiting for Enter (a pager's keys):
    termios cbreak on stdin on POSIX, the console's unbuffered getwch on Windows."""

    def __init__(self) -> None:
        self.saved = None

    def __enter__(self):
        if not IS_WINDOWS:
            import termios
            import tty

            self.saved = termios.tcgetattr(0)
            tty.setcbreak(0)
        return self

    def read(self) -> str:
        if IS_WINDOWS:
            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):  # function/arrow prefix: consume its scan code
                msvcrt.getwch()
                return ""
            return key
        return os.read(0, 1).decode("utf-8", errors="replace")

    def __exit__(self, *_exc) -> None:
        if self.saved is not None:
            import termios

            termios.tcsetattr(0, termios.TCSADRAIN, self.saved)


def live_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
