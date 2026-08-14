"""
auth.py
Maneja dos formas de "iniciar sesión":

1. Cuenta de Microsoft (oficial): usa minecraft_launcher_lib.microsoft_account
   con el flujo OAuth "authorization code + PKCE". El usuario abre una URL en
   su navegador, inicia sesión con su cuenta de Microsoft, y el navegador lo
   redirige a una URL local (http://localhost:<port>/) con un código. Un
   servidor HTTP mínimo, levantado en un hilo aparte, captura ese código.

2. Modo offline / no premium: no hay ningún tipo de "hackeo" ni bypass de
   nada de Mojang/Microsoft; simplemente se genera un UUID determinista a
   partir del nombre de usuario (el mismo algoritmo que usa el propio
   Minecraft para partidas en LAN / servidores offline: MD5 de
   "OfflinePlayer:<nombre>" con los bits de versión ajustados a UUID v3).
   Esto solo funciona en servidores configurados con online-mode=false o en
   un solo jugador; no da acceso a servidores oficiales ni a Realms.
"""

from __future__ import annotations

import hashlib
import http.server
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Optional

import minecraft_launcher_lib as mll

# ID de cliente público de ejemplo. Para uso serio, registra tu propia app en
# https://portal.azure.com (Azure AD) y reemplaza este valor + añade
# "http://localhost:3003/callback" como Redirect URI de tipo "Web".
CLIENT_ID = "8c476a12-1b58-4b3b-b0b1-8cc2a5c56c21"
REDIRECT_URI = "http://localhost:3003/callback"


@dataclass
class Account:
    username: str
    uuid: str
    access_token: str  # cadena vacía en modo offline
    is_offline: bool
    refresh_token: Optional[str] = None


def offline_uuid(username: str) -> str:
    """Genera un UUID v3 determinista a partir del nombre, igual que hace
    Minecraft internamente para partidas sin conexión."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30  # versión 3
    digest[8] = (digest[8] & 0x3F) | 0x80  # variante RFC 4122
    hex_str = digest.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


def login_offline(username: str) -> Account:
    username = username.strip()
    if not username or len(username) > 16:
        raise ValueError("El nombre de usuario debe tener entre 1 y 16 caracteres.")
    return Account(username=username, uuid=offline_uuid(username), access_token="", is_offline=True)


class _CodeCatcherHandler(http.server.BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    state_expected: Optional[str] = None

    def do_GET(self):  # noqa: N802 (nombre requerido por http.server)
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]

        if code and (self.state_expected is None or state == self.state_expected):
            _CodeCatcherHandler.auth_code = code
            body = "<html><body><h2>Sesión iniciada. Ya puedes cerrar esta pestaña.</h2></body></html>"
        else:
            body = "<html><body><h2>No se recibió un código válido. Vuelve a intentarlo.</h2></body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):  # silencia logs del servidor
        pass


def login_microsoft(status_callback=None) -> Account:
    """Ejecuta el flujo completo de login con Microsoft de forma bloqueante.

    status_callback(str) se llama con mensajes de progreso, útil para
    actualizar la interfaz gráfica.
    """
    def status(msg: str):
        if status_callback:
            status_callback(msg)

    login_url, state, code_verifier = mll.microsoft_account.get_secure_login_data(
        CLIENT_ID, REDIRECT_URI
    )

    _CodeCatcherHandler.auth_code = None
    _CodeCatcherHandler.state_expected = state

    server = http.server.HTTPServer(("localhost", 3003), _CodeCatcherHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    status("Abriendo el navegador para iniciar sesión con Microsoft…")
    webbrowser.open(login_url)

    try:
        while _CodeCatcherHandler.auth_code is None:
            server_thread.join(timeout=0.5)
            if not server_thread.is_alive():
                break
    finally:
        server.shutdown()

    auth_code = _CodeCatcherHandler.auth_code
    if not auth_code:
        raise RuntimeError("No se recibió el código de autorización. ¿Se canceló el login?")

    status("Validando credenciales con Xbox Live y Minecraft…")
    login_data = mll.microsoft_account.complete_login(
        CLIENT_ID, None, REDIRECT_URI, auth_code, code_verifier
    )

    status("Obteniendo perfil de Minecraft…")
    profile = mll.microsoft_account.get_profile(login_data["access_token"])

    return Account(
        username=profile["name"],
        uuid=profile["id"],
        access_token=login_data["access_token"],
        is_offline=False,
        refresh_token=login_data.get("refresh_token"),
    )
