"""Vestidor: cambiar la skin y la capa de la cuenta de Minecraft.

Usa el access_token de la sesión activa (el mismo que ya usa el launcher para mostrar la skin
en la pestaña "Skin" y para lanzar el juego) para hablar con la API oficial de Minecraft Services
de Mojang. Solo funciona con cuentas de Microsoft: una cuenta sin conexión no tiene un perfil
real que se pueda modificar.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

import requests

API_BASE = "https://api.minecraftservices.com/minecraft"
MAX_SKIN_BYTES = 32 * 1024   # una skin de 64x64 normal pesa unos pocos KB; de sobra con 32 KB
TIMEOUT = 20


class SkinError(RuntimeError):
    """Error pensado para mostrarse tal cual al jugador (texto en español, sin tecnicismos)."""


def _read_png_size(path: Path) -> tuple[int, int]:
    try:
        with open(path, "rb") as fh:
            head = fh.read(33)
    except OSError as e:
        raise SkinError(f"No se pudo leer el archivo: {e.strerror or e}") from e
    if len(head) < 33 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SkinError("El archivo no es una imagen PNG válida.")
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def validate_skin_file(path: Path) -> tuple[int, int]:
    """Comprueba que el archivo sea una skin válida. Devuelve (ancho, alto) si todo está bien."""
    path = Path(path)
    if not path.is_file():
        raise SkinError("No se encontró el archivo seleccionado.")
    size = path.stat().st_size
    if size == 0:
        raise SkinError("El archivo está vacío.")
    if size > MAX_SKIN_BYTES:
        raise SkinError("El archivo es demasiado grande para ser una skin de Minecraft (una skin normal pesa unos pocos KB).")
    width, height = _read_png_size(path)
    if width != 64 or height not in (32, 64):
        raise SkinError(f"La imagen debe medir 64x64 píxeles (la que elegiste mide {width}x{height}).")
    return width, height


def _friendly_error(status: int, body: str) -> str:
    if status in (401, 403):
        return "Tu sesión de Microsoft ya no es válida para esto. Cierra sesión y vuelve a iniciarla, luego inténtalo de nuevo."
    if status == 429:
        return "Mojang está limitando los cambios por ahora (demasiados seguidos). Espera un minuto y vuelve a intentarlo."
    if status == 400:
        return "Mojang rechazó la imagen. Revisa que sea un PNG de 64x64 válido."
    return f"Mojang respondió con un error inesperado (código {status}). Inténtalo de nuevo en unos minutos."


def upload_skin(access_token: str, file_path: Path, variant: str) -> None:
    """variant: 'classic' (modelo ancho / Wide) o 'slim' (modelo fino / Slim)."""
    if variant not in ("classic", "slim"):
        raise SkinError("Tipo de modelo de skin inválido.")
    file_path = Path(file_path)
    validate_skin_file(file_path)
    data = file_path.read_bytes()
    try:
        r = requests.post(
            f"{API_BASE}/profile/skins",
            headers={"Authorization": f"Bearer {access_token}"},
            data={"variant": variant},
            files={"file": ("skin.png", data, "image/png")},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise SkinError(f"No se pudo conectar con los servidores de Mojang: {e}") from e
    if r.status_code not in (200, 204):
        raise SkinError(_friendly_error(r.status_code, r.text))


def set_cape(access_token: str, cape_id: Optional[str]) -> None:
    """cape_id=None quita la capa activa (deja al personaje sin capa)."""
    try:
        if cape_id:
            r = requests.put(
                f"{API_BASE}/profile/capes/active",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"capeId": cape_id}, timeout=TIMEOUT,
            )
        else:
            r = requests.delete(
                f"{API_BASE}/profile/capes/active",
                headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT,
            )
    except requests.RequestException as e:
        raise SkinError(f"No se pudo conectar con los servidores de Mojang: {e}") from e
    if r.status_code not in (200, 204):
        raise SkinError(_friendly_error(r.status_code, r.text))
