from __future__ import annotations

import hashlib
import http.server
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import minecraft_launcher_lib as mll

import securestore

CLIENT_ID = "8c476a12-1b58-4b3b-b0b1-8cc2a5c56c21"
REDIRECT_URI = "http://localhost:3003/callback"

RECENT_OFFLINE_USERNAMES_FILE = Path.home() / ".mi_mc_launcher_recent_offline.json"
MAX_RECENT_OFFLINE_USERNAMES = 8


def fetch_full_profile(access_token: str) -> dict:
    """Perfil completo de Minecraft Services (skins[] y capes[] con todas sus variantes/estados).
    Usa el mismo access_token que ya se obtiene al iniciar sesión con Microsoft."""
    return mll.microsoft_account.get_profile(access_token)


def list_recent_offline_usernames() -> list[str]:
    if RECENT_OFFLINE_USERNAMES_FILE.exists():
        try:
            import json
            return json.loads(RECENT_OFFLINE_USERNAMES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _record_recent_offline_username(username: str) -> None:
    import json
    names = list_recent_offline_usernames()
    names = [n for n in names if n.lower() != username.lower()]
    names.insert(0, username)
    names = names[:MAX_RECENT_OFFLINE_USERNAMES]
    try:
        RECENT_OFFLINE_USERNAMES_FILE.write_text(json.dumps(names, indent=2), encoding="utf-8")
    except Exception:
        pass


@dataclass
class Account:
    username: str
    uuid: str
    access_token: str
    is_offline: bool
    refresh_token: Optional[str] = None
    skin_url: Optional[str] = None
    cape_url: Optional[str] = None


def offline_uuid(username: str) -> str:
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    hex_str = digest.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


def fetch_public_skin(username: str) -> tuple[Optional[str], Optional[str]]:
    import base64
    import json as _json
    import requests

    try:
        r = requests.get(
            f"https://api.mojang.com/users/profiles/minecraft/{username}",
            timeout=6,
        )
        if r.status_code != 200:
            return None, None
        uuid_no_dashes = r.json().get("id")
        if not uuid_no_dashes:
            return None, None

        r2 = requests.get(
            f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_no_dashes}",
            timeout=6,
        )
        if r2.status_code != 200:
            return None, None

        properties = r2.json().get("properties", [])
        textures_prop = next((p for p in properties if p.get("name") == "textures"), None)
        if not textures_prop:
            return None, None

        decoded = _json.loads(base64.b64decode(textures_prop["value"]))
        textures = decoded.get("textures", {})
        skin_url = textures.get("SKIN", {}).get("url")
        cape_url = textures.get("CAPE", {}).get("url")
        return skin_url, cape_url
    except Exception:
        return None, None


def login_offline(username: str) -> Account:
    username = username.strip()
    if not username or len(username) > 16:
        raise ValueError("El nombre de usuario debe tener entre 1 y 16 caracteres.")
    skin_url, cape_url = fetch_public_skin(username)
    _record_recent_offline_username(username)
    return Account(
        username=username,
        uuid=offline_uuid(username),
        access_token="",
        is_offline=True,
        skin_url=skin_url,
        cape_url=cape_url,
    )


def _make_code_catcher_handler(state_container: dict):

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [None])[0]
            state = query.get("state", [None])[0]

            expected_state = state_container.get("state_expected")
            if code and (expected_state is None or state == expected_state):
                state_container["auth_code"] = code
                body = "<html><body><h2>Sesión iniciada. Ya puedes cerrar esta pestaña.</h2></body></html>"
            else:
                body = "<html><body><h2>No se recibió un código válido. Vuelve a intentarlo.</h2></body></html>"

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format, *args):
            pass

    return _Handler


def login_microsoft(status_callback=None) -> Account:
    def status(msg: str):
        if status_callback:
            status_callback(msg)

    login_url, state, code_verifier = mll.microsoft_account.get_secure_login_data(
        CLIENT_ID, REDIRECT_URI
    )

    state_container = {"auth_code": None, "state_expected": state}
    handler_cls = _make_code_catcher_handler(state_container)

    try:
        server = http.server.HTTPServer(("localhost", 3003), handler_cls)
    except OSError:
        raise RuntimeError(
            "Ya hay un login de Microsoft en curso (o algo más está usando el puerto 3003). "
            "Espera a que termine el intento anterior antes de volver a intentarlo."
        )

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    status("Abriendo el navegador para iniciar sesión con Microsoft…")
    webbrowser.open(login_url)

    try:
        timeout_seconds = 120
        waited = 0.0
        while state_container["auth_code"] is None and waited < timeout_seconds:
            server_thread.join(timeout=0.5)
            waited += 0.5
            if not server_thread.is_alive():
                break
    finally:
        server.shutdown()

    auth_code = state_container["auth_code"]
    if not auth_code:
        raise RuntimeError(
            "No se recibió el código de autorización (¿se canceló el login o tardó más de 2 minutos?). "
            "Cierra la pestaña del navegador si sigue abierta e inténtalo de nuevo."
        )

    status("Validando credenciales con Xbox Live y Minecraft…")
    try:
        login_data = mll.microsoft_account.complete_login(
            CLIENT_ID, None, REDIRECT_URI, auth_code, code_verifier
        )
    except KeyError:
        raise RuntimeError(
            "Microsoft no devolvió un token válido para este intento de login. Esto suele pasar si "
            "el código de un solo uso ya se usó o expiró (por ejemplo, si le diste clic dos veces al "
            "botón, o tardaste mucho en el navegador). Cierra este mensaje y vuelve a intentarlo una "
            "sola vez, sin cerrar ni recargar la pestaña del navegador que se abre."
        )

    if "access_token" not in login_data:
        raise RuntimeError("Microsoft no devolvió un token de acceso válido. Intenta el login de nuevo.")

    status("Obteniendo perfil de Minecraft…")
    profile = mll.microsoft_account.get_profile(login_data["access_token"])

    if "name" not in profile or "id" not in profile:
        raise RuntimeError(
            "No se pudo obtener el perfil de Minecraft de esta cuenta. "
            "¿Esta cuenta de Microsoft tiene Minecraft comprado y activado?"
        )

    skin_url = None
    cape_url = None
    for skin in profile.get("skins", []):
        if skin.get("state") == "ACTIVE":
            skin_url = skin.get("url")
            break
    for cape in profile.get("capes", []):
        if cape.get("state") == "ACTIVE":
            cape_url = cape.get("url")
            break

    account = Account(
        username=profile["name"],
        uuid=profile["id"],
        access_token=login_data["access_token"],
        is_offline=False,
        refresh_token=login_data.get("refresh_token"),
        skin_url=skin_url,
        cape_url=cape_url,
    )
    if account.refresh_token:
        _save_ms_session(account.refresh_token)
    return account


MS_SESSION_FILE = Path.home() / ".mi_mc_launcher_ms_session.json"


def _save_ms_session(refresh_token: str) -> None:
    import json
    try:
        securestore.write(MS_SESSION_FILE, {"refresh_token": refresh_token})
    except Exception:
        pass


def clear_ms_session() -> None:
    try:
        if MS_SESSION_FILE.exists():
            MS_SESSION_FILE.unlink()
    except Exception:
        pass


def has_saved_ms_session() -> bool:
    return MS_SESSION_FILE.exists()


def try_restore_microsoft_session() -> Optional[Account]:
    import json
    if not MS_SESSION_FILE.exists():
        return None
    try:
        data = securestore.read(MS_SESSION_FILE) or {}
        refresh_token = data.get("refresh_token")
        if not refresh_token:
            return None
        _save_ms_session(refresh_token)  # si estaba en texto plano (versión anterior), se cifra ya

        login_data = mll.microsoft_account.complete_refresh(
            CLIENT_ID, None, REDIRECT_URI, refresh_token
        )
        if "access_token" not in login_data:
            clear_ms_session()
            return None

        profile = mll.microsoft_account.get_profile(login_data["access_token"])
        if "name" not in profile or "id" not in profile:
            clear_ms_session()
            return None

        skin_url = None
        cape_url = None
        for skin in profile.get("skins", []):
            if skin.get("state") == "ACTIVE":
                skin_url = skin.get("url")
                break
        for cape in profile.get("capes", []):
            if cape.get("state") == "ACTIVE":
                cape_url = cape.get("url")
                break

        new_refresh_token = login_data.get("refresh_token", refresh_token)
        _save_ms_session(new_refresh_token)

        return Account(
            username=profile["name"],
            uuid=profile["id"],
            access_token=login_data["access_token"],
            is_offline=False,
            refresh_token=new_refresh_token,
            skin_url=skin_url,
            cape_url=cape_url,
        )
    except Exception:
        return None
