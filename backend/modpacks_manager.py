from __future__ import annotations

import datetime
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional

import downloads

USER_AGENT = "ChechenitzaStudio/1.0 (contacto: gleiberlecuzz@gmail.com)"

SUPPORTED_LOADERS = {"forge", "neoforge", "fabric", "quilt"}

ProgressCallback = Callable[[str, int, int], None]

INFO_FILENAME = ".modpack_info.json"


def get_installed_modpack(instance_dir: Path) -> Optional[dict]:
    info_path = Path(instance_dir) / INFO_FILENAME
    if not info_path.exists():
        return None
    try:
        return json.loads(info_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_loader(dependencies: dict) -> tuple[str, Optional[str], bool]:
    if "neoforge" in dependencies:
        return "neoforge", dependencies["neoforge"], False
    if "forge" in dependencies:
        return "forge", dependencies["forge"], False
    if "fabric-loader" in dependencies:
        return "fabric", dependencies["fabric-loader"], False
    if "quilt-loader" in dependencies:
        return "quilt", dependencies["quilt-loader"], False
    return "none", None, False


def _download_label(rel_path: str) -> str:
    """Texto genérico según la carpeta de destino: nunca el nombre del archivo."""
    top = Path(rel_path).parts[0].lower() if len(Path(rel_path).parts) > 1 else ""
    return {
        "mods": "Descargando mods…",
        "resourcepacks": "Descargando resource packs…",
        "shaderpacks": "Descargando shaders…",
        "datapacks": "Descargando datapacks…",
    }.get(top, "Descargando archivos del modpack…")


def install_modpack(download_url: str, filename: str, title: str, version_number: Optional[str],
                     instance_dir: Path, progress: Optional[ProgressCallback] = None) -> dict:
    instance_dir = Path(instance_dir)
    instance_dir.mkdir(parents=True, exist_ok=True)

    def report(text, val, mx):
        if progress:
            progress(text, val, mx)

    report("Descargando el modpack…", 0, 1)

    limiter = downloads.RateLimiter.from_settings()
    pack_folders: set[str] = set()   # carpetas de primer nivel que escribe el modpack (se cifran en instancias oficiales)

    with tempfile.NamedTemporaryFile(suffix=".mrpack", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        downloads.download_to(download_url, tmp, limiter)

    try:
        with zipfile.ZipFile(tmp_path) as zf:
            try:
                index = json.loads(zf.read("modrinth.index.json"))
            except KeyError:
                raise RuntimeError("Este archivo no es un modpack válido de Modrinth (falta modrinth.index.json).")

            dependencies = index.get("dependencies", {})
            minecraft_version = dependencies.get("minecraft")
            loader, loader_version, unsupported_loader = _resolve_loader(dependencies)

            files = [
                f for f in index.get("files", [])
                if f.get("env", {}).get("client", "required") != "unsupported"
            ]

            total = len(files) + 1
            for i, f in enumerate(files, start=1):
                rel_path = f.get("path")
                file_urls = f.get("downloads") or []
                if not rel_path or not file_urls:
                    continue
                dest = instance_dir / rel_path
                if len(Path(rel_path).parts) > 1:
                    pack_folders.add(Path(rel_path).parts[0])
                dest.parent.mkdir(parents=True, exist_ok=True)
                report(_download_label(rel_path), i, total)
                with open(dest, "wb") as out:
                    downloads.download_to(file_urls[0], out, limiter)

            report("Aplicando archivos del modpack (configs, overrides)…", total, total)
            for prefix in ("overrides/", "client-overrides/"):
                for name in zf.namelist():
                    if not name.startswith(prefix) or name.endswith("/"):
                        continue
                    rel = name[len(prefix):]
                    if not rel:
                        continue
                    dest = instance_dir / rel
                    if len(Path(rel).parts) > 1:
                        pack_folders.add(Path(rel).parts[0])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(dest, "wb") as out:
                        out.write(src.read())
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    info = {
        "name": title or index.get("name") or filename,
        "versionNumber": version_number or index.get("versionId"),
        "minecraftVersion": minecraft_version,
        "loader": loader,
        "loaderVersion": loader_version,
        "unsupportedLoader": unsupported_loader,
        "packFolders": sorted(pack_folders),
        "installedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    (instance_dir / INFO_FILENAME).write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info
