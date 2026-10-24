"""Guardado cifrado de JSON en disco.

Windows : DPAPI (CryptProtectData). Solo el mismo usuario de Windows en este
          equipo puede descifrarlo; copiar el archivo a otro PC no sirve.
Otros   : AES-256-GCM con una clave aleatoria local (archivo con permisos 0600).
Los formatos anteriores (texto plano y el cifrador "G4S-G1") se siguen leyendo y se
migran al formato nuevo en la siguiente escritura.

Los archivos antiguos en texto plano se siguen leyendo y se cifran al guardar.
"""
from __future__ import annotations

import ctypes
import getpass
import hashlib
import hmac
import json
import os
import socket
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import paths

_MAGIC_WIN = b"G4S-W1"
_MAGIC_GEN = b"G4S-G1"   # solo lectura (formato antiguo, clave adivinable)
_MAGIC_AES = b"G4S-A2"
_KEY_FILE = paths.SYSTEM_DIR / "store.key"
_ENTROPY = f"{paths.APP_ID}-store-v1".encode("utf-8")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    in_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    blob_in = _Blob(len(data), ctypes.cast(in_buf, ctypes.c_void_p))
    blob_ent = _Blob(len(_ENTROPY), ctypes.cast(ent_buf, ctypes.c_void_p))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = (ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None, 0, ctypes.byref(blob_out))
    if not fn(*args):
        raise OSError("DPAPI falló")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _gen_key() -> bytes:
    seed = f"{paths.APP_ID}|{getpass.getuser()}|{socket.gethostname()}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    out, counter = bytearray(), 0
    while len(out) < length:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:length])


def _gen_encrypt(data: bytes) -> bytes:
    key, nonce = _gen_key(), os.urandom(16)
    body = bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data))))
    mac = hmac.new(key, nonce + body, hashlib.sha256).digest()
    return nonce + mac + body


def _gen_decrypt(blob: bytes) -> bytes:
    key, nonce, mac, body = _gen_key(), blob[:16], blob[16:48], blob[48:]
    if not hmac.compare_digest(mac, hmac.new(key, nonce + body, hashlib.sha256).digest()):
        raise ValueError("archivo alterado")
    return bytes(a ^ b for a, b in zip(body, _stream(key, nonce, len(body))))


def _aes_key() -> bytes:
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes()
        if len(key) == 32:
            return key
    key = os.urandom(32)
    tmp = _KEY_FILE.with_name(_KEY_FILE.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    os.replace(tmp, _KEY_FILE)
    return key


def _aes_encrypt(data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_aes_key()).encrypt(nonce, data, _MAGIC_AES)


def _aes_decrypt(blob: bytes) -> bytes:
    return AESGCM(_aes_key()).decrypt(blob[:12], blob[12:], _MAGIC_AES)


def write(path: Path, obj: Any) -> None:
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    data = None
    if sys.platform == "win32":
        try:
            data = _MAGIC_WIN + _dpapi(raw, True)
        except Exception:
            data = None  # DPAPI no disponible: se usa el cifrado genérico
    if data is None:
        data = _MAGIC_AES + _aes_encrypt(raw)
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # escritura atómica: nunca queda un archivo a medias


def read(path: Path) -> Any:
    data = Path(path).read_bytes()
    if data.startswith(_MAGIC_WIN):
        raw = _dpapi(data[len(_MAGIC_WIN):], False)
    elif data.startswith(_MAGIC_AES):
        raw = _aes_decrypt(data[len(_MAGIC_AES):])
    elif data.startswith(_MAGIC_GEN):
        raw = _gen_decrypt(data[len(_MAGIC_GEN):])
    else:
        raw = data  # archivo antiguo en texto plano
    return json.loads(raw.decode("utf-8-sig"))


def upgrade(path: Path) -> bool:
    """Si el archivo está en texto plano (versión anterior), lo reescribe cifrado.
    Devuelve True si lo migró; no hace nada si ya está cifrado o no existe."""
    try:
        p = Path(path)
        data = p.read_bytes()
        if data.startswith((_MAGIC_WIN, _MAGIC_AES, _MAGIC_GEN)):
            return False
        write(p, json.loads(data.decode("utf-8-sig")))
        return True
    except Exception:
        return False
