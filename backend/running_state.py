from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

STATE_FILE = Path.home() / ".chechenitza_studio_running.json"

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_STILL_ACTIVE = 259


def is_pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == _STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def terminate_pid(pid: int) -> bool:
    if not is_pid_alive(pid):
        return False
    try:
        if sys.platform == "win32":
            handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
            if not handle:
                return False
            try:
                ctypes.windll.kernel32.TerminateProcess(handle, 1)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(pid, 15)
        return True
    except Exception:
        return False


def load_alive() -> dict[str, int]:
    if not STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}

    alive: dict[str, int] = {}
    for profile_id, pid in raw.items():
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if is_pid_alive(pid):
            alive[profile_id] = pid

    if alive != raw:
        save(alive)
    return alive


def save(mapping: dict[str, int]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    except Exception:
        pass
