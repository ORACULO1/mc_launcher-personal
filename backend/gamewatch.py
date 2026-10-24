"""Detecta cuándo Minecraft terminó de cargar, sin depender de lo que imprima el log."""
from __future__ import annotations

import os
import threading
import time
from typing import Callable

LOG_MARKERS = ("sound engine started", "openal initialized")
FALLBACK_SECONDS = 90   # si no se detecta nada, se actúa igualmente a los 90 s
MIN_SECONDS = 8         # nunca antes: los mods deben haberse abierto


def pid_has_minecraft_window(pid: int) -> bool:
    """True si el proceso tiene una ventana visible cuyo título empieza por 'Minecraft' (solo Windows)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found: list[int] = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value == pid:
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, buf, 256)
                    if buf.value.startswith("Minecraft"):
                        found.append(1)
            return True

        user32.EnumWindows(enum_proc(cb), 0)
        return bool(found)
    except Exception:
        return False


def line_signals_loaded(line) -> bool:
    if isinstance(line, bytes):
        line = line.decode("utf-8", "ignore")
    low = line.lower()
    return any(m in low for m in LOG_MARKERS)


def watch_until_loaded(process, log_event: threading.Event, on_loaded: Callable[[str], None],
                       window_check=pid_has_minecraft_window, sleep=time.sleep,
                       clock=time.monotonic, fallback=FALLBACK_SECONDS, minimum=MIN_SECONDS) -> None:
    """Bloquea hasta que el juego cargó (log, ventana o tiempo) y llama a on_loaded(motivo) una vez."""
    start = clock()
    while process.poll() is None:
        elapsed = clock() - start
        reason = None
        if elapsed >= minimum:
            if log_event.is_set():
                reason = "log"
            elif window_check(process.pid):
                reason = "ventana"
            elif elapsed >= fallback:
                reason = "tiempo"
        if reason:
            on_loaded(reason)
            return
        sleep(1.0)
