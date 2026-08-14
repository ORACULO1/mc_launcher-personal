"""
launcher_core.py
Envuelve minecraft_launcher_lib para las tres operaciones que necesita la GUI:

  1. Listar versiones disponibles (vanilla, con o sin snapshots).
  2. Instalar una versión, opcionalmente con Forge o Fabric encima.
  3. Construir el comando de lanzamiento y ejecutarlo.

Todo lo que tarda (descargas, instalación) se ejecuta con un callback de
progreso para poder alimentar una barra de progreso en la interfaz.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

import minecraft_launcher_lib as mll

from auth import Account

ProgressCallback = Callable[[str, int, int], None]  # (texto, valor, máximo)


def default_minecraft_directory() -> Path:
    return Path(mll.utils.get_minecraft_directory())


def list_vanilla_versions(include_snapshots: bool = False) -> list[str]:
    versions = mll.utils.get_version_list()
    result = []
    for v in versions:
        if v["type"] == "release" or (include_snapshots and v["type"] == "snapshot"):
            result.append(v["id"])
    return result


def list_forge_versions_for(vanilla_version: str) -> list[str]:
    all_forge = mll.forge.list_forge_versions()
    prefix = f"{vanilla_version}-"
    return [v for v in all_forge if v.startswith(prefix)]


def list_installed_versions(minecraft_directory: Path) -> list[str]:
    return [v["id"] for v in mll.utils.get_installed_versions(str(minecraft_directory))]


def _make_lib_callback(progress: Optional[ProgressCallback]) -> dict:
    if progress is None:
        return {}

    state = {"max": 0, "status": ""}

    def set_status(text: str):
        state["status"] = text
        progress(text, 0, max(state["max"], 1))

    def set_max(value: int):
        state["max"] = value
        progress(state["status"], 0, max(value, 1))

    def set_progress(value: int):
        progress(state["status"], value, max(state["max"], 1))

    return {
        "setStatus": set_status,
        "setMax": set_max,
        "setProgress": set_progress,
    }


def install_vanilla(version: str, minecraft_directory: Path, progress: Optional[ProgressCallback] = None) -> None:
    minecraft_directory.mkdir(parents=True, exist_ok=True)
    mll.install.install_minecraft_version(
        version, str(minecraft_directory), callback=_make_lib_callback(progress)
    )


def install_forge(vanilla_version: str, minecraft_directory: Path,
                   forge_version: Optional[str] = None,
                   progress: Optional[ProgressCallback] = None) -> str:
    """Instala Forge para vanilla_version. Si no se especifica forge_version,
    usa la recomendada automáticamente. Devuelve el id de versión resultante
    (el que hay que pasar a get_minecraft_command)."""
    minecraft_directory.mkdir(parents=True, exist_ok=True)

    if forge_version is None:
        found = mll.forge.find_forge_version(vanilla_version)
        if not found:
            raise RuntimeError(f"No hay Forge disponible para la versión {vanilla_version}.")
        forge_version = found

    if not mll.forge.is_forge_version_valid(forge_version):
        raise RuntimeError(f"La versión de Forge {forge_version} no es válida.")

    # Forge necesita que la versión vanilla base ya esté instalada.
    install_vanilla(vanilla_version, minecraft_directory, progress)
    mll.forge.install_forge_version(
        forge_version, str(minecraft_directory), callback=_make_lib_callback(progress)
    )
    return mll.forge.forge_to_installed_version(forge_version)


def install_fabric(vanilla_version: str, minecraft_directory: Path,
                    loader_version: Optional[str] = None,
                    progress: Optional[ProgressCallback] = None) -> str:
    """Instala Fabric para vanilla_version. Devuelve el id de versión
    resultante, con el formato fabric-loader-<loader>-<vanilla>."""
    minecraft_directory.mkdir(parents=True, exist_ok=True)

    if loader_version is None:
        loader_version = mll.fabric.get_latest_loader_version()

    mll.fabric.install_fabric(
        vanilla_version, str(minecraft_directory),
        loader_version=loader_version, callback=_make_lib_callback(progress)
    )
    return f"fabric-loader-{loader_version}-{vanilla_version}"


def launch(version_id: str, minecraft_directory: Path, account: Account,
           ram_mb: int = 2048, window_width: int = 925, window_height: int = 530,
           java_path: Optional[str] = None) -> subprocess.Popen:
    """Construye el comando y lanza Minecraft como un proceso independiente."""
    options: mll.types.MinecraftOptions = {
        "username": account.username,
        "uuid": account.uuid,
        "token": account.access_token or "0",  # "0" es válido para partidas offline
        "jvmArguments": [f"-Xmx{ram_mb}M", f"-Xms{min(ram_mb, 1024)}M"],
        "customResolution": True,
        "resolutionWidth": str(window_width),
        "resolutionHeight": str(window_height),
        "launcherName": "MiLauncher",
        "launcherVersion": "1.0",
    }
    if java_path:
        options["executablePath"] = java_path

    command = mll.command.get_minecraft_command(version_id, str(minecraft_directory), options)
    return subprocess.Popen(command, cwd=str(minecraft_directory))
