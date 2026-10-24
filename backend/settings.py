from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SETTINGS_FILE = Path.home() / ".chechenitza_studio_settings.json"

MIN_RAM_MB = 1024
HARD_MAX_RAM_MB = 32 * 1024
DEFAULT_RAM_MB = 4096
MAX_DOWNLOAD_LIMIT_MB = 50


def system_ram_mb() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys // (1024 * 1024))
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except Exception:
        return None


def max_ram_mb() -> int:
    total = system_ram_mb()
    if total is None:
        return HARD_MAX_RAM_MB
    return max(MIN_RAM_MB, min(HARD_MAX_RAM_MB, (total // 512) * 512))


def _clamp_ram(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_RAM_MB
    return max(MIN_RAM_MB, min(max_ram_mb(), value))


def _clamp_download(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    return max(0, min(MAX_DOWNLOAD_LIMIT_MB, value))


def load() -> dict:
    raw = {}
    if SETTINGS_FILE.exists():
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    return {
        "ram_mb": _clamp_ram(raw.get("ram_mb", DEFAULT_RAM_MB)),
        "download_limit_mb": _clamp_download(raw.get("download_limit_mb", 0)),
    }


def save(ram_mb, download_limit_mb) -> dict:
    data = {
        "ram_mb": _clamp_ram(ram_mb),
        "download_limit_mb": _clamp_download(download_limit_mb),
    }
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def get_ram_mb() -> int:
    return load()["ram_mb"]


def get_download_limit_bytes_per_sec() -> int:
    return load()["download_limit_mb"] * 1024 * 1024
