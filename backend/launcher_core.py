from __future__ import annotations

import re
import subprocess
import sys
import concurrent.futures
from pathlib import Path
from typing import Callable, Optional

import minecraft_launcher_lib as mll

from auth import Account
import fabric_installer


def _with_timeout(func: Callable, timeout: int, error_message: str):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise RuntimeError(error_message)
    except Exception:
        raise RuntimeError(error_message)
    finally:
        executor.shutdown(wait=False)


def get_latest_fabric_loader_version(timeout: int = 8) -> tuple[str, bool]:
    FALLBACK_FABRIC_LOADER_VERSION = "0.19.3"
    try:
        version = _with_timeout(fabric_installer.latest_loader_version, timeout * 2, "timeout")
        return version, False
    except Exception:
        return FALLBACK_FABRIC_LOADER_VERSION, True


def find_forge_version_for(vanilla_version: str, timeout: int = 8) -> Optional[str]:
    return _with_timeout(
        lambda: mll.forge.find_forge_version(vanilla_version),
        timeout,
        "No se pudo conectar con los servidores de Forge para encontrar una versión "
        "compatible. Revisa tu conexión a internet e inténtalo de nuevo.",
    )

ProgressCallback = Callable[[str, int, int], None]


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


def is_version_installed(minecraft_directory: Path, version_id: Optional[str]) -> bool:
    if not version_id:
        return False
    try:
        return version_id in list_installed_versions(minecraft_directory)
    except Exception:
        return False


_HEX_NAME = re.compile(r"[0-9a-f]{32,64}")


def generic_status(text: str, last: str = "") -> str:
    """Convierte lo que informa la librería de Minecraft ("Download libraries/…/archivo.jar") en un texto
    genérico. NUNCA devuelve nombres de archivo: solo frases fijas."""
    low = (text or "").strip().lower()
    if not low:
        return last or "Descargando archivos del juego…"
    installing = low.startswith(("install", "extract", "running", "unpack"))
    if "runtime" in low or "java" in low or "jre" in low:
        return "Instalando Java…" if installing else "Descargando Java…"
    if any(k in low for k in ("forge", "fabric", "quilt", "installer", "loader")):
        return "Instalando el cargador de mods…"
    if _HEX_NAME.search(low) or any(k in low for k in ("asset", "object", "sound", "icon")):
        return "Descargando recursos del juego…"
    if "client" in low:
        return "Descargando el juego…"
    if "librar" in low or ".jar" in low or low.endswith((".zip", ".pom")):
        return "Descargando librerías…"
    if installing:
        return "Instalando archivos del juego…"
    return last or "Descargando archivos del juego…"


def _make_lib_callback(progress: Optional[ProgressCallback]) -> dict:
    if progress is None:
        return {}

    state = {"max": 0, "value": 0, "status": ""}

    def set_status(text: str):
        # Solo cambia el texto (genérico): el progreso se queda donde está, no vuelve a 0 por cada archivo.
        state["status"] = generic_status(text, state["status"])
        progress(state["status"], state["value"], max(state["max"], 1))

    def set_max(value: int):
        state["max"] = value
        state["value"] = 0
        progress(state["status"] or "Descargando archivos del juego…", 0, max(value, 1))

    def set_progress(value: int):
        state["value"] = value
        progress(state["status"] or "Descargando archivos del juego…", value, max(state["max"], 1))

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


def _get_bundled_java_executable(vanilla_version: str, minecraft_directory: Path) -> Optional[str]:
    try:
        client_json = mll.runtime.get_client_json(vanilla_version, str(minecraft_directory))
        component = client_json.get("javaVersion", {}).get("component")
        if not component:
            return None
        return mll.runtime.get_executable_path(component, str(minecraft_directory))
    except Exception:
        return None


def install_forge(vanilla_version: str, minecraft_directory: Path,
                   forge_version: Optional[str] = None,
                   progress: Optional[ProgressCallback] = None) -> str:
    minecraft_directory.mkdir(parents=True, exist_ok=True)

    if forge_version is None:
        found = find_forge_version_for(vanilla_version)
        if not found:
            raise RuntimeError(f"No hay Forge disponible para la versión {vanilla_version}.")
        forge_version = found
    elif "-" not in forge_version:
        forge_version = f"{vanilla_version}-{forge_version}"

    if not mll.forge.is_forge_version_valid(forge_version):
        raise RuntimeError(f"La versión de Forge {forge_version} no es válida.")

    install_vanilla(vanilla_version, minecraft_directory, progress)
    java_path = _get_bundled_java_executable(vanilla_version, minecraft_directory)
    mll.forge.install_forge_version(
        forge_version, str(minecraft_directory), callback=_make_lib_callback(progress),
        java=java_path,
    )
    return mll.forge.forge_to_installed_version(forge_version)


def install_fabric(vanilla_version: str, minecraft_directory: Path,
                    loader_version: Optional[str] = None,
                    progress: Optional[ProgressCallback] = None) -> str:
    minecraft_directory.mkdir(parents=True, exist_ok=True)

    install_vanilla(vanilla_version, minecraft_directory, progress)
    java_path = _get_bundled_java_executable(vanilla_version, minecraft_directory)

    try:
        return fabric_installer.install(
            vanilla_version, minecraft_directory, loader_version, progress,
            fallback_loader_version="0.19.3",
        )
    except fabric_installer.FabricNetworkError as e:
        raise RuntimeError(
            "No se pudo descargar Fabric: ni los servidores oficiales (meta.fabricmc.net) ni el "
            f"servidor de respaldo respondieron. Inténtalo de nuevo en unos minutos. ({e})"
        )
    except Exception:
        pass

    if loader_version is None:
        loader_version, _ = get_latest_fabric_loader_version()
    original_check = mll.fabric.is_minecraft_version_supported
    mll.fabric.is_minecraft_version_supported = lambda version: True
    try:
        _with_timeout(
            lambda: mll.fabric.install_fabric(
                vanilla_version, str(minecraft_directory),
                loader_version=loader_version, callback=_make_lib_callback(progress),
                java=java_path,
            ),
            timeout=120,
            error_message=(
                "No se pudo completar la instalación de Fabric — los servidores de Fabric "
                "(meta.fabricmc.net) no respondieron a tiempo. Revisa tu conexión a internet "
                "o si están caídos ahora mismo, y vuelve a intentarlo en unos minutos."
            ),
        )
    finally:
        mll.fabric.is_minecraft_version_supported = original_check

    return f"fabric-loader-{loader_version}-{vanilla_version}"


def _match_loader_version(loader, vanilla_version: str, wanted: str) -> str:
    try:
        available = _with_timeout(
            lambda: loader.get_loader_versions(vanilla_version, False), 20, "timeout"
        )
    except Exception:
        return wanted
    if wanted in available:
        return wanted
    for candidate in available:
        if candidate.endswith(f"-{wanted}") or candidate.endswith(f"+{wanted}"):
            return candidate
    return wanted


def install_mod_loader(loader_id: str, vanilla_version: str, minecraft_directory: Path,
                        loader_version: Optional[str] = None,
                        progress: Optional[ProgressCallback] = None) -> str:
    from minecraft_launcher_lib import mod_loader as mll_mod_loader

    loader = mll_mod_loader.get_mod_loader(loader_id)
    minecraft_directory.mkdir(parents=True, exist_ok=True)

    install_vanilla(vanilla_version, minecraft_directory, progress)
    java_path = _get_bundled_java_executable(vanilla_version, minecraft_directory)

    if loader_version:
        loader_version = _match_loader_version(loader, vanilla_version, loader_version)

    try:
        return loader.install(
            vanilla_version, str(minecraft_directory),
            loader_version=loader_version, callback=_make_lib_callback(progress), java=java_path,
        )
    except Exception as e:
        raise RuntimeError(
            f"No se pudo instalar {loader.get_name()} para Minecraft {vanilla_version}"
            f"{' (' + loader_version + ')' if loader_version else ''}: {e}"
        )


def _sha1_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _client_jar_ok(minecraft_directory: Path, version_id: str) -> bool:
    import json
    jar = minecraft_directory / "versions" / version_id / f"{version_id}.jar"
    if not jar.exists() or jar.stat().st_size == 0:
        return False
    try:
        info = json.loads((minecraft_directory / "versions" / version_id / f"{version_id}.json").read_text(encoding="utf-8"))
        expected = info["downloads"]["client"]["sha1"]
    except Exception:
        return True
    return _sha1_file(jar) == expected


def ensure_game_jar(version_id: str, minecraft_directory: Path,
                    progress: Optional[ProgressCallback] = None) -> None:
    import json
    import shutil

    version_json = minecraft_directory / "versions" / version_id / f"{version_id}.json"
    if not version_json.exists():
        return
    base = json.loads(version_json.read_text(encoding="utf-8")).get("inheritsFrom") or version_id

    if not _client_jar_ok(minecraft_directory, base):
        if progress:
            progress("Reparando archivos del juego…", 0, 1)
        (minecraft_directory / "versions" / base / f"{base}.jar").unlink(missing_ok=True)
        install_vanilla(base, minecraft_directory, progress)

    if base != version_id:
        source = minecraft_directory / "versions" / base / f"{base}.jar"
        target = minecraft_directory / "versions" / version_id / f"{version_id}.jar"
        if source.exists() and (not target.exists() or target.stat().st_size == 0):
            shutil.copy2(source, target)


def launch(version_id: str, minecraft_directory: Path, account: Account,
           ram_mb: int = 2048, window_width: int = 925, window_height: int = 530,
           java_path: Optional[str] = None) -> subprocess.Popen:
    ram_mb = max(512, min(int(ram_mb), 32 * 1024))
    options: mll.types.MinecraftOptions = {
        "username": account.username,
        "uuid": account.uuid,
        "token": account.access_token or "0",
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

    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    return subprocess.Popen(
        command,
        cwd=str(minecraft_directory),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )
