from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Optional

import requests

import downloads

META_HOSTS = [
    "https://meta.fabricmc.net",
    "https://bmclapi2.bangbang93.com/fabric-meta",
]
MAVEN_HOSTS = [
    "https://maven.fabricmc.net",
    "https://bmclapi2.bangbang93.com/maven",
]

ProgressCallback = Callable[[str, int, int], None]


class FabricNetworkError(RuntimeError):
    pass


def _get_json(path: str, timeout: int = 10, tries: int = 2):
    last: Optional[Exception] = None
    for host in META_HOSTS:
        for attempt in range(tries):
            try:
                r = requests.get(host + path, timeout=timeout, headers={"User-Agent": downloads.USER_AGENT})
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last = e
                if attempt < tries - 1:
                    time.sleep(1.0 * (attempt + 1))
    raise FabricNetworkError(f"No respondió ningún servidor de Fabric ({last})")


def latest_loader_version() -> str:
    data = _get_json("/v2/versions/loader")
    for item in data:
        if item.get("stable"):
            return item["version"]
    return data[0]["version"]


def _maven_path(name: str) -> str:
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = f"-{parts[3]}" if len(parts) > 3 else ""
    return f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}{classifier}.jar"


def _candidate_urls(lib: dict, rel_path: str) -> list[str]:
    base = (lib.get("url") or MAVEN_HOSTS[0]).rstrip("/")
    urls = [f"{base}/{rel_path}"]
    if base == MAVEN_HOSTS[0]:
        urls += [f"{h}/{rel_path}" for h in MAVEN_HOSTS[1:]]
    return urls


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_library(lib: dict, libraries_dir: Path, limiter: downloads.RateLimiter) -> None:
    rel = _maven_path(lib["name"])
    dest = libraries_dir / rel
    expected = (lib.get("sha1") or "").lower()

    if dest.exists() and (not expected or _sha1(dest) == expected):
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last: Optional[Exception] = None
    for url in _candidate_urls(lib, rel):
        for attempt in range(2):
            try:
                with open(tmp, "wb") as f:
                    downloads.download_to(url, f, limiter, timeout=15)
                if expected and _sha1(tmp) != expected:
                    raise RuntimeError("SHA-1 incorrecto")
                tmp.replace(dest)
                return
            except Exception as e:
                last = e
                time.sleep(0.8)
    tmp.unlink(missing_ok=True)
    raise FabricNetworkError(f"No se pudo descargar {lib['name']} ({last})")


def install(vanilla_version: str, minecraft_directory: Path, loader_version: Optional[str] = None,
            progress: Optional[ProgressCallback] = None, fallback_loader_version: Optional[str] = None) -> str:
    if loader_version is None:
        try:
            loader_version = latest_loader_version()
        except FabricNetworkError:
            if not fallback_loader_version:
                raise
            loader_version = fallback_loader_version

    profile = _get_json(f"/v2/versions/loader/{vanilla_version}/{loader_version}/profile/json")
    version_id = profile["id"]
    libraries = profile.get("libraries", [])

    limiter = downloads.RateLimiter.from_settings()
    total = max(len(libraries), 1)
    for i, lib in enumerate(libraries, start=1):
        if progress:
            progress("Descargando el cargador de mods…", i, total)
        _download_library(lib, minecraft_directory / "libraries", limiter)

    version_dir = minecraft_directory / "versions" / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / f"{version_id}.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    if progress:
        progress("Cargador de mods instalado", total, total)
    return version_id
