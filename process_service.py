"""Non-Tk process discovery, filtering, architecture, and launching."""

from dataclasses import dataclass
import logging
import subprocess
import sys


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    architecture: str
    name: str
    executable_path: str


class ProcessService:
    """Return plain process records; presentation remains the caller's job."""

    def __init__(
        self,
        *,
        process_iter,
        visible_window,
        architecture,
        popen=None,
        excluded_executables=(),
        system_dirs=(),
        system_patterns=(),
        bloatware_patterns=(),
        minimum_pid=100,
    ):
        self._process_iter = process_iter
        self._visible_window = visible_window
        self._architecture = architecture
        self._popen = popen or subprocess.Popen
        self.excluded_executables = {str(name).lower() for name in excluded_executables}
        self.system_dirs = tuple(str(path).lower() for path in system_dirs)
        self.system_patterns = tuple(str(pattern).lower() for pattern in system_patterns)
        self.bloatware_patterns = tuple(str(pattern).lower() for pattern in bloatware_patterns)
        self.minimum_pid = minimum_pid

    def should_exclude(self, process_name, executable_path=None):
        name = str(process_name or "").lower()
        if name in self.excluded_executables:
            return True
        path = str(executable_path or "").lower()
        if path and any(path.startswith(directory) for directory in self.system_dirs):
            return True
        return any(pattern in name for pattern in self.system_patterns + self.bloatware_patterns)

    def discover(self):
        discovered = []
        for process in self._process_iter(['pid', 'name', 'exe']):
            try:
                info = process.info
                pid = int(info['pid'])
                name = str(info.get('name') or '')
                executable_path = str(info.get('exe') or '')
                if pid < self.minimum_pid or self.should_exclude(name, executable_path):
                    continue
                if not self._visible_window(pid):
                    continue
                discovered.append(ProcessInfo(pid, self._architecture(pid), name, executable_path))
            except Exception:
                # Process inspection is inherently racy; inaccessible/exited processes are skipped.
                continue
        return discovered

    def launch(self, executable_path):
        return self._popen([str(executable_path)])


def windows_process_architecture(pid):
    """Return the legacy x86 fallback when Windows inspection is unavailable."""
    try:
        if sys.platform == 'win32':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                is_wow64 = ctypes.c_bool()
                if kernel32.IsWow64Process(handle, ctypes.byref(is_wow64)):
                    kernel32.CloseHandle(handle)
                    return 'x86' if is_wow64.value else 'x64'
                kernel32.CloseHandle(handle)
    except Exception:
        logging.exception('Failed to determine process architecture')
    return 'x86'
