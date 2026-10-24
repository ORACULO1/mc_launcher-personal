"""Ubicación de los datos de seguridad de Chechenitza Studio (clave del vault y registro de diagnóstico).

No cambia dónde guarda nada el resto del launcher: perfiles, ajustes, sesión, cachés, etc. siguen
exactamente donde estaban. Esta carpeta solo la usan el cifrado de instancias y el registro.

  Windows : C:\\Users\\<usuario>\\.chechenitza_studio_system  (oculta)
  Otros   : ~/.chechenitza_studio_system
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "ChechenitzaStudio"   # identifica a este launcher (secreto propio para la clave del vault)
SYSTEM_DIR = Path.home() / ".chechenitza_studio_system"

# Carpeta propia del launcher (aparte de .minecraft): aquí viven las instancias, así no se mezclan con las de
# otros launchers ni con el Minecraft oficial.
#   Windows : C:\Users\<usuario>\AppData\Roaming\ChechenitzaStudio\instances\<instancia>
if sys.platform == "win32":
    GAME_DIR = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "ChechenitzaStudio"
else:
    GAME_DIR = Path.home() / ".local" / "share" / "ChechenitzaStudio"
SYSTEM_DIR.mkdir(parents=True, exist_ok=True)

def hide_path(path) -> None:
    """Oculta una carpeta en Windows con los atributos Oculto + Sistema: el Explorador no la muestra ni
    siquiera con "Mostrar archivos ocultos" (solo aparecería quitando también "Ocultar archivos protegidos
    del sistema operativo"). En otros sistemas no hace nada."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM = 0x2, 0x4
        get, setter = ctypes.windll.kernel32.GetFileAttributesW, ctypes.windll.kernel32.SetFileAttributesW
        current = get(str(path))
        if current == 0xFFFFFFFF:      # INVALID_FILE_ATTRIBUTES: no existe
            return
        wanted = current | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
        if wanted != current:
            setter(str(path), wanted)
    except Exception:
        pass


hide_path(SYSTEM_DIR)


def is_frozen() -> bool:
    """True si se ejecuta como .exe compilado (con PyInstaller o con Nuitka). False en codigo fuente.

    PyInstaller marca esto con sys.frozen. Nuitka (--standalone / --onefile) NO pone sys.frozen:
    cada modulo que compila recibe en su lugar la marca "__compiled__" en sus propios globals(),
    por eso aqui se comprueba en los globals() de ESTE modulo (paths.py tambien se compila entero)."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def app_root_dir() -> Path:
    """Carpeta donde viven los datos empaquetados (frontend/...), tanto compilado como en codigo fuente.

      PyInstaller : sys._MEIPASS (disposicion plana: frontend/ junto a los modulos).
      Nuitka      : junto a este modulo compilado (disposicion plana tambien: no hay backend/ en runtime,
                    Nuitka no conserva la carpeta backend/ porque no es un paquete de Python).
      Codigo fuente: un nivel por encima de backend/, que es donde vive frontend/ en el repositorio.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)                      # type: ignore[attr-defined]
    here = Path(__file__).resolve().parent
    return here if "__compiled__" in globals() else here.parent


def log_event(tag: str, message: str) -> None:
    """Línea de diagnóstico en access.log (sin datos sensibles)."""
    try:
        import time
        log = SYSTEM_DIR / "access.log"
        if log.exists() and log.stat().st_size > 50_000:
            log.unlink()
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {tag}: {message}\n")
    except Exception:
        pass
