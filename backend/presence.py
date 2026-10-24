from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

import studio_config

_DEVICE_ID_FILE = Path.home() / ".chechenitza_studio_device_id.json"
_REQUEST_TIMEOUT = 6
_STALE_AFTER_SECONDS = 70


def _device_id() -> str:
    try:
        data = json.loads(_DEVICE_ID_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("id"):
            return data["id"]
    except Exception:
        pass
    new_id = uuid.uuid4().hex
    try:
        _DEVICE_ID_FILE.write_text(json.dumps({"id": new_id}), encoding="utf-8")
    except Exception:
        pass
    return new_id


def _base_url() -> str:
    return studio_config.FIREBASE_DB_URL.strip().rstrip("/")


def is_configured() -> bool:
    return bool(_base_url())


def send_heartbeat(label: str = "") -> None:
    url = _base_url()
    if not url:
        return
    try:
        r = requests.put(
            f"{url}/presence/{_device_id()}.json",
            json={"t": int(time.time()), "who": label or "?"},
            timeout=_REQUEST_TIMEOUT,
        )
    except Exception:
        pass


def clear_heartbeat() -> None:
    url = _base_url()
    if not url:
        return
    try:
        requests.delete(f"{url}/presence/{_device_id()}.json", timeout=_REQUEST_TIMEOUT)
    except Exception:
        pass


def get_online_count() -> Optional[int]:
    url = _base_url()
    if not url:
        return None
    try:
        r = requests.get(f"{url}/presence.json", timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json() or {}
        if not isinstance(data, dict):
            return 0
        now = time.time()
        return sum(
            1 for entry in data.values()
            if isinstance(entry, dict) and now - float(entry.get("t", 0)) < _STALE_AFTER_SECONDS
        )
    except Exception:
        return None
