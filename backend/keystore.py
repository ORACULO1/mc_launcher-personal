"""Jerarquía de claves del vault.

  clave maestra  : 32 bytes aleatorios, guardados con securestore
                   (Windows: DPAPI ligado a usuario+equipo · otros: AES-GCM con clave local).
  clave de instancia : HKDF-SHA256(maestra, salt aleatorio de la instancia, id de la instancia).

La clave maestra nunca va dentro del .exe ni se deriva de datos adivinables
(usuario, hostname...). Cada instancia tiene una clave distinta.
"""
from __future__ import annotations

import os
import threading

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import paths
import securestore

MASTER_FILE = paths.SYSTEM_DIR / "vault_master.bin"
_lock = threading.Lock()
_cached: bytes | None = None


def _master() -> bytes:
    global _cached
    with _lock:
        if _cached is not None:
            return _cached
        if MASTER_FILE.exists():
            key = bytes.fromhex(securestore.read(MASTER_FILE)["k"])
            if len(key) != 32:
                raise RuntimeError("clave maestra corrupta")
        else:
            key = os.urandom(32)
            securestore.write(MASTER_FILE, {"k": key.hex()})
        _cached = key
        return key


def new_salt() -> bytes:
    return os.urandom(16)


def instance_key(instance_id: str, salt: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt,
        info=b"G4S-vault-v1|" + instance_id.encode("utf-8"),
    ).derive(_master())
