from __future__ import annotations

import re
import time
from typing import BinaryIO, Callable, Optional

import requests

import settings

USER_AGENT = "ChechenitzaStudio/1.0 (contacto: gleiberlecuzz@gmail.com)"
CHUNK = 131072

_DRIVE_PATTERNS = (
    re.compile(r"drive\.google\.com/file/d/([\w-]+)"),
    re.compile(r"drive\.google\.com/(?:open|uc)\?(?:[^#]*&)?id=([\w-]+)"),
    re.compile(r"drive\.usercontent\.google\.com/download\?(?:[^#]*&)?id=([\w-]+)"),
)


def drive_file_id(url: str) -> Optional[str]:
    for pattern in _DRIVE_PATTERNS:
        m = pattern.search(url or "")
        if m:
            return m.group(1)
    return None


def resolve_url(url: str) -> str:
    file_id = drive_file_id(url)
    if file_id:
        return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    return url


class RateLimiter:

    def __init__(self, bytes_per_sec: int = 0):
        self.rate = max(0, int(bytes_per_sec))
        self._start = time.monotonic()
        self._sent = 0

    @classmethod
    def from_settings(cls) -> "RateLimiter":
        return cls(settings.get_download_limit_bytes_per_sec())

    def wait(self, n: int) -> None:
        if self.rate <= 0:
            return
        self._sent += n
        ahead = self._sent / self.rate - (time.monotonic() - self._start)
        if ahead > 0:
            time.sleep(ahead)


def download_to(url: str, out: BinaryIO, limiter: Optional[RateLimiter] = None,
                on_bytes: Optional[Callable[[int], None]] = None, timeout: int = 30) -> None:
    is_drive = drive_file_id(url) is not None
    with requests.get(resolve_url(url), stream=True, headers={"User-Agent": USER_AGENT}, timeout=timeout) as r:
        r.raise_for_status()
        if is_drive and "text/html" in r.headers.get("Content-Type", ""):
            raise RuntimeError("No se pudo descargar el archivo en este momento.")
        for chunk in r.iter_content(chunk_size=CHUNK):
            if not chunk:
                continue
            out.write(chunk)
            if limiter:
                limiter.wait(len(chunk))
            if on_bytes:
                on_bytes(len(chunk))


def fetch_json(url: str, timeout: int = 6):
    r = requests.get(resolve_url(url), headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return r.json()
