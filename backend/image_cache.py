"""Caché local de imágenes remotas (galería, icono y portada de las instancias).

La ventana del launcher se abre desde file:// y pedirle a Google Drive las imágenes directamente falla a
menudo (cuota/limitación al pedir varias a la vez, sin reintentos). Aquí las descarga Python (con reintentos),
las guarda en disco y la interfaz las muestra desde un archivo local.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import requests

import downloads
import paths

CACHE_DIR = Path.home() / ".chechenitza_studio_image_cache"
paths.hide_path(CACHE_DIR)
_MAX_BYTES = 40 * 1024 * 1024
_EXT_BY_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp",
    "image/gif": ".gif", "image/bmp": ".bmp", "image/avif": ".avif",
}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_slots = threading.Semaphore(6)   # como mucho 6 descargas a la vez para no saturar a Drive


def _key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]


def _sniff(head: bytes) -> str:
    """Extensión según los primeros bytes (Drive a veces sirve las imágenes como application/octet-stream)."""
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:3] == b"GIF":
        return ".gif"
    if head[:2] == b"BM":
        return ".bmp"
    if head[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"
    return ""


def _find(key: str) -> Optional[Path]:
    if not CACHE_DIR.exists():
        return None
    for p in CACHE_DIR.glob(f"{key}.*"):
        if p.suffix != ".part" and p.stat().st_size > 0:
            return p
    return None


_API_ID = re.compile(r"/drive/v3/files/([\w-]+)")


def _candidates(url: str) -> list[str]:
    """La URL original y, si es de Drive, otras rutas públicas al mismo archivo."""
    out = [url]
    m = _API_ID.search(url) or re.search(r"[?&]id=([\w-]+)", url)
    fid = m.group(1) if m else downloads.drive_file_id(url)
    if fid:
        out += [f"https://drive.google.com/thumbnail?id={fid}&sz=w1600",
                f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t",
                f"https://lh3.googleusercontent.com/d/{fid}=w1600"]
    return out


def _fetch(url: str, key: str) -> Path:
    last: Exception = RuntimeError("no se pudo descargar la imagen")
    errors = []
    for attempt in range(3):
      for cand in _candidates(url):
        try:
            with _slots:
                with requests.get(cand,
                                  headers={"User-Agent": downloads.USER_AGENT}, timeout=30, stream=True) as r:
                    r.raise_for_status()
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    paths.hide_path(CACHE_DIR)
                    part = CACHE_DIR / f"{key}.part"
                    size, ext = 0, ""
                    with open(part, "wb") as f:
                        for chunk in r.iter_content(chunk_size=downloads.CHUNK):
                            if not chunk:
                                continue
                            if size == 0:
                                ext = _sniff(chunk[:16])
                                if not ext:
                                    raise RuntimeError("la respuesta no es una imagen "
                                                       f"({r.headers.get('Content-Type', 'sin tipo')})")
                            size += len(chunk)
                            if size > _MAX_BYTES:
                                raise RuntimeError("imagen demasiado grande")
                            f.write(chunk)
                    if size == 0:
                        raise RuntimeError("descarga vacía")
                    target = CACHE_DIR / f"{key}{ext}"
                    os.replace(part, target)
                    return target
        except Exception as e:  # noqa: BLE001
            last = e
            errors.append(f"{cand.split('key=')[0][:90]} -> {e}")
      time.sleep(0.8 * (attempt + 1))
    try:
        part = CACHE_DIR / f"{key}.part"
        part.unlink(missing_ok=True)
    except Exception:
        pass
    paths.log_event("image_cache", "fallo al descargar: " + " | ".join(errors[-4:]))
    raise last


def get(url: str) -> Optional[str]:
    """Devuelve la URI file:// de la imagen en caché (descargándola si hace falta), o None si falla."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    key = _key(url)
    cached = _find(key)
    if cached:
        return cached.resolve().as_uri()
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        cached = _find(key)
        if cached:
            return cached.resolve().as_uri()
        try:
            return _fetch(url, key).resolve().as_uri()
        except Exception:
            return None


def prefetch(urls) -> None:
    """Descarga en segundo plano (en paralelo) las imágenes que se van a mostrar, para que al abrir la
    pantalla ya estén en disco y salgan al instante."""
    wanted = [u for u in dict.fromkeys(urls or []) if u and u.lower().startswith(("http://", "https://"))]
    if not wanted:
        return

    def worker():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda u: get(u), wanted))

    threading.Thread(target=worker, daemon=True).start()
