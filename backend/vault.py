"""Vault cifrado para instancias oficiales.

En disco (en reposo) una instancia protegida NO tiene mods ni configs legibles:

    <instancia>/.vault/
        salt.bin            sal aleatoria de la instancia
        manifest.g4v        {ruta_real: id_de_bloque}, cifrado y autenticado
        <32 hex>.g4v        un archivo cifrado por cada original (nombre aleatorio)

Cifrado : AES-256-GCM por bloques de 1 MiB (nonce único por bloque, marca de
          "último bloque" autenticada → detecta truncado, reordenado y cambios).
AAD     : liga cada archivo a su instancia y a su id, así no se pueden intercambiar
          archivos entre instancias ni mover bloques.
Ciclo   : unseal() justo antes de lanzar  →  seal() al cerrar el juego / al arrancar
          el launcher (recuperación tras un cierre inesperado).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import keystore
import paths

VAULT_DIR = ".vault"
MAGIC = b"G4V2"
CHUNK = 1 << 20
TAG = 16

# Nunca cambian durante el juego: tras jugar solo se borra la copia en claro.
IMMUTABLE = ("mods",)
# Carpetas que siempre se protegen. El resto de carpetas del modpack se detecta al instalar.
LEGACY_FOLDERS = ("mods", "config", "defaultconfigs", "kubejs")
PROTECTED = LEGACY_FOLDERS

# NUNCA se cifran: son de Minecraft (públicas y de varios GB), las genera el juego mientras se
# juega, o son datos del jugador (mundos, capturas). Cifrarlas haría el arranque muy lento
# o rompería el juego.
EXCLUDE = frozenset({
    "assets", "libraries", "versions", "runtime", "natives", "bin",
    "saves", "screenshots", "logs", "crash-reports", "backups",
    "cache", "downloads", "debug", "data", "journeymap", "webcache",
})
INFO_FILE = ".modpack_info.json"

# Fecha fija que se pone a los archivos descifrados: si al cerrar sigue igual, el juego no
# los tocó y no hace falta volver a cifrarlos (shaders y resourcepacks pesan cientos de MB).
FIXED_NS = 1_000_000_000 * 10**9

# Los mods como JourneyMap vuelven a abrir su propio .jar tras cargar (ServiceLoader, recursos…).
# Denegar la lectura de los .jar hace que el juego se caiga, así que está desactivado.
LOCK_JAR_READS = False
# Impide listar la carpeta mods durante el juego (no se ven ni los nombres). Si algún mod
# necesitara listarla y diera "acceso denegado", ponlo en False.
DENY_MODS_LISTING = True
# Impide listar la carpeta de la instancia: desde el Explorador no se puede ni entrar a ella,
# así que tampoco se llega a resourcepacks, shaderpacks, saves… navegando. (Quien conozca la
# ruta exacta de una subcarpeta aún podría teclearla: el juego necesita listar esas carpetas.)
DENY_ROOT_LISTING = False
# Carpetas que Minecraft NO necesita listar durante la partida: se les niega el listado.
LIST_DENY_FOLDERS: tuple = ()
_GAME_FOLDERS = ("libraries", "versions", "runtime", "assets")
# Quitar de disco los mods en cuanto el juego carga. Desactivado: algunos mods (WaterMedia/FancyMenu, JourneyMap…)
# vuelven a abrir su propio .jar más tarde y, si ya no está, fallan.
PURGE_MODS_AFTER_LOAD = False
HIDE_FOLDERS = True
# Los .jar se descifran con nombre aleatorio: aunque alguien llegue a la carpeta, no sabe qué es cada uno.
RANDOMIZE_MOD_NAMES = True

_IS_WIN = os.name == "nt"

# ── Ajustes editables (sin recompilar): <carpeta del sistema>\seguridad.json ──────────────────────
SETTINGS_FILE = paths.SYSTEM_DIR / "seguridad.json"
_SETTINGS_DEFAULTS = {
    "retirar_mods_tras_cargar": False,           # borra los .jar del disco al cargar el juego
    "bloquear_listado_mods": True,               # la carpeta mods da "acceso denegado" durante la partida
    "bloquear_listado_instancia": False,         # la carpeta de la instancia da "acceso denegado" durante la partida
    "bloquear_listado_carpetas_del_juego": False,  # idem para libraries, versions, runtime y assets
    "nombres_aleatorios_mods": True,             # los .jar se descifran con nombre aleatorio
    "ocultar_carpetas": True,                    # las carpetas de la instancia se marcan como ocultas
}
_SETTINGS_HELP = ("Cada ajuste es true (activado) o false (desactivado). Reinicia el launcher tras cambiarlos. "
                  "Si algún mod (por ejemplo el vídeo de FancyMenu) no funciona, prueba a poner en false, de uno en uno, "
                  "los de la protección durante la partida.")


def load_settings(path: Path | None = None, create: bool = True) -> dict:
    """Lee seguridad.json (lo crea con los valores por defecto si no existe). Valores inválidos -> por defecto."""
    path = Path(path or SETTINGS_FILE)
    values = dict(_SETTINGS_DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        for key in values:
            if isinstance(raw.get(key), bool):
                values[key] = raw[key]
    except FileNotFoundError:
        if create:
            try:
                path.write_text(json.dumps({"_ayuda": _SETTINGS_HELP, **values}, indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
    except Exception:
        pass
    return values


def apply_settings(values: dict | None = None) -> dict:
    global PURGE_MODS_AFTER_LOAD, DENY_MODS_LISTING, DENY_ROOT_LISTING, LIST_DENY_FOLDERS, RANDOMIZE_MOD_NAMES, HIDE_FOLDERS
    v = values if values is not None else load_settings()
    PURGE_MODS_AFTER_LOAD = v["retirar_mods_tras_cargar"]
    DENY_MODS_LISTING = v["bloquear_listado_mods"]
    DENY_ROOT_LISTING = v["bloquear_listado_instancia"]
    LIST_DENY_FOLDERS = _GAME_FOLDERS if v["bloquear_listado_carpetas_del_juego"] else ()
    RANDOMIZE_MOD_NAMES = v["nombres_aleatorios_mods"]
    HIDE_FOLDERS = v["ocultar_carpetas"]
    return v
_EVERYONE = "*S-1-1-0"       # SID de "Todos"
_LOCK_MARK = "readlock"      # marca en .vault: hay archivos con lectura denegada

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class VaultError(RuntimeError):
    pass


def _lock_for(inst: Path) -> threading.Lock:
    k = str(inst.resolve())
    with _locks_guard:
        return _locks.setdefault(k, threading.Lock())


# ───────────────────────── cifrado por bloques ─────────────────────────

def _nonce(prefix: bytes, i: int) -> bytes:
    return prefix + i.to_bytes(4, "big")


def _encrypt_stream(key: bytes, src: BinaryIO, dst: BinaryIO, aad: bytes) -> None:
    aes, prefix = AESGCM(key), os.urandom(8)
    dst.write(MAGIC + prefix)
    i, buf = 0, src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK)
        last = not nxt
        dst.write(aes.encrypt(_nonce(prefix, i), buf, aad + (b"\x01" if last else b"\x00")))
        if last:
            return
        buf, i = nxt, i + 1


def _decrypt_stream(key: bytes, src: BinaryIO, dst: BinaryIO, aad: bytes) -> None:
    head = src.read(12)
    if len(head) != 12 or head[:4] != MAGIC:
        raise VaultError("formato de archivo inválido")
    aes, prefix, size = AESGCM(key), head[4:], CHUNK + TAG
    i, buf = 0, src.read(size)
    while True:
        nxt = src.read(size) if len(buf) == size else b""
        last = not nxt
        dst.write(aes.decrypt(_nonce(prefix, i), buf, aad + (b"\x01" if last else b"\x00")))
        if last:
            return
        buf, i = nxt, i + 1


def _aad(instance_id: str, name: str) -> bytes:
    return f"G4S|{instance_id}|{name}".encode("utf-8")


# ───────────────────────── utilidades de disco ─────────────────────────

# ───────────────────── bloqueo de lectura (Windows) ─────────────────────
# Un .jar que Java tiene abierto no se puede borrar en Windows. Para esos archivos se
# deniega la lectura a "Todos": los manejadores que el juego ya abrió siguen funcionando,
# pero copiarlos desde el Explorador o abrirlos con otro programa da "acceso denegado".
# Antes de cualquier operación del launcher sobre la carpeta se quita el bloqueo.

def _icacls(*args: str) -> bool:
    if not _IS_WIN:
        return False
    try:
        r = subprocess.run(["icacls", *args], capture_output=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def _set_hidden(path: Path) -> None:
    """Oculta la carpeta (oculta + sistema): el Explorador no la muestra por defecto."""
    if not _IS_WIN or not HIDE_FOLDERS or not path.exists():
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2 | 0x4)  # HIDDEN | SYSTEM
    except Exception:
        pass


def hide_all(inst: Path, folders=None) -> None:
    """Oculta las carpetas protegidas y el vault (solo Windows)."""
    for folder in (folders if folders is not None else detect_folders(inst)):
        _set_hidden(inst / folder)
    _set_hidden(_vdir(inst))


# ─────────────── protección contra borrado manual (Windows) ───────────────
# La carpeta .vault nunca está vacía (blobs cifrados + .keep) y a "Todos" se le deniega
# borrarla y borrar su contenido. Windows no permite eliminar una carpeta que no se puede
# vaciar, así que la instancia no se puede borrar desde el Explorador. El launcher quita
# la protección solo para desinstalar o para reescribir el vault, y la restablece al terminar.

def _can_delete(path: Path) -> bool | None:
    """Comprueba (sin borrar nada) si el usuario puede abrir `path` con permiso de borrado.
    None si no se puede saber (no Windows)."""
    if not _IS_WIN:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW(str(path), 0x00010000, 7, None, 3, 0x02000000, None)  # DELETE, OPEN_EXISTING
        if h is None or h == ctypes.c_void_p(-1).value:
            return False
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    except Exception:
        return None


def delete_protection_status(inst: Path) -> str:
    r = _can_delete(_vdir(Path(inst)) / ".keep")
    return "desconocida" if r is None else ("NO EFECTIVA" if r else "activa")


def protect_instance(inst: Path) -> bool:
    inst = Path(inst)
    vdir = _vdir(inst)
    if not _IS_WIN or not vdir.exists():
        return False
    (vdir / ".keep").write_bytes(b"G4S")
    # Windows permite borrar un archivo si él mismo lo permite O si su carpeta permite borrar hijos:
    # se niegan las dos vías (herencia para lo que haya dentro + denegación explícita en cada archivo).
    ok = _icacls(str(vdir), "/deny", f"{_EVERYONE}:(OI)(CI)(DE,DC)", "/C")
    ok &= _icacls(str(vdir / "*"), "/deny", f"{_EVERYONE}:(DE)", "/C")
    _set_hidden(vdir)
    return ok and _can_delete(vdir / ".keep") is not True


def release_instance(inst: Path) -> None:
    """Quita todas las protecciones (borrado, lectura, listado). Se usa antes de desinstalar."""
    inst = Path(inst)
    if not _IS_WIN:
        return
    vdir = _vdir(inst)
    if vdir.exists():
        _icacls(str(vdir), "/remove:d", _EVERYONE, "/T", "/C")
    _unlock_reads(inst)


def hide_every_dir(inst: Path) -> None:
    """Oculta TODAS las carpetas que haya en la instancia (también las que cree el juego)."""
    inst = Path(inst)
    if not _IS_WIN or not HIDE_FOLDERS:
        return
    try:
        for d in inst.iterdir():
            if d.is_dir() and not d.is_symlink():
                _set_hidden(d)
    except OSError:
        pass


def _lock_listing(inst: Path) -> bool:
    """Oculta todo y niega el listado de la instancia y de las carpetas que el juego no lista."""
    if not _IS_WIN:
        return False
    _mark(inst).write_bytes(b"1")
    hide_every_dir(inst)            # antes de bloquear el listado de la raíz
    ok = True
    for name in LIST_DENY_FOLDERS:
        if (inst / name).exists():
            ok &= _icacls(str(inst / name), "/deny", f"{_EVERYONE}:(RD)", "/C")
    if DENY_ROOT_LISTING:
        ok &= _icacls(str(inst), "/deny", f"{_EVERYONE}:(RD)", "/C")   # la raíz, la última
        try:
            os.listdir(inst)
            return False            # se pudo listar: el bloqueo no es efectivo
        except OSError:
            pass
    return ok


def _dirs_of(base: Path) -> list[Path]:
    """base y todas sus subcarpetas, de la más profunda a la raíz."""
    dirs = [base] + [p for p in base.rglob("*") if p.is_dir() and not p.is_symlink()]
    return sorted(dirs, key=lambda d: len(d.parts), reverse=True)


def _mark(inst: Path) -> Path:
    return inst / ".g4readlock"


def _lock_reads(inst: Path, folder: str) -> bool:
    """Niega la lectura de los archivos y el listado de la carpeta. True si ambos son efectivos."""
    base = inst / folder
    if not _IS_WIN or not base.exists():
        return False
    _mark(inst).write_bytes(b"1")
    sample = next((p for p in base.rglob("*") if p.is_file()), None)
    ok = True
    if LOCK_JAR_READS:
        for d in _dirs_of(base):  # de dentro hacia fuera: las subcarpetas se bloquean al final de su contenido
            ok &= _icacls(str(d / "*"), "/deny", f"{_EVERYONE}:(R)", "/C")
    # Última: la propia carpeta, para que no se pueda ni listar su contenido.
    if DENY_MODS_LISTING:
        ok &= _icacls(str(base), "/deny", f"{_EVERYONE}:(RD)", "/C")
    _set_hidden(base)
    files_blocked = True
    if sample is not None:
        try:
            with open(sample, "rb"):
                files_blocked = False
        except OSError:
            pass
    list_blocked = False
    try:
        os.listdir(base)
    except OSError:
        list_blocked = True
    return ok and (list_blocked or not DENY_MODS_LISTING) and (files_blocked or not LOCK_JAR_READS)


def _unlock_reads(inst: Path) -> None:
    """Quita el bloqueo (de fuera hacia dentro) para que el launcher pueda borrar o reescribir."""
    if not _IS_WIN or not _mark(inst).exists():
        return
    _icacls(str(inst), "/remove:d", _EVERYONE, "/C")                 # la raíz primero: sin esto no se puede listar
    for name in LIST_DENY_FOLDERS:
        if (inst / name).exists():
            _icacls(str(inst / name), "/remove:d", _EVERYONE, "/C")
    for folder in IMMUTABLE:
        base = inst / folder
        if not base.exists():
            continue
        _icacls(str(base), "/remove:d", _EVERYONE, "/C")  # primero la raíz: sin esto no se puede listar
        pending = [base]
        while pending:
            d = pending.pop(0)
            _icacls(str(d / "*"), "/remove:d", _EVERYONE, "/C")
            try:
                pending += [p for p in d.iterdir() if p.is_dir() and not p.is_symlink()]
            except OSError:
                pass
    _mark(inst).unlink(missing_ok=True)


def _rmtree(path: Path, tries: int = 8) -> None:
    """Borra archivo a archivo (un archivo bloqueado no impide borrar el resto) y reintenta."""
    if not path.exists():
        return
    last: Exception | None = None
    for n in range(tries):
        for p in sorted(path.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            try:
                if p.is_dir() and not p.is_symlink():
                    p.rmdir()
                else:
                    os.chmod(p, stat.S_IWRITE)
                    p.unlink()
            except OSError as e:
                last = e
        try:
            path.rmdir()
            return
        except OSError as e:
            last = e
        time.sleep(0.5 * (n + 1))  # Windows suelta el .jar unos instantes después de cerrar
    raise VaultError(f"No se pudo borrar '{path.name}': {last}")


def _rmtree_all(inst: Path, folders=None) -> None:
    _unlock_reads(inst)
    errors = []
    for folder in (folders if folders is not None else detect_folders(inst)):
        try:
            _rmtree(inst / folder)
        except VaultError as e:
            errors.append(str(e))
    if errors:
        raise VaultError("; ".join(errors))


def _atomic_write(path: Path, writer) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            writer(fh)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _safe_rel(rel: str) -> str:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or not _allowed_folder(p.parts[0]):
        raise VaultError("ruta no permitida en el manifiesto")
    return p.as_posix()


# ───────────────────────── manifiesto / clave ─────────────────────────

def _vdir(inst: Path) -> Path:
    return inst / VAULT_DIR


def _allowed_folder(name: str) -> bool:
    return bool(name) and not name.startswith(".") and name.lower() not in EXCLUDE


def detect_folders(inst: Path) -> list[str]:
    """Carpetas del modpack que se protegen: las que instaló el modpack (packFolders) o,
    en instalaciones antiguas, todas las demás que existan, menos las de EXCLUDE."""
    inst = Path(inst)
    names: set[str] = set()
    declared = None
    try:
        declared = json.loads((inst / INFO_FILE).read_text(encoding="utf-8")).get("packFolders")
    except Exception:
        pass
    if isinstance(declared, list):
        names |= {n for n in declared if isinstance(n, str)}
    else:
        try:
            names |= {d.name for d in inst.iterdir() if d.is_dir() and not d.is_symlink()}
        except OSError:
            pass
    return sorted(n for n in names | set(LEGACY_FOLDERS) if _allowed_folder(n))


def _resolve_folders(inst: Path, stored: list[str] | None) -> list[str]:
    if stored is not None:
        return [n for n in stored if _allowed_folder(n)]
    return detect_folders(inst)


def is_sealed(inst: Path) -> bool:
    return (_vdir(inst) / "manifest.g4v").exists()


def _key(inst: Path, instance_id: str) -> bytes:
    vdir = _vdir(inst)
    vdir.mkdir(parents=True, exist_ok=True)
    salt_file = vdir / "salt.bin"
    if not salt_file.exists():
        _atomic_write(salt_file, lambda f: f.write(keystore.new_salt()))
    return keystore.instance_key(instance_id, salt_file.read_bytes())


def _load_manifest(inst: Path, key: bytes, instance_id: str) -> tuple[dict[str, str], list[str] | None]:
    """Devuelve (archivos, carpetas). carpetas es None en manifiestos antiguos (v1)."""
    mf = _vdir(inst) / "manifest.g4v"
    if not mf.exists():
        return {}, None
    out = io.BytesIO()
    try:
        with open(mf, "rb") as fh:
            _decrypt_stream(key, fh, out, _aad(instance_id, "manifest"))
    except InvalidTag:
        raise VaultError("El vault está dañado o fue alterado. Reinstala la instancia.")
    data = json.loads(out.getvalue().decode("utf-8"))
    files = {_safe_rel(r): b for r, b in data.get("files", {}).items()}
    folders = data.get("folders")
    return files, ([f for f in folders if isinstance(f, str)] if isinstance(folders, list) else None)


def _save_manifest(inst: Path, key: bytes, instance_id: str, files: dict[str, str], folders: list[str]) -> None:
    raw = io.BytesIO(json.dumps({"v": 2, "folders": folders, "files": files}).encode("utf-8"))
    _atomic_write(_vdir(inst) / "manifest.g4v",
                  lambda fh: _encrypt_stream(key, raw, fh, _aad(instance_id, "manifest")))


def _plain_files(inst: Path, folder: str) -> list[Path]:
    base = inst / folder
    return [p for p in base.rglob("*") if p.is_file()] if base.exists() else []


def _any_plain(inst: Path, folders=None) -> bool:
    return any((inst / f).exists() for f in (folders if folders is not None else detect_folders(inst)))


# ───────────────────────── API pública ─────────────────────────

def seal(inst: Path, instance_id: str) -> None:
    """Cifra lo que haya en claro y borra las copias en claro. Es idempotente."""
    inst = Path(inst)
    _unlock_reads(inst)             # si quedó bloqueado el listado (cierre inesperado), hay que poder enumerar
    if not _any_plain(inst) and not is_sealed(inst):
        return
    release_instance(inst)          # .vault se reescribe: hay que quitar la protección
    try:
        _seal_locked(inst, instance_id)
    finally:
        if is_sealed(inst):
            protect_instance(inst)
        hide_every_dir(inst)        # lo que no se cifra (saves, libraries…) también queda oculto


def _seal_locked(inst: Path, instance_id: str) -> None:
    with _lock_for(inst):
        if not _any_plain(inst) and not is_sealed(inst):
            return
        _unlock_reads(inst)
        key = _key(inst, instance_id)
        vdir = _vdir(inst)
        old, stored = _load_manifest(inst, key, instance_id)
        folders = _resolve_folders(inst, stored)
        new: dict[str, str] = {}

        def _put(f: Path, rel: str, bid: str) -> None:
            aad = _aad(instance_id, bid)
            _atomic_write(vdir / f"{bid}.g4v", lambda fh: _enc_file(key, f, fh, aad))
            new[rel] = bid

        for folder in folders:
            kept = {r: b for r, b in old.items()
                    if r.split("/")[0] == folder and (vdir / f"{b}.g4v").exists()}
            if folder in IMMUTABLE:
                # Lo ya cifrado se conserva tal cual. Lo que aparezca en claro después se borra.
                new.update(kept)
                if not any(r.split("/")[0] == folder for r in old):  # instalación inicial
                    for f in _plain_files(inst, folder):
                        _put(f, f.relative_to(inst).as_posix(), uuid.uuid4().hex)
                continue
            if not (inst / folder).exists():
                new.update(kept)          # no se descifró: se conserva lo cifrado
                continue
            for f in _plain_files(inst, folder):
                rel = f.relative_to(inst).as_posix()
                bid = old.get(rel)
                if bid and (vdir / f"{bid}.g4v").exists():
                    try:
                        if f.stat().st_mtime_ns == FIXED_NS:   # el juego no lo tocó
                            new[rel] = bid
                            continue
                    except OSError:
                        pass
                _put(f, rel, bid or uuid.uuid4().hex)

        _save_manifest(inst, key, instance_id, new, folders)

        keep = set(new.values())
        for blob in vdir.glob("*.g4v"):
            if blob.stem != "manifest" and blob.stem not in keep:
                blob.unlink(missing_ok=True)

        _rmtree_all(inst, folders)


def _enc_file(key: bytes, path: Path, dst: BinaryIO, aad: bytes) -> None:
    with open(path, "rb") as src:
        _encrypt_stream(key, src, dst, aad)


def unseal(inst: Path, instance_id: str) -> None:
    """Descifra mods y configs justo antes de lanzar el juego."""
    inst = Path(inst)
    _unlock_reads(inst)
    if _any_plain(inst):
        seal(inst, instance_id)  # asienta restos de un cierre inesperado y borra intrusos
    with _lock_for(inst):
        if not is_sealed(inst):
            return
        key = _key(inst, instance_id)
        files, stored = _load_manifest(inst, key, instance_id)
        folders = _resolve_folders(inst, stored)
        vdir = _vdir(inst)
        try:
            for rel, bid in files.items():
                dest = inst / rel
                if RANDOMIZE_MOD_NAMES and rel.split("/")[0] in IMMUTABLE:
                    dest = dest.with_name(uuid.uuid4().hex + dest.suffix)
                dest.parent.mkdir(parents=True, exist_ok=True)
                aad = _aad(instance_id, bid)

                def _w(fh, bid=bid, aad=aad):
                    with open(vdir / f"{bid}.g4v", "rb") as src:
                        _decrypt_stream(key, src, fh, aad)

                try:
                    _atomic_write(dest, _w)
                except InvalidTag:
                    raise VaultError("Un archivo cifrado está dañado o fue alterado. Reinstala la instancia.")
                if rel.split("/")[0] not in IMMUTABLE:
                    os.utime(dest, ns=(FIXED_NS, FIXED_NS))   # marca: "sin tocar desde que se descifró"
            hide_all(inst, folders)
            hide_every_dir(inst)
        except Exception:
            try:
                _rmtree_all(inst, folders)
            except VaultError:
                pass
            raise


def purge_runtime(inst: Path, instance_id: str) -> tuple[int, bool]:
    """Con el juego ya cargado: protege los mods mientras se juega.

    1) Solo si "retirar_mods_tras_cargar" está activado: borra los .jar que se puedan. Solo actúa si el vault
       está cifrado y contiene los mods (nunca pierde datos).
    2) Aplica lo que esté activado en seguridad.json: carpeta mods sin listado, instancia sin listado, etc.
       Lo que quede en disco se elimina al cerrar el juego (seal).

    Devuelve (archivos que siguen en disco, True si su lectura quedó bloqueada).
    (-1, False) si no se hizo nada.
    """
    inst = Path(inst)
    with _lock_for(inst):
        if not is_sealed(inst):
            return -1, False
        key = _key(inst, instance_id)
        files, _stored = _load_manifest(inst, key, instance_id)
        if not any(r.split("/")[0] in IMMUTABLE for r in files):
            return -1, False  # el vault no tiene los mods: no borrar nada
        left, locked = 0, False
        for folder in IMMUTABLE:
            base = inst / folder
            if not base.exists():
                continue
            if PURGE_MODS_AFTER_LOAD:
                for p in sorted(base.rglob("*"), key=lambda x: len(x.parts), reverse=True):
                    try:
                        if p.is_dir() and not p.is_symlink():
                            p.rmdir()
                        else:
                            os.chmod(p, stat.S_IWRITE)
                            p.unlink()
                    except OSError:
                        pass
                try:
                    base.rmdir()
                except OSError:
                    pass
            left += sum(1 for p in base.rglob("*") if p.is_file()) if base.exists() else 0
            if base.exists() and left:
                locked = _lock_reads(inst, folder)
        listing = _lock_listing(inst)       # la instancia entera: sin listado y todo oculto
        return left, (locked or left == 0) and listing


def destroy(inst: Path) -> None:
    """Elimina el vault (se usa antes de reinstalar)."""
    release_instance(Path(inst))
    _rmtree(_vdir(Path(inst)))


apply_settings()   # al importar el módulo: carga seguridad.json
