from __future__ import annotations

import re
import sys
import time
from typing import Optional

import requests

API = "https://www.googleapis.com/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
TIMEOUT = 8


def folder_id_from(value: str) -> str:
    m = re.search(r"/folders/([\w-]+)", value or "")
    return m.group(1) if m else (value or "").strip()


def media_url(file_id: str, api_key: str) -> str:
    return f"{API}/{file_id}?alt=media&supportsAllDrives=true&key={api_key}"


def _list(query: str, fields: str, api_key: str, order_by: Optional[str] = None) -> list:
    files, page_token = [], None
    while True:
        params = {"q": query, "fields": f"nextPageToken,files({fields})", "pageSize": 1000,
                  "key": api_key, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
        if order_by:
            params["orderBy"] = order_by
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(API, params=params, timeout=TIMEOUT)
        if r.status_code in (400, 403):
            raise RuntimeError("No se pudo cargar el contenido en este momento.")
        r.raise_for_status()
        data = r.json()
        files.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            return files


GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
VIDEO_EXTENSIONS = (".mp4", ".webm", ".m4v", ".ogv")
INFO_NAME_RE = re.compile(r"^(info|informaci[oó]n|descripci[oó]n|description|readme)\b", re.I)


def _read_text(file: dict, api_key: str, tries: int = 2) -> str:
    if file.get("mimeType") == GOOGLE_DOC_MIME:
        url, params = f"{API}/{file['id']}/export", {"mimeType": "text/plain", "key": api_key}
    else:
        url, params = f"{API}/{file['id']}", {"alt": "media", "key": api_key}

    last: Optional[Exception] = None
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.content.decode("utf-8-sig", errors="replace").strip()
        except Exception as e:
            last = e
            if attempt < tries - 1:
                time.sleep(1.0)
    return ""


def _is_image(f: dict) -> bool:
    return f.get("mimeType", "").startswith("image/") or f["name"].lower().endswith(IMAGE_EXTENSIONS)


def _is_video(f: dict) -> bool:
    return f.get("mimeType", "").startswith("video/") or f["name"].lower().endswith(VIDEO_EXTENSIONS)


def _is_info(f: dict) -> bool:
    name = f["name"]
    if not INFO_NAME_RE.match(name):
        return False
    is_text = f.get("mimeType") in ("text/plain", "text/markdown", GOOGLE_DOC_MIME) \
        or name.lower().endswith((".txt", ".md"))
    return is_text


def _files_by_parent(subfolders: list, api_key: str) -> dict:
    fields = "id,name,mimeType,md5Checksum,modifiedTime,parents"
    result: dict[str, list] = {f["id"]: [] for f in subfolders}
    ids = list(result)

    try:
        for start in range(0, len(ids), 40):
            chunk = ids[start:start + 40]
            q = "(" + " or ".join(f"'{i}' in parents" for i in chunk) + ") and trashed=false"
            for f in _list(q, fields, api_key):
                for parent in f.get("parents", []):
                    if parent in result:
                        result[parent].append(f)
        return result
    except RuntimeError:
        result = {i: [] for i in ids}

    for folder in subfolders:
        try:
            result[folder["id"]] = _list(f"'{folder['id']}' in parents and trashed=false", fields, api_key)
        except RuntimeError:
            pass
    return result


# Cada dato de la pantalla "Información" sale de su propio archivo (.txt, .md o Google Doc)
# dentro de la carpeta de la instancia. El nombre del archivo decide qué dato es.
_DETAIL_PATTERNS = {
    "version": re.compile(r"^(versi[oó]n|version)\b", re.I),
    "mods": re.compile(r"^mods?\b", re.I),
    "experience": re.compile(r"^(experiencia|tipo)\b", re.I),
    "status": re.compile(r"^(estado|status)\b", re.I),
    "before": re.compile(r"^(antes|before|checklist|requisitos)\b", re.I),
    "news": re.compile(r"^(novedades|news|noticias|changelog)\b", re.I),
    "server": re.compile(r"^(servidor|server|ip)\b", re.I),
}
_ICON_NAME_RE = re.compile(r"^(icon|icono|logo)\b", re.I)
# Imágenes de la galería de Información: galeria 1.png, galeria 2.png, foto 3.jpg, captura 4.png...
_GALLERY_NAME_RE = re.compile(r"^(galer[ií]a|gallery|imagen|imagenes|im[aá]genes|img|foto|fotos|captura|screenshot)", re.I)


def _gallery_images(files: list[dict], api_key: str) -> list[dict]:
    """Imágenes de galería ordenadas por número del nombre (galeria 2 antes que galeria 10).
    'n' es el número que se usa en la descripción con [img 1, 2]; sin número en el nombre, su posición."""
    pics = [f for f in files if _is_image(f) and _GALLERY_NAME_RE.match(f["name"])]

    def sort_key(f):
        m = re.search(r"\d+", f["name"])
        return (int(m.group(0)) if m else 10**9, f["name"].lower())

    pics.sort(key=sort_key)
    out = []
    for idx, f in enumerate(pics, start=1):
        m = re.search(r"\d+", f["name"])
        out.append({"n": int(m.group(0)) if m else idx, "url": media_url(f["id"], api_key)})
    return out
_BULLET_RE = re.compile(r"^[\s\-\*\u2022\u2713\u2714\u2611]+")


def _is_text_file(f: dict) -> bool:
    return f.get("mimeType") in ("text/plain", "text/markdown", GOOGLE_DOC_MIME) \
        or f["name"].lower().endswith((".txt", ".md"))


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def _bullet_lines(text: str) -> list[str]:
    lines = (_BULLET_RE.sub("", ln).strip() for ln in (text or "").splitlines())
    return [ln for ln in lines if ln]


def _parse_detail(key: str, text: str):
    if key == "before":
        return _bullet_lines(text)
    if key == "news":
        m = re.search(r"https?://\S+", text or "")
        return m.group(0).rstrip(").,;") if m else ""
    return _first_line(text)


def list_instances(folder_value: str, api_key: str) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    root = folder_id_from(folder_value)
    subfolders = _list(
        f"'{root}' in parents and mimeType='{FOLDER_MIME}' and trashed=false",
        "id,name", api_key, order_by="name",
    )
    if not subfolders:
        return []

    files_by_parent = _files_by_parent(subfolders, api_key)

    instances = []
    jobs = []   # (instancia, clave, archivo) de todos los textos que hay que leer
    for folder in subfolders:
        files = files_by_parent.get(folder["id"], [])
        packs = [f for f in files if f["name"].lower().endswith(".mrpack")]
        if not packs:
            continue
        pack = max(packs, key=lambda f: f.get("modifiedTime", ""))

        all_images = [f for f in files if _is_image(f)]
        icons = [f for f in all_images if _ICON_NAME_RE.match(f["name"])]
        gallery = _gallery_images(files, api_key)
        images = [f for f in all_images if f not in icons and not _GALLERY_NAME_RE.match(f["name"])]
        images.sort(key=lambda f: (not re.match(r"(cover|portada)", f["name"], re.I), f["name"].lower()))
        videos = [f for f in files if _is_video(f)]
        videos.sort(key=lambda f: (not re.match(r"(cover|portada)", f["name"], re.I), f["name"].lower()))
        info_file = next((f for f in files if _is_info(f)), None)

        inst = {
            "id": f"drive-{folder['id']}",
            "name": folder["name"],
            "description": "",
            "info": "",
            "details": {},
            "gallery": gallery,
            "icon": media_url(icons[0]["id"], api_key) if icons else "",
            "image": media_url(images[0]["id"], api_key) if images else "",
            "video": media_url(videos[0]["id"], api_key) if videos else "",
            "video_version": ((videos[0].get("md5Checksum") or videos[0].get("modifiedTime") or "")[:12]) if videos else "",
            "video_name": videos[0]["name"] if videos else "",
            "source": "url",
            "download_url": media_url(pack["id"], api_key),
            "filename": pack["name"],
            "version_number": (pack.get("md5Checksum") or pack.get("modifiedTime") or "")[:12],
        }
        instances.append(inst)

        if info_file:
            jobs.append((inst, "info", info_file))
        for key, rx in _DETAIL_PATTERNS.items():
            f = next((f for f in files if f is not info_file and _is_text_file(f) and rx.match(f["name"])), None)
            if f:
                jobs.append((inst, key, f))

    if jobs:
        with ThreadPoolExecutor(max_workers=8) as pool:
            texts = list(pool.map(lambda j: _read_text(j[2], api_key), jobs))
        for (inst, key, _f), text in zip(jobs, texts):
            if key == "info":
                inst["info"] = text
                inst["description"] = _first_line(text)
            else:
                value = _parse_detail(key, text)
                if value:
                    inst["details"][key] = value
    return instances


WHITELIST_FILE_RE = re.compile(r"^whitelist(\.txt)?$", re.I)
_MODE_LINE_RE = re.compile(r"^modo\s*[:=]\s*(\S+)", re.I)
_PUBLIC_WORDS = {"publico", "público", "public", "abierto", "todos"}
_NAME_RE = re.compile(r"^([A-Za-z0-9_]{3,16})\b")


def parse_whitelist(text: str) -> dict:
    mode = "whitelist"
    names = []
    for raw in text.replace("\ufeff", "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _MODE_LINE_RE.match(line)
        if m:
            mode = "public" if m.group(1).lower() in _PUBLIC_WORDS else "whitelist"
            continue
        m = _NAME_RE.match(line)
        if m:
            names.append(m.group(1).lower())
    return {"mode": mode, "names": names}


def fetch_whitelist(folder_value: str, api_key: str) -> dict:
    root = folder_id_from(folder_value)
    candidates = _list(
        f"'{root}' in parents and trashed=false and name contains 'whitelist'",
        "id,name,mimeType", api_key,
    )
    found = next((f for f in candidates if WHITELIST_FILE_RE.match(f["name"])), None)
    if found is None:
        return {"mode": "whitelist", "names": []}

    if found["mimeType"] == "application/vnd.google-apps.document":
        r = requests.get(f"{API}/{found['id']}/export",
                         params={"mimeType": "text/plain", "key": api_key}, timeout=TIMEOUT)
    else:
        r = requests.get(f"{API}/{found['id']}", params={"alt": "media", "key": api_key}, timeout=TIMEOUT)
    r.raise_for_status()
    cfg = parse_whitelist(r.content.decode("utf-8-sig", errors="replace"))
    return cfg
