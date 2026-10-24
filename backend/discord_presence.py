from __future__ import annotations

import sys
import threading
import time
from typing import Optional

import studio_config

try:
    from pypresence import Presence
    _PYPRESENCE_OK = True
except Exception:
    _PYPRESENCE_OK = False

_lock = threading.Lock()
_rpc: Optional["Presence"] = None
_connected = False
_last_attempt = 0.0
_RETRY_SECONDS = 15

_launcher_start_ts = int(time.time())
_playing_since_ts: Optional[int] = None
_current_instance: Optional[str] = None


def is_configured() -> bool:
    return _PYPRESENCE_OK and bool(studio_config.DISCORD_CLIENT_ID.strip())


def _ensure_connected() -> bool:
    global _rpc, _connected, _last_attempt
    if not is_configured():
        return False
    if _connected:
        return True
    now = time.time()
    if now - _last_attempt < _RETRY_SECONDS:
        return False
    _last_attempt = now
    try:
        rpc = Presence(studio_config.DISCORD_CLIENT_ID.strip())
        rpc.connect()
        _rpc = rpc
        _connected = True
        return True
    except Exception:
        _rpc = None
        _connected = False
        return False


def _reset_connection():
    global _rpc, _connected
    _rpc = None
    _connected = False


def _push(**kwargs) -> None:
    with _lock:
        if not _ensure_connected():
            return
        try:
            _rpc.update(**kwargs)
        except Exception:
            _reset_connection()


def set_idle() -> None:
    global _current_instance, _playing_since_ts
    _current_instance = None
    _playing_since_ts = None
    _push(
        details="En el launcher",
        state="Explorando instancias",
        start=_launcher_start_ts,
        large_image="logo",
        large_text="Chechenitza Studio",
    )


def set_playing(instance_name: str) -> None:
    global _current_instance, _playing_since_ts
    if _current_instance != instance_name:
        _playing_since_ts = int(time.time())
    _current_instance = instance_name
    _push(
        details="Jugando",
        state=instance_name,
        start=_playing_since_ts,
        large_image="logo",
        large_text="Chechenitza Studio",
    )


def refresh() -> None:
    if _current_instance:
        set_playing(_current_instance)
    else:
        set_idle()


def close() -> None:
    global _rpc, _connected
    with _lock:
        if _rpc is not None:
            try:
                _rpc.clear()
                _rpc.close()
            except Exception:
                pass
        _rpc = None
        _connected = False
