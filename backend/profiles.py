from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

PROFILES_FILE = Path.home() / ".chechenitza_studio_profiles.json"


@dataclass
class Profile:
    id: str
    name: str
    version: str
    loader: str
    loader_version: Optional[str] = None
    resolved_version_id: Optional[str] = None
    ram_mb: int = 2048
    icon_color: str = "#2f6fed"
    instance_dir_name: Optional[str] = None
    instance_ref: Optional[str] = None
    created_at: str = field(default_factory=lambda: "")


def _load_raw() -> list[dict]:
    if PROFILES_FILE.exists():
        try:
            return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_raw(data: list[dict]) -> None:
    PROFILES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_profiles() -> list[Profile]:
    return [Profile(**p) for p in _load_raw()]


def get_profile(profile_id: str) -> Optional[Profile]:
    for p in list_profiles():
        if p.id == profile_id:
            return p
    return None


def get_profile_by_instance_ref(instance_ref: str) -> Optional[Profile]:
    for p in list_profiles():
        if p.instance_ref == instance_ref:
            return p
    return None


_INVALID_FOLDER_CHARS = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_folder_name(name: str) -> str:
    cleaned = "".join(c for c in name.strip() if c not in _INVALID_FOLDER_CHARS)
    cleaned = cleaned.rstrip(". ")
    if not cleaned or cleaned.upper() in _RESERVED_WINDOWS_NAMES:
        return ""
    return cleaned[:64]


def unique_instance_dir_name(base: str, exclude_profile_id: Optional[str] = None) -> str:
    existing = {
        (p.instance_dir_name or p.id)
        for p in list_profiles()
        if p.id != exclude_profile_id
    }
    if base not in existing:
        return base
    i = 2
    while f"{base} ({i})" in existing:
        i += 1
    return f"{base} ({i})"


def create_profile(name: str, version: str, loader: str = "none",
                    loader_version: Optional[str] = None, ram_mb: int = 2048,
                    icon_color: str = "#ff2d55", instance_ref: Optional[str] = None) -> Profile:
    import datetime
    profile_id = uuid.uuid4().hex[:12]
    final_name = name.strip() or version
    dir_base = sanitize_folder_name(final_name) or profile_id
    dir_name = unique_instance_dir_name(dir_base)
    profile = Profile(
        id=profile_id,
        name=final_name,
        version=version,
        loader=loader,
        loader_version=loader_version,
        ram_mb=ram_mb,
        icon_color=icon_color,
        instance_ref=instance_ref,
        instance_dir_name=dir_name,
        created_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    data = _load_raw()
    data.append(asdict(profile))
    _save_raw(data)
    return profile


def update_profile(profile_id: str, **changes) -> Optional[Profile]:
    data = _load_raw()
    for entry in data:
        if entry["id"] == profile_id:
            entry.update(changes)
            _save_raw(data)
            return Profile(**entry)
    return None


def delete_profile(profile_id: str) -> bool:
    data = _load_raw()
    new_data = [p for p in data if p["id"] != profile_id]
    if len(new_data) == len(data):
        return False
    _save_raw(new_data)
    return True


def instance_directory(base_minecraft_dir: Path, profile: Profile) -> Path:
    dir_name = profile.instance_dir_name or profile.id
    return Path(base_minecraft_dir) / "instances" / dir_name
