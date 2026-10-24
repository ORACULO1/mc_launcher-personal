from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes

import running_state


def rename_window_for_pid(pid: int, title: str, timeout: float = 90.0, poll: float = 1.0):
    if sys.platform != "win32" or not pid:
        return
    threading.Thread(target=_worker, args=(pid, title, timeout, poll), daemon=True).start()


def _worker(pid: int, title: str, timeout: float, poll: float):
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def windows_for_pid() -> list:
        hwnds = []

        def _each(hwnd, _lparam):
            found_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(found_pid))
            if found_pid.value == pid and user32.IsWindowVisible(hwnd):
                hwnds.append(hwnd)
            return True

        user32.EnumWindows(EnumWindowsProc(_each), 0)
        return hwnds

    deadline = time.time() + timeout
    found = False
    while time.time() < deadline:
        if not running_state.is_pid_alive(pid):
            return
        hwnds = windows_for_pid()
        if hwnds:
            for hwnd in hwnds:
                user32.SetWindowTextW(hwnd, title)
            found = True
            break
        time.sleep(poll)

    if not found:
        return

    reinforce_until = time.time() + 15
    while time.time() < reinforce_until:
        time.sleep(poll)
        if not running_state.is_pid_alive(pid):
            return
        for hwnd in windows_for_pid():
            user32.SetWindowTextW(hwnd, title)
