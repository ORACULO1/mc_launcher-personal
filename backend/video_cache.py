from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Iterable, Optional

import downloads
import paths

CACHE_DIR = Path.home() / ".chechenitza_studio_video_cache"
paths.hide_path(CACHE_DIR)
_EXT_OK = (".mp4", ".webm", ".m4v", ".ogv")

_lock = threading.Lock()
_in_progress: set[str] = set()


def _key(url: str, version: str) -> str:
    return hashlib.sha1(f"{url}|{version}".encode("utf-8")).hexdigest()[:24]


def _path_for(url: str, version: str, ext: str = ".mp4") -> Path:
    return CACHE_DIR / f"{_key(url, version)}{ext}"


def _find_cached(url: str, version: str) -> Optional[Path]:
    key = _key(url, version)
    for ext in _EXT_OK:
        p = CACHE_DIR / f"{key}{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def local_uri(url: str, version: str = "") -> Optional[str]:
    if not url:
        return None
    p = _find_cached(url, version)
    return p.resolve().as_uri() if p else None


def _download(url: str, version: str, ext: str) -> None:
    target = _path_for(url, version, ext)
    part = target.with_suffix(target.suffix + ".part")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        paths.hide_path(CACHE_DIR)
        with open(part, "wb") as f:
            downloads.download_to(url, f, timeout=30)
        if part.stat().st_size == 0:
            raise RuntimeError("descarga vacía")
        os.replace(part, target)
    except Exception:
        try:
            part.unlink(missing_ok=True)
        except Exception:
            pass
    finally:
        with _lock:
            _in_progress.discard(_key(url, version))


def prefetch(videos: Iterable[tuple[str, str, str]]) -> None:
    wanted = [(u, v, n) for (u, v, n) in videos if u]
    keep = {_key(u, v) for (u, v, _n) in wanted}

    def worker():
        for url, version, name in wanted:
            if _find_cached(url, version):
                continue
            key = _key(url, version)
            with _lock:
                if key in _in_progress:
                    continue
                _in_progress.add(key)
            ext = Path(name or "").suffix.lower()
            _download(url, version, ext if ext in _EXT_OK else ".mp4")

        try:
            if CACHE_DIR.exists():
                for f in CACHE_DIR.iterdir():
                    if f.suffix == ".part" or f.stem in keep:
                        continue
                    if wanted:
                        f.unlink(missing_ok=True)
        except Exception:
            pass

    if wanted:
        threading.Thread(target=worker, daemon=True).start()
