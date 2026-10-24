"""Mueve las instancias que estaban dentro de .minecraft\\instances a la carpeta propia del launcher.

Solo se mueven las instancias de ESTE launcher (las que figuran en sus perfiles); lo que haya de otros
launchers en .minecraft no se toca. Es seguro repetirlo: si algo falla, la instancia original no se pierde.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Iterable, Optional

import profiles


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def migrate_instances(old_base: Path, new_base: Path, profile_list: Iterable,
                      skip_ids: Iterable[str] = (), release: Optional[Callable[[Path], None]] = None,
                      log: Optional[Callable[[str], None]] = None) -> dict:
    """Devuelve {"moved": [...], "failed": [...]} con los nombres de perfil."""
    old_base, new_base = Path(old_base), Path(new_base)
    result: dict = {"moved": [], "failed": []}
    if _same(old_base, new_base):
        return result
    skip = set(skip_ids)
    say = log or (lambda m: None)

    for p in profile_list:
        if p.id in skip:
            continue                                   # el juego está abierto: no se mueve
        old = profiles.instance_directory(old_base, p)
        new = profiles.instance_directory(new_base, p)
        if not old.is_dir() or new.exists():
            continue
        tmp = new.with_name(new.name + ".migrando")
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            if release:
                release(old)                           # quita permisos de protección (borrado/listado)
                if tmp.exists():
                    release(tmp)
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)  # restos de un intento anterior interrumpido
            try:
                os.rename(old, new)                    # mismo disco: instantáneo
            except OSError:
                shutil.copytree(old, tmp, symlinks=True)   # otro disco: copia completa y luego se cambia el nombre
                os.rename(tmp, new)
                shutil.rmtree(old, ignore_errors=True)
            result["moved"].append(p.name)
            say(f"instancia movida a la carpeta propia: {p.name}")
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            result["failed"].append(p.name)
            say(f"NO se pudo mover '{p.name}': {type(e).__name__}: {e} (queda donde estaba)")

    try:
        (old_base / "instances").rmdir()               # solo si quedó vacía
    except OSError:
        pass
    return result
