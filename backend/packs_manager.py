from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PackEntry:
    filename: str
    size_kb: int


def packs_folder(instance_dir: Path, folder_name: str) -> Path:
    if folder_name not in {"shaderpacks", "resourcepacks"}:
        raise ValueError("Carpeta de packs no válida")
    folder = Path(instance_dir) / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def list_packs(folder: Path, include_directories: bool = False) -> list[PackEntry]:
    entries = []
    for item in sorted(folder.iterdir(), key=lambda path: path.name.lower()):
        if item.is_file() and item.suffix.lower() == ".zip":
            size_kb = max(1, item.stat().st_size // 1024)
        elif include_directories and item.is_dir():
            size_kb = 0
        else:
            continue
        entries.append(PackEntry(filename=item.name, size_kb=size_kb))
    return entries
