from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

import downloads

API_BASE = "https://api.modrinth.com/v2"
USER_AGENT = "ChechenitzaStudio/1.0 (contacto: gleiberlecuzz@gmail.com)"


def _headers() -> dict:
    return {"User-Agent": USER_AGENT}


def search_mods(query: str, loader: str = "fabric", game_version: Optional[str] = None,
                 offset: int = 0, limit: int = 20) -> dict:
    facets = [["project_type:mod"]]
    if loader and loader != "none":
        facets.append([f"categories:{loader}"])
    if game_version:
        facets.append([f"versions:{game_version}"])

    params = {
        "query": query,
        "facets": json.dumps(facets),
        "limit": limit,
        "offset": offset,
        "index": "relevance",
    }
    r = requests.get(f"{API_BASE}/search", params=params, headers=_headers(), timeout=10)
    r.raise_for_status()
    data = r.json()

    hits = []
    for h in data.get("hits", []):
        hits.append({
            "id": h.get("project_id"),
            "slug": h.get("slug"),
            "title": h.get("title"),
            "description": h.get("description"),
            "iconUrl": h.get("icon_url"),
            "downloads": h.get("downloads", 0),
            "author": h.get("author"),
            "categories": h.get("categories", []),
        })
    return {"hits": hits, "totalHits": data.get("total_hits", 0)}


def search_packs(query: str, project_type: str, game_version: Optional[str] = None, offset: int = 0, limit: int = 20) -> dict:
    if project_type not in {"shader", "resourcepack", "modpack"}:
        raise ValueError("Tipo de pack no válido")
    facets = [[f"project_type:{project_type}"]]
    if game_version:
        facets.append([f"versions:{game_version}"])
    params = {"query": query, "facets": json.dumps(facets), "limit": limit, "offset": offset, "index": "relevance"}
    r = requests.get(f"{API_BASE}/search", params=params, headers=_headers(), timeout=10)
    r.raise_for_status()
    data = r.json()
    return {"hits": [{"id": h.get("project_id"), "slug": h.get("slug"), "title": h.get("title"), "description": h.get("description"), "iconUrl": h.get("icon_url"), "downloads": h.get("downloads", 0), "author": h.get("author"), "categories": h.get("categories", [])} for h in data.get("hits", [])], "totalHits": data.get("total_hits", 0)}


def get_pack_versions(project_id: str, game_version: Optional[str] = None) -> list[dict]:
    return get_mod_versions(project_id, loader="none", game_version=game_version)


def get_mod_versions(project_id: str, loader: str, game_version: Optional[str] = None) -> list[dict]:
    params = {}
    if loader and loader != "none":
        params["loaders"] = json.dumps([loader])
    if game_version:
        params["game_versions"] = json.dumps([game_version])

    r = requests.get(f"{API_BASE}/project/{project_id}/version", params=params,
                      headers=_headers(), timeout=10)
    r.raise_for_status()
    versions = r.json()

    result = []
    for v in versions:
        files = v.get("files", [])
        primary_file = next((f for f in files if f.get("primary")), None)
        if primary_file is None and files:
            primary_file = files[0]
        if primary_file is None:
            continue
        result.append({
            "id": v.get("id"),
            "versionNumber": v.get("version_number"),
            "name": v.get("name"),
            "datePublished": v.get("date_published"),
            "gameVersions": v.get("game_versions", []),
            "loaders": v.get("loaders", []),
            "downloadUrl": primary_file.get("url"),
            "filename": primary_file.get("filename"),
            "fileSize": primary_file.get("size"),
        })
    return result


def download_mod(download_url: str, filename: str, dest_folder: Path) -> Path:
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest_path = dest_folder / filename
    with open(dest_path, "wb") as f:
        downloads.download_to(download_url, f, downloads.RateLimiter.from_settings())
    return dest_path
