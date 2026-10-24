from __future__ import annotations

import re
import sys
import threading
import shutil
import uuid
import os
from pathlib import Path
from typing import Optional

import paths
import securestore
import vault
import gamelog
import skins
import gamewatch
import instance_migration
import smooth_progress
import auth
import launcher_core as core
import profiles
import mods_manager
import packs_manager
import modpacks_manager
import updater
import modrinth
import downloads
import video_cache
import image_cache
import requests
import drive_folder
import server_status
import settings as app_settings
import studio_config
import running_state
import presence
import discord_presence


_SECRET_RE = re.compile(r"([?&](?:key|api_key|apikey|token|access_token)=)[^&\s'\")]+", re.I)
_URL_RE = re.compile(r"https?://\S+")


def _log_real_error(e) -> None:
    """Deja en access.log la causa real (sin claves ni URLs) aunque al usuario se le muestre un mensaje genérico."""
    try:
        text = _URL_RE.sub("<url>", _SECRET_RE.sub(r"\1***", str(e)))[:300]
        status = getattr(getattr(e, "response", None), "status_code", None) or getattr(e, "status", None)
        extra = f" [HTTP {status}]" if status else ""
        paths.log_event("error", f"{type(e).__name__}{extra}: {text}")
    except Exception:
        pass


def _public_error(e) -> str:
    _log_real_error(e)
    text = str(e) or "Ha ocurrido un error."
    low = text.lower()
    if isinstance(e, requests.RequestException) or "google" in low or "googleapis" in low or "drive" in low \
            or "api key" in low or "clave" in low:
        return "No se pudo completar la operación. Comprueba tu conexión e inténtalo de nuevo más tarde."
    text = _SECRET_RE.sub(r"\1", text)
    return _URL_RE.sub("", text).strip() or "Ha ocurrido un error."


class Api:
    def __init__(self):
        self._window = None
        self._emit_hook = None   # la ventana Tauri recibe los eventos a través de server.py
        self._account: Optional[auth.Account] = None
        self._mc_dir = paths.GAME_DIR   # carpeta propia (no .minecraft): las instancias no se mezclan con otras
        self._running: dict = {}
        self._instances_cache: Optional[list] = None
        self._instances_cache_time: float = 0.0
        self._wl_cache: Optional[dict] = None
        self._wl_cache_time: float = 0.0
        self._installing_instances: set = set()
        self._manifest_lock = threading.Lock()
        self._manifest_fetch_failed = False

        for profile_id, pid in running_state.load_alive().items():
            self._running[profile_id] = {"process": None, "pid": pid}
            restored_profile = profiles.get_profile(profile_id)
            if restored_profile:
                discord_presence.set_playing(restored_profile.name)
            threading.Thread(target=self._watch_restored_process, args=(profile_id, pid), daemon=True).start()

        try:  # instancias que estaban en .minecraft\instances -> carpeta propia (una sola vez, nunca bloquea el arranque)
            instance_migration.migrate_instances(
                Path(core.default_minecraft_directory()), self._mc_dir, profiles.list_profiles(),
                skip_ids=set(self._running), release=vault.release_instance,
                log=lambda m: paths.log_event("migracion", m))
        except Exception as e:
            paths.log_event("migracion", f"error: {type(e).__name__}: {e}")

        paths.log_event("vault", "seguridad activa: build vault-13 (todo cifrado + instancias en carpeta propia + barra suave + compatibilidad con mods)")
        for _plain in (auth.MS_SESSION_FILE, self._WL_CACHE_FILE, self._MANIFEST_CACHE_FILE):
            securestore.upgrade(_plain)
        threading.Thread(target=self._vault_recover, daemon=True).start()
        threading.Thread(target=self._presence_loop, daemon=True).start()

    @staticmethod
    def _frontend_dir() -> Path:
        return paths.app_root_dir() / "frontend"


    def _seal_profile(self, profile_id: str) -> None:
        """Vuelve a cifrar una instancia oficial y borra las copias en claro."""
        profile = profiles.get_profile(profile_id)
        if profile is None or not profile.instance_ref:
            return
        try:
            inst_dir = profiles.instance_directory(self._mc_dir, profile)
            vault.seal(inst_dir, profile.instance_ref)
            paths.log_event("vault", f"cifrado OK: {profile.name} · protección contra borrado: {vault.delete_protection_status(inst_dir)}")
        except Exception as e:
            paths.log_event("vault", f"CIFRADO FALLÓ en '{profile.name}': {type(e).__name__}: {e}")

    def _vault_recover(self) -> None:
        """Al arrancar: cifra (o migra) instancias oficiales y limpia restos en claro."""
        for profile in profiles.list_profiles():
            if profile.instance_ref and profile.id not in self._running:
                self._seal_profile(profile.id)

    def _mark_running(self, profile_id: str, process=None, pid: Optional[int] = None):
        self._running[profile_id] = {"process": process, "pid": pid if pid is not None else (process.pid if process else None)}
        self._persist_running()

    def _mark_stopped(self, profile_id: str):
        self._running.pop(profile_id, None)
        self._persist_running()

    def _sync_discord_after_stop(self):
        remaining = list(self._running.keys())
        if remaining:
            other = profiles.get_profile(remaining[0])
            discord_presence.set_playing(other.name if other else "otra instancia")
        else:
            discord_presence.set_idle()

    def _persist_running(self):
        mapping = {pid_key: entry["pid"] for pid_key, entry in self._running.items() if entry.get("pid")}
        running_state.save(mapping)

    def _watch_restored_process(self, profile_id: str, pid: int):
        import time
        while running_state.is_pid_alive(pid):
            time.sleep(3)
        entry = self._running.get(profile_id)
        if entry is not None and entry.get("pid") == pid:
            self._seal_profile(profile_id)
            self._mark_stopped(profile_id)
            self._sync_discord_after_stop()
            self._emit("game_closed", {"profileId": profile_id, "exitCode": None})

    def _presence_loop(self):
        import time
        if not presence.is_configured():
            self._emit("presence_update", {"available": False, "count": 0})
        while True:
            if presence.is_configured():
                label = self._account.username if self._account else ""
                presence.send_heartbeat(label)
                count = presence.get_online_count()
                if count is None:
                    self._emit("presence_update", {"available": False, "count": 0})
                else:
                    self._emit("presence_update", {"available": True, "count": count})
            if discord_presence.is_configured():
                discord_presence.refresh()
            time.sleep(20)

    def _emit(self, event: str, payload: dict):
        if self._emit_hook is not None:
            try:
                self._emit_hook(event, payload)
            except Exception:
                pass


    # Minimizar / maximizar / cerrar y el selector de archivos los resuelve la ventana Tauri (Rust).
    def minimize_window(self):
        return {"ok": True}

    def toggle_maximize_window(self):
        return {"ok": True}

    def close_window(self):
        return {"ok": True}


    def login_offline(self, username: str):
        try:
            account = auth.login_offline(username)
            self._account = account
            return {"ok": True, "account": self._account_dict(account)}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}

    def login_microsoft(self):
        def worker():
            try:
                account = auth.login_microsoft(
                    status_callback=lambda msg: self._emit("ms_login_status", {"message": msg})
                )
                self._account = account
                self._emit("ms_login_done", {"ok": True, "account": self._account_dict(account)})
            except Exception as e:
                self._emit("ms_login_done", {"ok": False, "error": _public_error(e)})

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "started": True}

    def logout(self):
        self._account = None
        auth.clear_ms_session()
        return {"ok": True}

    def get_account(self):
        if self._account is None:
            return None
        return self._account_dict(self._account)

    def has_saved_session(self):
        return auth.has_saved_ms_session()

    def try_restore_session(self):
        def worker():
            account = auth.try_restore_microsoft_session()
            if account:
                self._account = account
                self._emit("session_restored", {"ok": True, "account": self._account_dict(account)})
            else:
                self._emit("session_restored", {"ok": False})

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "started": True}

    def list_recent_offline_usernames(self):
        return auth.list_recent_offline_usernames()

    def _account_dict(self, account: auth.Account) -> dict:
        return {
            "username": account.username,
            "uuid": account.uuid,
            "isOffline": account.is_offline,
            "skinUrl": account.skin_url,
            "capeUrl": account.cape_url,
        }


    def get_wardrobe(self):
        """Datos para el Vestidor: skin/modelo actuales y las capas oficiales de la cuenta."""
        if self._account is None:
            return {"ok": False, "error": "Debes iniciar sesión primero"}
        if self._account.is_offline:
            return {"ok": True, "offline": True, "skinUrl": None, "variant": "classic", "capes": []}
        try:
            profile = auth.fetch_full_profile(self._account.access_token)
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}
        skins_list = profile.get("skins") or []
        active_skin = next((s for s in skins_list if s.get("state") == "ACTIVE"), None)
        capes = [
            {"id": c.get("id"), "url": c.get("url"), "alias": c.get("alias") or "Capa",
             "active": c.get("state") == "ACTIVE"}
            for c in (profile.get("capes") or [])
        ]
        return {
            "ok": True, "offline": False,
            "skinUrl": (active_skin or {}).get("url"),
            "variant": ((active_skin or {}).get("variant") or "CLASSIC").lower(),
            "capes": capes,
        }

    def pick_skin_file(self):
        """El selector de archivos nativo lo abre la ventana Tauri; aquí solo llega si ésta no lo atendió."""
        return {"ok": False, "error": "El selector de archivos no está disponible"}

    def read_skin_preview(self, file_path: str):
        """Valida el archivo elegido y devuelve una vista previa (data URL) SIN subir nada todavía."""
        import base64
        try:
            skins.validate_skin_file(Path(file_path))
            data = Path(file_path).read_bytes()
        except skins.SkinError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}
        return {"ok": True, "dataUrl": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}

    def apply_skin(self, file_path: str, variant: str):
        if self._account is None:
            return {"ok": False, "error": "Debes iniciar sesión primero"}
        if self._account.is_offline:
            return {"ok": False, "error": "Necesitas iniciar sesión con una cuenta de Microsoft con Minecraft para cambiar la skin."}
        try:
            skins.upload_skin(self._account.access_token, Path(file_path), variant)
        except skins.SkinError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}
        return {"ok": True}

    def set_active_cape(self, cape_id: Optional[str]):
        if self._account is None:
            return {"ok": False, "error": "Debes iniciar sesión primero"}
        if self._account.is_offline:
            return {"ok": False, "error": "Necesitas iniciar sesión con una cuenta de Microsoft con Minecraft para cambiar la capa."}
        try:
            skins.set_cape(self._account.access_token, cape_id or None)
        except skins.SkinError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}
        return {"ok": True}

    _WL_TTL_SECONDS = 60
    _WL_CACHE_FILE = Path.home() / ".chechenitza_studio_whitelist_cache.json"

    # --- Caché offline de la whitelist -------------------------------------
    # Nunca se guardan los nombres en claro: solo hashes con sal, firmados y con
    # caducidad. Así el archivo no revela quién está autorizado y no se puede
    # editar a mano para colarse cuando no hay internet.
    _WL_OFFLINE_MAX_AGE = 3 * 24 * 3600

    @staticmethod
    def _wl_hash(name: str, salt: str) -> str:
        import hashlib
        return hashlib.sha256(f"{salt}:{name.lower()}".encode("utf-8")).hexdigest()

    @staticmethod
    def _wl_key() -> bytes:
        import hashlib
        seed = f"{paths.APP_ID}|{studio_config.DRIVE_API_KEY}|{presence._device_id()}"
        return hashlib.sha256(seed.encode("utf-8")).digest()

    @classmethod
    def _wl_sign(cls, payload: dict) -> str:
        import hashlib
        import hmac
        import json
        body = json.dumps({k: payload[k] for k in ("mode", "salt", "hashes", "ts")}, sort_keys=True)
        return hmac.new(cls._wl_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()

    @classmethod
    def _wl_cache_save(cls, cfg: dict) -> None:
        import os
        import time
        salt = os.urandom(8).hex()
        payload = {
            "mode": cfg.get("mode"),
            "salt": salt,
            "hashes": sorted(cls._wl_hash(n, salt) for n in cfg.get("names", [])),
            "ts": int(time.time()),
        }
        payload["sig"] = cls._wl_sign(payload)
        securestore.write(cls._WL_CACHE_FILE, payload)

    @classmethod
    def _wl_cache_load(cls) -> Optional[dict]:
        import hmac
        import time
        try:
            raw = securestore.read(cls._WL_CACHE_FILE)
            if not hmac.compare_digest(str(raw.get("sig", "")), cls._wl_sign(raw)):
                return None
            if time.time() - int(raw["ts"]) > cls._WL_OFFLINE_MAX_AGE:
                return None
            return {"mode": raw.get("mode"), "salt": raw["salt"], "hashes": raw["hashes"]}
        except Exception:
            return None

    @classmethod
    def _wl_contains(cls, cfg: dict, username: str) -> bool:
        if "names" in cfg:
            return username.lower() in cfg["names"]
        return cls._wl_hash(username, cfg.get("salt", "")) in set(cfg.get("hashes", []))

    def _whitelist_config(self) -> Optional[dict]:
        import json
        import time

        if self._wl_cache is not None and time.time() - self._wl_cache_time < self._WL_TTL_SECONDS:
            return self._wl_cache

        cfg = None
        try:
            cfg = drive_folder.fetch_whitelist(studio_config.DRIVE_FOLDER_ID, studio_config.DRIVE_API_KEY)
            try:
                self._wl_cache_save(cfg)
            except Exception:
                pass  # guardar la caché es opcional; nunca debe bloquear el acceso
        except (requests.ConnectionError, requests.Timeout):
            cfg = self._wl_cache_load()
        except Exception:
            cfg = None

        if cfg is not None:
            self._wl_cache = cfg
            self._wl_cache_time = time.time()
        return cfg

    def _access_status(self) -> str:
        account = self._account
        if account is None:
            return "login"
        if not (studio_config.DRIVE_FOLDER_ID and studio_config.DRIVE_API_KEY):
            return "allowed"
        cfg = self._whitelist_config()
        if cfg is None:
            return "unverified"
        if cfg.get("mode") == "public":
            return "allowed"
        if account.is_offline:
            return "denied"
        return "allowed" if self._wl_contains(cfg, account.username) else "denied"

    @staticmethod
    def _access_error(status: str) -> str:
        return {
            "login": "Inicia sesión con tu cuenta de Microsoft para continuar.",
            "denied": "Tu cuenta no está autorizada para usar este launcher.",
            "unverified": "No se pudo comprobar tu acceso. Revisa tu conexión a internet.",
        }.get(status, "Acceso no permitido.")

    def check_access(self, force: bool = False):
        if force:
            self._wl_cache = None
        status = self._access_status()
        return {"ok": True, "status": status,
                "username": self._account.username if self._account else None}


    def get_vanilla_versions(self, include_snapshots: bool = False):
        try:
            return {"ok": True, "versions": core.list_vanilla_versions(include_snapshots)}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}


    def list_profiles(self):
        return [self._profile_dict(p) for p in profiles.list_profiles()]

    def create_profile(self, name: str, version: str, loader: str = "none",
                        loader_version: Optional[str] = None, ram_mb: int = 2048,
                        icon_color: str = "#ff2d55"):
        p = profiles.create_profile(name, version, loader, loader_version, ram_mb, icon_color)
        return self._profile_dict(p)

    def edit_profile(self, profile_id: str, name: str, version: str, loader: str = "none",
                      loader_version: Optional[str] = None, ram_mb: int = 2048,
                      icon_color: str = "#ff2d55"):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        if profile_id in self._running:
            return {"ok": False, "error": "Cierra Minecraft antes de modificar este perfil."}

        if loader == profile.loader and loader_version is None:
            loader_version = profile.loader_version

        final_name = name.strip() or profile.name

        changes = {
            "name": final_name,
            "version": version,
            "loader": loader,
            "loader_version": loader_version,
            "ram_mb": ram_mb,
            "icon_color": icon_color,
        }
        if version != profile.version or loader != profile.loader or loader_version != profile.loader_version:
            changes["resolved_version_id"] = None

        if final_name != profile.name:
            old_dir = profiles.instance_directory(self._mc_dir, profile)
            new_base = profiles.sanitize_folder_name(final_name) or profile.id
            new_dir_name = profiles.unique_instance_dir_name(new_base, exclude_profile_id=profile.id)
            if old_dir.exists() and new_dir_name != profile.instance_dir_name:
                new_dir = old_dir.parent / new_dir_name
                try:
                    old_dir.rename(new_dir)
                    changes["instance_dir_name"] = new_dir_name
                except Exception as e:
                    return {"ok": False, "error": f"No se pudo renombrar la carpeta del perfil: {_public_error(e)}"}
            else:
                changes["instance_dir_name"] = new_dir_name

        updated = profiles.update_profile(profile_id, **changes)
        return {"ok": True, "profile": self._profile_dict(updated)}

    def delete_profile(self, profile_id: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        if profile_id in self._running:
            return {"ok": False, "error": "No puedes eliminar un perfil mientras Minecraft está en ejecución en él."}

        instance_dir = profiles.instance_directory(self._mc_dir, profile)
        folder_error = None
        if instance_dir.exists():
            folder_error = self._force_delete_folder(instance_dir)

        if folder_error:
            return {"ok": False, "error": f"No se pudo borrar la carpeta del perfil: {folder_error}"}

        ok = profiles.delete_profile(profile_id)
        return {"ok": ok}

    @staticmethod
    def _force_delete_folder(path: Path) -> Optional[str]:
        import stat

        def _on_error(func, path_, exc_info):
            try:
                os.chmod(path_, stat.S_IWRITE)
                func(path_)
            except Exception:
                raise

        try:
            vault.release_instance(path)  # quita la protección: desinstalar desde el launcher es la única vía
            shutil.rmtree(path, onerror=_on_error)
            return None
        except Exception as e:
            return (
                f"{e}. Puede que algún archivo esté en uso (cierra Minecraft/el launcher externo "
                f"si lo tienes abierto) o que el antivirus lo esté bloqueando."
            )

    def _profile_dict(self, p: profiles.Profile) -> dict:
        return {
            "id": p.id, "name": p.name, "version": p.version, "loader": p.loader,
            "loaderVersion": p.loader_version, "ramMb": p.ram_mb,
            "iconColor": p.icon_color, "createdAt": p.created_at,
        }


    def _install_game_files(self, profile, instance_dir, progress) -> str:
        """Descarga/instala Minecraft + el cargador (librerías, assets, Java…) y devuelve el id de versión.
        Lo usan tanto el lanzamiento como la instalación de instancias (pantalla de instalación)."""
        if core.is_version_installed(instance_dir, profile.resolved_version_id):
            progress("Usando la instalación ya descargada…", 1, 1)
            return profile.resolved_version_id
        if profile.loader == "forge":
            loader_version = profile.loader_version
            if loader_version is None:
                loader_version = core.find_forge_version_for(profile.version)
                if loader_version:
                    profiles.update_profile(profile.id, loader_version=loader_version)
            return core.install_forge(profile.version, instance_dir, loader_version, progress)
        if profile.loader == "fabric":
            loader_version = profile.loader_version
            if loader_version is None:
                loader_version, used_fallback = core.get_latest_fabric_loader_version()
                profiles.update_profile(profile.id, loader_version=loader_version)
                if used_fallback:
                    progress("No se pudo comprobar la última versión del cargador — usando una de respaldo…", 0, 1)
            return core.install_fabric(profile.version, instance_dir, loader_version, progress)
        if profile.loader in ("neoforge", "quilt"):
            return core.install_mod_loader(
                profile.loader, profile.version, instance_dir, profile.loader_version, progress
            )
        core.install_vanilla(profile.version, instance_dir, progress)
        return profile.version

    def launch_profile(self, profile_id: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        if self._account is None:
            return {"ok": False, "error": "Debes iniciar sesión primero"}
        access = self._access_status()
        if access != "allowed":
            return {"ok": False, "error": self._access_error(access)}
        if profile_id in self._running:
            return {"ok": False, "error": "Ya tienes esta instancia abierta. Ciérrala antes de volver a lanzarla."}

        def worker():
            try:
                instance_dir = profiles.instance_directory(self._mc_dir, profile)

                smooth = smooth_progress.SmoothProgress()   # la barra solo avanza, no va y viene entre fases

                def progress(text, val, mx):
                    value, maximum = smooth.update(val, mx)
                    self._emit("install_progress", {
                        "profileId": profile.id, "text": text or "Instalando…",
                        "value": value, "max": maximum,
                    })

                version_id = self._install_game_files(profile, instance_dir, progress)

                profiles.update_profile(profile.id, resolved_version_id=version_id)

                progress("Comprobando archivos del juego…", 1, 1)
                core.ensure_game_jar(version_id, instance_dir, progress)

                if profile.instance_ref:
                    if not vault.is_sealed(instance_dir) and not (instance_dir / "mods").exists():
                        raise RuntimeError(
                            "Faltan archivos de esta instancia (fue modificada o borrada fuera del launcher). "
                            "Desinstálala desde Instancias y vuelve a instalarla."
                        )
                    vault.unseal(instance_dir, profile.instance_ref)

                value, maximum = smooth.finish()
                self._emit("install_progress", {
                    "profileId": profile.id, "text": "Iniciando Minecraft…", "value": value, "max": maximum,
                })
                process = core.launch(version_id, instance_dir, self._account, ram_mb=app_settings.get_ram_mb())
                self._mark_running(profile.id, process=process)
                discord_presence.set_playing(profile.name)
                self._emit("launch_done", {"ok": True, "profileId": profile.id})
                self._stream_process_output(process, profile.id)
            except Exception as e:
                if profile.id not in self._running:
                    self._seal_profile(profile.id)  # no dejar nada en claro si el lanzamiento falló
                self._emit("launch_done", {"ok": False, "profileId": profile.id, "error": _public_error(e)})

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "started": True}

    def get_running_game(self):
        profile_ids = list(self._running.keys())
        return {"ok": True, "running": bool(profile_ids), "profiles": profile_ids}

    def close_game(self, profile_id: str):
        entry = self._running.get(profile_id)
        if entry is None:
            return {"ok": False, "error": "Esa instancia no tiene ningún Minecraft en ejecución ahora mismo."}
        try:
            if entry.get("process") is not None:
                entry["process"].terminate()
            elif not running_state.terminate_pid(entry.get("pid")):
                return {"ok": False, "error": "No se pudo cerrar Minecraft (el proceso ya no existe)."}
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}

    def _purge_after_load(self, profile_id: str, reason: str = "") -> None:
        """Con el juego ya cargado, quita la carpeta mods del disco."""
        profile = profiles.get_profile(profile_id)
        if profile is None or not profile.instance_ref:
            return
        paths.log_event("vault", f"juego cargado (detectado por {reason or '?'}): retirando mods de {profile.name}")
        try:
            left, locked = vault.purge_runtime(profiles.instance_directory(self._mc_dir, profile), profile.instance_ref)
            if left == 0:
                paths.log_event("vault", f"mods retirados del disco tras la carga: {profile.name}")
            elif left > 0 and locked:
                paths.log_event("vault", f"{left} mod(s) protegidos durante la partida (carpeta oculta y sin listado); se borran al cerrar ({profile.name})")
            elif left > 0:
                paths.log_event("vault", f"AVISO {left} mod(s) siguen en disco y NO se pudo ocultar/bloquear el listado ({profile.name})")
        except Exception as e:
            paths.log_event("vault", f"retirada de mods tras la carga falló: {type(e).__name__}: {e}")

    def _stream_process_output(self, process, profile_id: str):
        try:
            profile = profiles.get_profile(profile_id)
            loaded = threading.Event()
            if profile and profile.instance_ref:
                paths.log_event("vault", f"juego iniciado, esperando la carga: {profile.name}")
                threading.Thread(
                    target=gamewatch.watch_until_loaded,
                    args=(process, loaded, lambda why: self._purge_after_load(profile_id, why)),
                    daemon=True,
                ).start()
            if process.stdout is not None:
                for line in process.stdout:
                    if not loaded.is_set() and gamewatch.line_signals_loaded(line):
                        loaded.set()
            process.wait()
        except Exception:
            pass
        finally:
            exit_code = process.poll()
            try:  # anota los errores del juego en access.log (para diagnosticar mods que no funcionan)
                prof = profiles.get_profile(profile_id)
                if prof:
                    lines = gamelog.summarize(profiles.instance_directory(self._mc_dir, prof) / "logs" / "latest.log")
                    if lines:
                        paths.log_event("juego", f"{prof.name}: {len(lines)} línea(s) relevantes de latest.log:")
                        for ln in lines:
                            paths.log_event("juego", ln)
            except Exception:
                pass
            self._seal_profile(profile_id)  # recifra y borra mods/config en claro
            if profile_id in self._running:
                self._mark_stopped(profile_id)
            self._sync_discord_after_stop()
            self._emit("game_closed", {"profileId": profile_id, "exitCode": exit_code})


    def list_mods(self, profile_id: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        instance_dir = profiles.instance_directory(self._mc_dir, profile)
        mods = mods_manager.list_mods(instance_dir)
        return {"ok": True, "mods": [
            {"filename": m.filename, "enabled": m.enabled, "sizeKb": m.size_kb} for m in mods
        ]}

    def toggle_mod(self, profile_id: str, filename: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        instance_dir = profiles.instance_directory(self._mc_dir, profile)
        try:
            enabled = mods_manager.toggle_mod(instance_dir, filename)
            return {"ok": True, "enabled": enabled}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}

    @staticmethod
    def _open_folder(folder) -> None:
        import subprocess
        import sys
        if sys.platform == "win32":
            import os
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def get_server_status(self, address: str):
        """Estado de un servidor de Minecraft: {ok, online, players, max}."""
        try:
            return server_status.query(address)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_external_url(self, url: str):
        """Abre un enlace http(s) en el navegador del sistema (p. ej. "Ver novedades")."""
        import webbrowser
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return {"ok": False, "error": "Enlace no válido."}
        try:
            webbrowser.open(url)
        except Exception:
            return {"ok": False, "error": "No se pudo abrir el enlace."}
        return {"ok": True}

    def open_screenshots_folder(self, profile_id: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Instancia no encontrada"}
        folder = profiles.instance_directory(self._mc_dir, profile) / "screenshots"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._open_folder(folder)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}

    def open_mods_folder(self, profile_id: str):
        import subprocess
        import sys
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        folder = mods_manager.mods_folder(profiles.instance_directory(self._mc_dir, profile))
        try:
            if sys.platform == "win32":
                import os
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}


    def search_mods_online(self, profile_id: str, query: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        try:
            result = modrinth.search_mods(query, loader=profile.loader, game_version=profile.version)
            return {"ok": True, **result}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo buscar en Modrinth: {_public_error(e)}"}

    def get_mod_online_versions(self, profile_id: str, project_id: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        try:
            versions = modrinth.get_mod_versions(project_id, loader=profile.loader, game_version=profile.version)
            return {"ok": True, "versions": versions}
        except Exception as e:
            return {"ok": False, "error": f"No se pudieron obtener las versiones: {_public_error(e)}"}

    def install_mod_online(self, profile_id: str, download_url: str, filename: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        instance_dir = profiles.instance_directory(self._mc_dir, profile)
        dest_folder = mods_manager.mods_folder(instance_dir)
        try:
            modrinth.download_mod(download_url, filename, dest_folder)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo descargar el mod: {_public_error(e)}"}


    def list_shaderpacks(self, profile_id: str):
        return self._list_packs(profile_id, "shaderpacks")

    def list_resourcepacks(self, profile_id: str):
        return self._list_packs(profile_id, "resourcepacks")

    def open_shaderpacks_folder(self, profile_id: str):
        return self._open_packs_folder(profile_id, "shaderpacks")

    def open_resourcepacks_folder(self, profile_id: str):
        return self._open_packs_folder(profile_id, "resourcepacks")

    def _list_packs(self, profile_id: str, folder_name: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        folder = packs_manager.packs_folder(
            profiles.instance_directory(self._mc_dir, profile), folder_name
        )
        packs = packs_manager.list_packs(folder, include_directories=folder_name == "resourcepacks")
        return {"ok": True, "packs": [
            {"filename": pack.filename, "sizeKb": pack.size_kb} for pack in packs
        ]}

    def _open_packs_folder(self, profile_id: str, folder_name: str):
        import os
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        try:
            folder = packs_manager.packs_folder(
                profiles.instance_directory(self._mc_dir, profile), folder_name
            )
            os.startfile(str(folder))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": _public_error(e)}

    def search_shaderpacks_online(self, profile_id: str, query: str):
        return self._search_packs_online(profile_id, query, "shader")

    def search_resourcepacks_online(self, profile_id: str, query: str):
        return self._search_packs_online(profile_id, query, "resourcepack")

    def get_shaderpack_online_versions(self, profile_id: str, project_id: str):
        return self._get_pack_online_versions(profile_id, project_id)

    def get_resourcepack_online_versions(self, profile_id: str, project_id: str):
        return self._get_pack_online_versions(profile_id, project_id)

    def install_shaderpack_online(self, profile_id: str, download_url: str, filename: str):
        return self._install_pack_online(profile_id, download_url, filename, "shaderpacks")

    def install_resourcepack_online(self, profile_id: str, download_url: str, filename: str):
        return self._install_pack_online(profile_id, download_url, filename, "resourcepacks")

    def _search_packs_online(self, profile_id: str, query: str, project_type: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        try:
            return {"ok": True, **modrinth.search_packs(query, project_type, profile.version)}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo buscar en Modrinth: {_public_error(e)}"}

    def _get_pack_online_versions(self, profile_id: str, project_id: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        try:
            return {"ok": True, "versions": modrinth.get_pack_versions(project_id, profile.version)}
        except Exception as e:
            return {"ok": False, "error": f"No se pudieron obtener las versiones: {_public_error(e)}"}

    def _install_pack_online(self, profile_id: str, download_url: str, filename: str, folder_name: str):
        profile = profiles.get_profile(profile_id)
        if profile is None:
            return {"ok": False, "error": "Perfil no encontrado"}
        try:
            folder = packs_manager.packs_folder(profiles.instance_directory(self._mc_dir, profile), folder_name)
            modrinth.download_mod(download_url, filename, folder)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo descargar el pack: {_public_error(e)}"}


    _MANIFEST_TTL_SECONDS = 300
    _MANIFEST_CACHE_FILE = Path.home() / ".chechenitza_studio_instances_cache.json"

    @staticmethod
    def _clean_manifest(data) -> list:
        if not isinstance(data, list):
            raise ValueError("El manifiesto debe ser una lista de instancias")
        return [e for e in data if isinstance(e, dict) and e.get("id")]

    def _load_instances_manifest(self) -> list:
        import json
        import time

        if self._instances_cache is not None and \
                time.time() - self._instances_cache_time < self._MANIFEST_TTL_SECONDS:
            return self._instances_cache

        with self._manifest_lock:
            if self._instances_cache is not None and \
                    time.time() - self._instances_cache_time < self._MANIFEST_TTL_SECONDS:
                return self._instances_cache

            manifest = None
            self._manifest_fetch_failed = False
            use_folder = bool(studio_config.DRIVE_FOLDER_ID and studio_config.DRIVE_API_KEY)
            if use_folder or studio_config.MANIFEST_URL:
                try:
                    if use_folder:
                        manifest = self._clean_manifest(drive_folder.list_instances(
                            studio_config.DRIVE_FOLDER_ID, studio_config.DRIVE_API_KEY))
                    else:
                        manifest = self._clean_manifest(downloads.fetch_json(studio_config.MANIFEST_URL))
                    try:
                        securestore.write(self._MANIFEST_CACHE_FILE, manifest)
                    except Exception:
                        pass
                except Exception:
                    self._manifest_fetch_failed = True
                    try:
                        manifest = self._clean_manifest(securestore.read(self._MANIFEST_CACHE_FILE))
                    except Exception:
                        manifest = None

            if manifest is None:
                if use_folder or studio_config.MANIFEST_URL:
                    self._manifest_fetch_failed = True
                try:
                    manifest_path = self._frontend_dir() / "instances.json"
                    manifest = self._clean_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
                except Exception:
                    manifest = []

            self._instances_cache = manifest
            self._instances_cache_time = time.time()
            try:
                video_cache.prefetch(
                    (downloads.resolve_url(e.get("video", "") or ""),
                     str(e.get("video_version", "")), e.get("video_name") or e.get("video", ""))
                    for e in manifest if e.get("video"))
            except Exception:
                pass
            return manifest

    @staticmethod
    def _any_drive_id(url: str):
        """Id de Drive tanto de enlaces normales como de la URL de la API (.../drive/v3/files/<id>?alt=media)."""
        import re
        fid = downloads.drive_file_id(url)
        if fid:
            return fid
        m = re.search(r"/drive/v3/files/([\w-]+)", url or "")
        return m.group(1) if m else None

    def _instance_entry_dict(self, entry: dict) -> dict:
        profile = profiles.get_profile_by_instance_ref(entry["id"])

        installed_info = None
        if profile is not None:
            installed_info = modpacks_manager.get_installed_modpack(
                profiles.instance_directory(self._mc_dir, profile)
            )
        installed = installed_info is not None

        wanted_version = entry.get("version_number")
        update_available = bool(
            installed and wanted_version is not None
            and str(installed_info.get("versionNumber")) != str(wanted_version)
        )

        image = entry.get("image", "")
        drive_id = self._any_drive_id(image)
        if drive_id:
            image = f"https://drive.google.com/thumbnail?id={drive_id}&sz=w800"

        icon = entry.get("icon", "") or ""
        icon_drive_id = self._any_drive_id(icon)
        if icon_drive_id:
            icon = f"https://drive.google.com/thumbnail?id={icon_drive_id}&sz=w256"

        gallery = []
        for idx, g in enumerate(entry.get("gallery") or [], start=1):
            g_url = g.get("url", "") if isinstance(g, dict) else str(g or "")
            g_n = g.get("n", idx) if isinstance(g, dict) else idx
            g_id = self._any_drive_id(g_url)
            thumb = f"https://drive.google.com/thumbnail?id={g_id}&sz=w1200" if g_id else g_url
            if g_url:
                gallery.append({"n": g_n, "url": thumb, "fallback": g_url})

        video_remote = downloads.resolve_url(entry.get("video", "") or "")
        video_local = video_cache.local_uri(video_remote, str(entry.get("video_version", "")))
        video = video_local or video_remote

        return {
            "id": entry["id"],
            "name": entry.get("name", entry["id"]),
            "description": entry.get("description", ""),
            "image": image,
            "video": video,
            "videoRemote": video_remote if video_local else "",
            "installed": installed,
            "updateAvailable": update_available,
            "profileId": profile.id if installed else None,
            "version": profile.version if installed else None,
            "loader": profile.loader if installed else None,
            "ramMb": app_settings.get_ram_mb(),
            "info": entry.get("info") or entry.get("description", ""),
            "details": entry.get("details") if isinstance(entry.get("details"), dict) else {},
            "icon": icon,
            "gallery": gallery,
        }

    def cache_image(self, url: str):
        """Descarga (con reintentos) una imagen remota y devuelve su ruta local file:// para mostrarla."""
        try:
            uri = image_cache.get(str(url or ""))
        except Exception:
            uri = None
        return {"ok": bool(uri), "uri": uri or ""}

    def list_instances(self):
        access = self._access_status()
        if access != "allowed":
            return {"ok": True, "instances": [], "blocked": access}
        manifest = self._load_instances_manifest()
        instances = [self._instance_entry_dict(e) for e in manifest]
        try:
            warm = []
            for i in instances:
                warm += [i.get("icon"), i.get("image")] + [g.get("url") for g in i.get("gallery") or []]
            image_cache.prefetch(warm)
        except Exception:
            pass
        return {
            "ok": True,
            "instances": instances,
            "fetchFailed": self._manifest_fetch_failed,
        }

    def list_library(self):
        manifest = self._load_instances_manifest()
        manifest_ids = {e["id"] for e in manifest}
        entries = [self._instance_entry_dict(e) for e in manifest]
        result = [e for e in entries if e["installed"]]

        for p in profiles.list_profiles():
            if not p.instance_ref or p.instance_ref in manifest_ids:
                continue
            info = modpacks_manager.get_installed_modpack(profiles.instance_directory(self._mc_dir, p))
            if info is None:
                continue
            result.append({
                "id": p.instance_ref, "name": p.name, "description": "", "image": "", "video": "",
                "installed": True, "updateAvailable": False, "profileId": p.id,
                "version": p.version, "loader": p.loader, "ramMb": app_settings.get_ram_mb(),
                "info": "", "orphan": True,
            })
        return {"ok": True, "instances": result, "fetchFailed": self._manifest_fetch_failed}

    def uninstall_instance(self, instance_id: str):
        profile = profiles.get_profile_by_instance_ref(instance_id)
        if profile is None:
            return {"ok": False, "error": "Esa instancia no está instalada."}
        if profile.id in self._running:
            return {"ok": False, "error": "Cierra Minecraft antes de desinstalar esta instancia."}
        if instance_id in self._installing_instances:
            return {"ok": False, "error": "Esa instancia se está instalando ahora mismo."}

        instance_dir = profiles.instance_directory(self._mc_dir, profile)
        if instance_dir.exists():
            err = self._force_delete_folder(instance_dir)
            if err:
                return {"ok": False, "error": f"No se pudo borrar la carpeta de la instancia: {err}"}
        profiles.delete_profile(profile.id)
        return {"ok": True}


    def get_settings(self):
        cfg = app_settings.load()
        return {
            "ok": True,
            "ramMb": cfg["ram_mb"],
            "maxRamMb": app_settings.max_ram_mb(),
            "minRamMb": app_settings.MIN_RAM_MB,
            "systemRamMb": app_settings.system_ram_mb(),
            "downloadLimitMb": cfg["download_limit_mb"],
            "maxDownloadLimitMb": app_settings.MAX_DOWNLOAD_LIMIT_MB,
            "gameRunning": bool(self._running),
        }

    def save_settings(self, ram_mb: int, download_limit_mb: int):
        try:
            app_settings.save(ram_mb, download_limit_mb)
            return self.get_settings()
        except Exception as e:
            return {"ok": False, "error": f"No se pudieron guardar los ajustes: {_public_error(e)}"}

    def install_instance(self, instance_id: str):
        access = self._access_status()
        if access != "allowed":
            return {"ok": False, "error": self._access_error(access)}

        manifest = self._load_instances_manifest()
        entry = next((e for e in manifest if e["id"] == instance_id), None)
        if entry is None:
            return {"ok": False, "error": "Instancia no encontrada"}

        profile = profiles.get_profile_by_instance_ref(instance_id)
        if profile is not None and profile.id in self._running:
            return {"ok": False, "error": "Cierra Minecraft antes de reinstalar esta instancia."}

        self._installing_instances.add(instance_id)

        def worker():
            try:
                nonlocal profile
                if profile is None:
                    profile = profiles.create_profile(
                        name=entry.get("name", instance_id),
                        version="Instalando…",
                        loader="none",
                        instance_ref=instance_id,
                    )

                # Dos etapas para la pantalla de instalación:
                #   1) modpack (mods, configs…)  -> 0 % a 50 % de la barra general
                #   2) Minecraft + cargador (librerías, assets…) -> 50 % a 100 %
                # "sub" es el avance de la descarga actual (barra de abajo, "Instalando librerías…").
                stage = {"n": 1, "sub": 0.0}
                game_smooth = smooth_progress.SmoothProgress()

                def progress(text, val, mx):
                    if mx and mx > 1:
                        stage["sub"] = min(1.0, max(0.0, val / mx))
                    if stage["n"] == 1:
                        overall = 0.5 * stage["sub"]
                    else:
                        sv, sm = game_smooth.update(val, mx)
                        overall = 0.5 + 0.5 * (sv / sm)
                    self._emit("instance_install_progress", {
                        "instanceId": instance_id, "text": text,
                        "value": int(overall * 1000), "max": 1000,
                        "stage": stage["n"], "overall": overall, "sub": stage["sub"],
                    })

                progress("Preparando descarga…", 0, 1)

                source = entry.get("source", "modrinth")
                if source == "modrinth":
                    project_id = entry["modrinth_project_id"]
                    pinned_version_id = entry.get("modrinth_version_id")
                    versions = modrinth.get_pack_versions(project_id)
                    if not versions:
                        raise RuntimeError("Ese modpack de Modrinth no tiene ninguna versión disponible.")
                    chosen = versions[0]
                    if pinned_version_id:
                        chosen = next((v for v in versions if v["id"] == pinned_version_id), chosen)
                    download_url, filename, version_number = chosen["downloadUrl"], chosen["filename"], chosen["versionNumber"]
                elif source == "url":
                    download_url = entry["download_url"]
                    filename = entry.get("filename") or download_url.rsplit("/", 1)[-1]
                    version_number = entry.get("version_number")
                else:
                    raise RuntimeError(f"Tipo de fuente de instancia desconocido: {source}")

                instance_dir = profiles.instance_directory(self._mc_dir, profile)

                if modpacks_manager.get_installed_modpack(instance_dir):
                    old_mods = instance_dir / "mods"
                    if old_mods.exists():
                        err = self._force_delete_folder(old_mods)
                        if err:
                            raise RuntimeError(f"No se pudo limpiar la carpeta de mods: {err}")

                vault.destroy(instance_dir)  # reinstalación limpia: se descartan los bloques antiguos

                result = modpacks_manager.install_modpack(
                    download_url, filename, entry.get("name", instance_id), version_number, instance_dir, progress
                )

                vault.seal(instance_dir, instance_id)

                update_kwargs = {"resolved_version_id": None}
                if result.get("minecraftVersion"):
                    update_kwargs["version"] = result["minecraftVersion"]
                if not result.get("unsupportedLoader"):
                    update_kwargs["loader"] = result.get("loader", "none")
                    update_kwargs["loader_version"] = result.get("loaderVersion")
                updated = profiles.update_profile(profile.id, **update_kwargs) or profile

                # Etapa 2: bajar ya Minecraft y el cargador (antes se hacía al darle a Jugar)
                stage["n"], stage["sub"] = 2, 0.0
                progress("Preparando Minecraft…", 0, 1)
                version_id = self._install_game_files(updated, instance_dir, progress)
                profiles.update_profile(profile.id, resolved_version_id=version_id)
                progress("Comprobando archivos del juego…", 0, 1)
                core.ensure_game_jar(version_id, instance_dir, progress)
                self._emit("instance_install_progress", {
                    "instanceId": instance_id, "text": "Listo", "value": 1000, "max": 1000,
                    "stage": 2, "overall": 1.0, "sub": 1.0,
                })

                self._emit("instance_install_done", {
                    "ok": True, "instanceId": instance_id,
                    "instance": self._instance_entry_dict(entry),
                    "modpack": result,
                })
            except Exception as e:
                self._emit("instance_install_done", {"ok": False, "instanceId": instance_id, "error": _public_error(e)})
            finally:
                self._installing_instances.discard(instance_id)

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "started": True}


    def list_installed_modpacks(self):
        result = []
        for p in profiles.list_profiles():
            instance_dir = profiles.instance_directory(self._mc_dir, p)
            info = modpacks_manager.get_installed_modpack(instance_dir)
            if info:
                result.append({"profile": self._profile_dict(p), "modpack": info})
        return {"ok": True, "modpacks": result}

    def search_modpacks_online(self, query: str):
        try:
            return {"ok": True, **modrinth.search_packs(query, "modpack")}
        except Exception as e:
            return {"ok": False, "error": f"No se pudo buscar en Modrinth: {_public_error(e)}"}

    def get_modpack_online_versions(self, project_id: str):
        try:
            return {"ok": True, "versions": modrinth.get_pack_versions(project_id)}
        except Exception as e:
            return {"ok": False, "error": f"No se pudieron obtener las versiones: {_public_error(e)}"}

    def install_modpack_online(self, download_url: str, filename: str, title: str = "", version_number: str = ""):
        install_id = uuid.uuid4().hex[:12]
        profile_name = (title or filename or "Modpack").strip()

        def worker():
            try:
                def progress(text, val, mx):
                    self._emit("modpack_install_progress", {
                        "installId": install_id, "text": text, "value": val, "max": mx,
                    })

                progress("Creando el perfil…", 0, 1)
                profile = profiles.create_profile(name=profile_name, version="Instalando…", loader="none")
                instance_dir = profiles.instance_directory(self._mc_dir, profile)

                result = modpacks_manager.install_modpack(
                    download_url, filename, title, version_number, instance_dir, progress
                )

                update_kwargs = {"resolved_version_id": None}
                if result.get("minecraftVersion"):
                    update_kwargs["version"] = result["minecraftVersion"]
                if not result.get("unsupportedLoader"):
                    update_kwargs["loader"] = result.get("loader", "none")
                    update_kwargs["loader_version"] = result.get("loaderVersion")
                updated = profiles.update_profile(profile.id, **update_kwargs)

                self._emit("modpack_install_done", {
                    "ok": True, "installId": install_id,
                    "modpack": result, "profile": self._profile_dict(updated),
                })
            except Exception as e:
                self._emit("modpack_install_done", {"ok": False, "installId": install_id, "error": _public_error(e)})

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "started": True, "installId": install_id}


    def get_current_version(self):
        return updater.CURRENT_VERSION

    def check_for_updates(self):
        # Las actualizaciones las gestiona el actualizador de Tauri (automático, al abrir el launcher).
        return {"ok": True, "updateAvailable": False, "currentVersion": updater.CURRENT_VERSION}
