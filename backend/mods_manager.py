from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass


@dataclass
class ModEntry:
    filename: str
    enabled: bool
    size_kb: int


def mods_folder(instance_dir: Path) -> Path:
    folder = Path(instance_dir) / "mods"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def list_mods(instance_dir: Path) -> list[ModEntry]:
    folder = mods_folder(instance_dir)
    entries = []
    for file in sorted(folder.iterdir()):
        if not file.is_file():
            continue
        if file.suffix == ".disabled":
            display_name = file.stem
            enabled = False
        elif file.suffix == ".jar":
            display_name = file.name
            enabled = True
        else:
            continue
        entries.append(ModEntry(
            filename=display_name,
            enabled=enabled,
            size_kb=max(1, file.stat().st_size // 1024),
        ))
    return entries


def toggle_mod(instance_dir: Path, filename: str) -> bool:
    folder = mods_folder(instance_dir)
    enabled_path = folder / filename
    disabled_path = folder / f"{filename}.disabled"

    if enabled_path.exists():
        enabled_path.rename(disabled_path)
        return False
    elif disabled_path.exists():
        disabled_path.rename(enabled_path)
        return True
    else:
        raise FileNotFoundError(f"No se encontró el mod {filename}")


def delete_mod(instance_dir: Path, filename: str) -> None:
    folder = mods_folder(instance_dir)
    for candidate in (folder / filename, folder / f"{filename}.disabled"):
        if candidate.exists():
            candidate.unlink()
            return
    raise FileNotFoundError(f"No se encontró el mod {filename}")
