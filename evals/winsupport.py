"""Native Windows primitives for the eval runner (run.py) and its pairmux proxy.

POSIX never imports the Win32 parts of this module. Everything here replaces a POSIX facility the
runner relies on:

* process groups / killpg      -> a Job Object per launched process (TerminateJobObject);
* /proc or ps parent lookup    -> a Toolhelp32 process snapshot;
* SO_PEERCRED / LOCAL_PEERPID  -> GetNamedPipeClientProcessId on the broker's named pipe;
* geteuid peer check           -> the client's process-token user SID;
* SCM_RIGHTS stdio passing     -> DuplicateHandle out of the kernel-identified client process;
* an exec'able `pairmux` file  -> a real console launcher (pip's vendored distlib launcher) so
                                  argv reaches Python through CommandLineToArgvW unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    PROCESS_TERMINATE = 0x0001
    PROCESS_DUP_HANDLE = 0x0040
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    STILL_ACTIVE = 259

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

    class _BasicAccounting(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetNamedPipeClientProcessId.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    advapi32.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)


# ---- processes ----------------------------------------------------------------------------------

def process_table() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, image name) from one Toolhelp32 snapshot."""
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return {}
    table: dict[int, tuple[int, str]] = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table


def parent_process_id(pid: int) -> int | None:
    parent = process_table().get(pid)
    return parent[0] if parent else None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_user_sid(pid: int | None = None) -> str | None:
    """The user SID of a process token (the current process when pid is None)."""
    process = kernel32.GetCurrentProcess() if pid is None else kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            needed = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))  # TokenUser
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi32.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)):
                return None
            sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
                return None
            try:
                return text.value
            finally:
                kernel32.LocalFree(text)
        finally:
            kernel32.CloseHandle(token)
    finally:
        if pid is not None:
            kernel32.CloseHandle(process)


class Job:
    """A Job Object holding one launched process tree: the Windows stand-in for a process group.
    It is not kill-on-close: daemons started by setup (pairmux's built-in server) survive."""

    def __init__(self) -> None:
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

    def assign(self, process: subprocess.Popen) -> bool:
        return bool(kernel32.AssignProcessToJobObject(self.handle, int(process._handle)))

    def active_processes(self) -> int:
        info = _BasicAccounting()
        if not kernel32.QueryInformationJobObject(self.handle, 1, ctypes.byref(info),
                                                  ctypes.sizeof(info), None):
            return 0
        return int(info.ActiveProcesses)

    def terminate(self, code: int = 1) -> None:
        kernel32.TerminateJobObject(self.handle, code)

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None


def taskkill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=30, check=False)


# ---- named-pipe broker transport ----------------------------------------------------------------

def pipe_client_pid(pipe_handle: int) -> int:
    pid = wintypes.ULONG()
    if not kernel32.GetNamedPipeClientProcessId(pipe_handle, ctypes.byref(pid)):
        raise OSError(ctypes.get_last_error(), "GetNamedPipeClientProcessId failed")
    return int(pid.value)


def duplicate_client_handles(client_pid: int, handles: list[int]) -> list[int | None]:
    """Duplicate the client's std handles into this process; returns CRT fds (None = no handle)."""
    import _winapi
    import msvcrt

    source = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, client_pid)
    if not source:
        raise OSError(ctypes.get_last_error(), "cannot open the broker client for handle duplication")
    fds: list[int | None] = []
    try:
        for value in handles:
            if value in (0, -1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF):
                fds.append(None)
                continue
            try:
                duplicate = _winapi.DuplicateHandle(int(source), value, _winapi.GetCurrentProcess(),
                                                    0, False, _winapi.DUPLICATE_SAME_ACCESS)
            except OSError:
                fds.append(None)
                continue
            fds.append(msvcrt.open_osfhandle(duplicate, 0))
    except BaseException:
        for fd in fds:
            if fd is not None:
                os.close(fd)
        raise
    finally:
        kernel32.CloseHandle(source)
    return fds


# ---- launchers ----------------------------------------------------------------------------------

def make_console_launcher(script: Path, destination_dir: Path, name: str) -> tuple[Path, str]:
    """Install `<name>.exe` that runs `<python> -I <script> args...` with exact argv.

    Returns (path, method). pip vendors distlib's console launchers; when that is unavailable a
    `<name>.cmd` shim is written instead (cmd.exe argument handling is lossy: method says so)."""
    import tempfile

    interpreter = Path(sys.executable).resolve()
    try:
        from pip._vendor.distlib.scripts import ScriptMaker  # type: ignore[import-not-found]

        with tempfile.TemporaryDirectory(prefix="pmx-launcher-") as staging:
            # The whole script is embedded in the launcher; its shebang carries -I, which the
            # launcher passes to the interpreter: "<python>" -I "<launcher.exe>" args...
            body = script.read_text(encoding="utf-8").split("\n", 1)
            source = Path(staging) / f"{name}.py"
            source.write_text("#!python -I\n" + (body[1] if len(body) > 1 else ""), encoding="utf-8")
            maker = ScriptMaker(staging, str(destination_dir), add_launchers=True)
            maker.executable = str(interpreter)
            maker.clobber = True
            maker.variants = {""}
            maker.make(source.name)
        launcher = destination_dir / f"{name}.exe"
        if launcher.is_file():
            return launcher, "distlib-console-launcher"
    except Exception:  # noqa: BLE001 - any launcher failure falls back to the documented shim
        pass
    # The script copy sits beside the shim so its sys.argv[0] locates the same directory a
    # launcher's would.
    target = destination_dir / f"{name}-script.py"
    shutil.copy2(script, target)
    shim = destination_dir / f"{name}.cmd"
    shim.write_text(f'@"{interpreter}" -I "{target}" %*\r\n@exit /b %ERRORLEVEL%\r\n', encoding="utf-8")
    return shim, "cmd-shim-lossy-argv"


_CMD_SHIM_TARGET = re.compile(r'"%(?:~dp0|dp0%)\\([^"%]+\.(?:js|cjs|mjs))"', re.IGNORECASE)
_CMD_SHIM_NODE = re.compile(r'"%(?:~dp0|dp0%)\\node\.exe"', re.IGNORECASE)


def resolve_agent_executable(executable: str) -> list[str]:
    """argv prefix that runs an agent CLI with exact multi-line arguments.

    npm installs Windows CLIs as `.cmd` shims; cmd.exe cannot carry a multi-line TASK argument.
    Resolve npm's cmd-shim format to `node <entry.js>`; .exe/.com run directly."""
    path = Path(executable)
    if path.suffix.lower() in {".exe", ".com"}:
        return [str(path)]
    if path.suffix.lower() not in {".cmd", ".bat"}:
        for suffix in (".exe", ".cmd"):
            candidate = path.with_name(path.name + suffix)
            if candidate.is_file():
                return resolve_agent_executable(str(candidate))
        return [str(path)]
    text = path.read_text(encoding="utf-8", errors="replace")
    target = _CMD_SHIM_TARGET.search(text)
    if target is None:
        raise ValueError(f"{path} is a .cmd launcher that is not an npm cmd-shim; multi-line task "
                         "arguments cannot pass through cmd.exe. Point PATH at the CLI's .exe or "
                         "its node entry script.")
    script = (path.parent / target.group(1)).resolve()
    node = path.parent / "node.exe"
    if not (_CMD_SHIM_NODE.search(text) and node.is_file()):
        found = shutil.which("node")
        if not found:
            raise ValueError(f"{path} needs node.exe, which is not on PATH")
        node = Path(found)
    return [str(node.resolve()), str(script)]


def posix_path(path: Path) -> str:
    """A Windows path as Git Bash (MSYS) spells it, for BASH_ENV PATH guards."""
    cygpath = shutil.which("cygpath")
    if cygpath:
        try:
            converted = subprocess.run([cygpath, "-u", str(path)], capture_output=True, text=True,
                                       timeout=10, check=False).stdout.strip()
            if converted:
                return converted
        except (OSError, subprocess.TimeoutExpired):
            pass
    text = str(path).replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/(.*)$", text)
    return f"/{match.group(1).lower()}/{match.group(2)}" if match else text
