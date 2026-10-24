"""Pruebas del Vestidor (validacion de PNG + API de Mojang + metodos del bridge).
Desarrollo, no se empaqueta."""
import base64, http.server, json, os, struct, sys, tempfile, threading, types
from pathlib import Path
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("minecraft_launcher_lib","minecraft_launcher_lib.utils","minecraft_launcher_lib.install","minecraft_launcher_lib.command",
             "minecraft_launcher_lib.fabric","minecraft_launcher_lib.forge","minecraft_launcher_lib.microsoft_account",
             "minecraft_launcher_lib.types","minecraft_launcher_lib.exceptions","minecraft_launcher_lib.quilt","minecraft_launcher_lib.mod_loader",
             "minecraft_launcher_lib.runtime","pypresence"):
    try: __import__(name)
    except Exception: sys.modules[name] = mock.MagicMock()
sys.modules["webview"] = mock.MagicMock()
import requests
import skins, auth, bridge

def make_png(width, height, body=b"x" * 50) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", 0)
    return sig + ihdr + body

tmp = Path(tempfile.mkdtemp())

# ── 1) validacion de PNG (sin red) ────────────────────────────────────────────
good = tmp / "skin.png"; good.write_bytes(make_png(64, 64))
assert skins.validate_skin_file(good) == (64, 64)
(tmp / "legacy.png").write_bytes(make_png(64, 32))
assert skins.validate_skin_file(tmp / "legacy.png") == (64, 32)
print("1 OK PNG 64x64 y el formato legado 64x32 se aceptan")

for name, data, frag in [
    ("vacio.png", b"", "vacío"),
    ("no_png.png", b"esto no es un png" * 5, "PNG válida"),
    ("chico.png", make_png(32, 32), "64x64"),
    ("ancho.png", make_png(100, 64), "64x64"),
]:
    f = tmp / name; f.write_bytes(data)
    try:
        skins.validate_skin_file(f); raise SystemExit(f"FALLO: acepto {name}")
    except skins.SkinError as e:
        assert frag in str(e), (name, e)
big = tmp / "grande.png"; big.write_bytes(make_png(64, 64, body=b"x" * 100_000))
try:
    skins.validate_skin_file(big); raise SystemExit("FALLO: acepto un archivo enorme")
except skins.SkinError as e:
    assert "grande" in str(e)
try:
    skins.validate_skin_file(tmp / "no_existe.png"); raise SystemExit("FALLO: acepto un archivo inexistente")
except skins.SkinError as e:
    assert "encontró" in str(e)
print("2 OK se rechazan: vacío, no-PNG, tamaño distinto de 64x64, demasiado pesado, inexistente — cada uno con su propio mensaje")

# ── 2) API de Mojang con un servidor local que simula distintas respuestas ───
STATE = {"mode": "ok", "last": None}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _respond(self, code, body=b""):
        self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers()
        if body: self.wfile.write(body)
    def do_POST(self):
        STATE["last"] = ("POST", self.path, dict(self.headers), self.rfile.read(int(self.headers.get("Content-Length", 0))))
        {"ok": lambda: self._respond(200), "unauth": lambda: self._respond(401), "limited": lambda: self._respond(429),
         "bad": lambda: self._respond(400)}[STATE["mode"]]()
    def do_PUT(self):
        STATE["last"] = ("PUT", self.path, dict(self.headers), self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self._respond(200 if STATE["mode"] == "ok" else 401)
    def do_DELETE(self):
        STATE["last"] = ("DELETE", self.path, dict(self.headers), b"")
        self._respond(200 if STATE["mode"] == "ok" else 401)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}/minecraft"

with mock.patch.object(skins, "API_BASE", base):
    STATE["mode"] = "ok"
    skins.upload_skin("TOKEN123", good, "slim")
    method, path, headers, body = STATE["last"]
    assert method == "POST" and path == "/minecraft/profile/skins" and headers["Authorization"] == "Bearer TOKEN123"
    assert b'name="variant"' in body and b"slim" in body and b'name="file"; filename="skin.png"' in body and b"image/png" in body
    print("3 OK subir la skin: POST correcto, con el token, el modelo (slim) y el archivo como multipart")

    for mode, frag in [("unauth", "sesión de Microsoft"), ("limited", "está limitando"), ("bad", "rechazó la imagen")]:
        STATE["mode"] = mode
        try:
            skins.upload_skin("T", good, "classic"); raise SystemExit(f"FALLO: {mode} no lanzo error")
        except skins.SkinError as e:
            assert frag in str(e), (mode, e)
    print("4 OK cada código de error de Mojang (401, 429, 400) da un mensaje en español distinto y entendible")

    try:
        skins.upload_skin("T", good, "ancha"); raise SystemExit("FALLO: acepto un variant invalido")
    except skins.SkinError as e:
        assert "modelo" in str(e)

    STATE["mode"] = "ok"
    skins.set_cape("TOKEN123", "cape-id-1")
    method, path, headers, body = STATE["last"]
    assert method == "PUT" and path == "/minecraft/profile/capes/active" and json.loads(body) == {"capeId": "cape-id-1"}
    skins.set_cape("TOKEN123", None)
    method, path, headers, body = STATE["last"]
    assert method == "DELETE" and path == "/minecraft/profile/capes/active"
    print("5 OK activar una capa usa PUT con su id; quitarla (None) usa DELETE")
srv.shutdown()

# ── 3) metodos del bridge (Api) ───────────────────────────────────────────────
def make_api(account):
    api = bridge.Api.__new__(bridge.Api)
    api._account = account; api._window = mock.MagicMock()
    return api

OFFLINE = types.SimpleNamespace(is_offline=True, access_token="", uuid="x", username="jugador")
ONLINE = types.SimpleNamespace(is_offline=False, access_token="TOKEN-MS", uuid="uuid-1", username="jugador")

assert make_api(None).get_wardrobe() == {"ok": False, "error": "Debes iniciar sesión primero"}
res = make_api(OFFLINE).get_wardrobe()
assert res == {"ok": True, "offline": True, "skinUrl": None, "variant": "classic", "capes": []}
print("6 OK get_wardrobe: sin cuenta pide iniciar sesión; con cuenta sin conexión avisa que es modo offline (sin llamar a Mojang)")

profile = {"skins": [{"state": "ACTIVE", "url": "https://textures/skin1.png", "variant": "SLIM"},
                     {"state": "INACTIVE", "url": "https://textures/skin0.png", "variant": "CLASSIC"}],
          "capes": [{"id": "c1", "url": "https://textures/cape1.png", "alias": "Vanilla", "state": "ACTIVE"},
                    {"id": "c2", "url": "https://textures/cape2.png", "alias": "Migrator", "state": "INACTIVE"}]}
with mock.patch.object(auth, "fetch_full_profile", return_value=profile) as fp:
    res = make_api(ONLINE).get_wardrobe()
    fp.assert_called_once_with("TOKEN-MS")
assert res == {"ok": True, "offline": False, "skinUrl": "https://textures/skin1.png", "variant": "slim",
              "capes": [{"id": "c1", "url": "https://textures/cape1.png", "alias": "Vanilla", "active": True},
                        {"id": "c2", "url": "https://textures/cape2.png", "alias": "Migrator", "active": False}]}
print("7 OK get_wardrobe con cuenta de Microsoft: toma la skin ACTIVA (no la inactiva) y lista las capas con cuál está activa")

with mock.patch.object(auth, "fetch_full_profile", side_effect=RuntimeError("500 server error")):
    res = make_api(ONLINE).get_wardrobe()
assert res["ok"] is False and res["error"]
print("8 OK get_wardrobe: si Mojang falla, no revienta, devuelve un error legible")

api = make_api(ONLINE)
api._window.create_file_dialog.return_value = ["C:\\Users\\x\\skin.png"]
res = api.pick_skin_file()
assert res == {"ok": True, "path": "C:\\Users\\x\\skin.png"}
args, kwargs = api._window.create_file_dialog.call_args
assert kwargs.get("file_types") == ("Imagen PNG (*.png)",) and kwargs.get("allow_multiple") is False
api._window.create_file_dialog.return_value = []       # el jugador cerro el dialogo sin elegir nada
assert api.pick_skin_file() == {"ok": True, "path": None}
assert make_api(ONLINE).__class__(); 
api2 = make_api(ONLINE); api2._window = None
assert api2.pick_skin_file()["ok"] is False
print("9 OK pick_skin_file: abre el selector solo para PNG, sin elegir nada no es un error, y sin ventana no revienta")

res = make_api(ONLINE).read_skin_preview(str(good))
assert res["ok"] and res["dataUrl"].startswith("data:image/png;base64,")
assert base64.b64decode(res["dataUrl"].split(",", 1)[1]) == good.read_bytes()
res_bad = make_api(ONLINE).read_skin_preview(str(tmp / "chico.png"))
try:
    skins.validate_skin_file(tmp / "chico.png")
except skins.SkinError as e:
    expected_msg = str(e)
assert res_bad == {"ok": False, "error": expected_msg}
print("10 OK read_skin_preview: para un PNG valido da un data-URL identico al archivo; para uno invalido da el mismo mensaje que validate_skin_file")

assert make_api(OFFLINE).apply_skin(str(good), "slim")["error"].startswith("Necesitas iniciar sesión")
assert make_api(None).apply_skin(str(good), "slim") == {"ok": False, "error": "Debes iniciar sesión primero"}
with mock.patch.object(skins, "upload_skin") as up:
    res = make_api(ONLINE).apply_skin(str(good), "slim")
    up.assert_called_once_with("TOKEN-MS", Path(str(good)), "slim")
    assert res == {"ok": True}
with mock.patch.object(skins, "upload_skin", side_effect=skins.SkinError("mensaje de prueba")):
    assert make_api(ONLINE).apply_skin(str(good), "slim") == {"ok": False, "error": "mensaje de prueba"}
print("11 OK apply_skin: bloqueado sin cuenta o en modo offline; con cuenta real llama a Mojang con el token correcto y devuelve su error tal cual")

assert make_api(OFFLINE).set_active_cape("c1")["error"].startswith("Necesitas iniciar sesión")
with mock.patch.object(skins, "set_cape") as sc:
    make_api(ONLINE).set_active_cape("c1"); sc.assert_called_once_with("TOKEN-MS", "c1")
    make_api(ONLINE).set_active_cape(None); sc.assert_called_with("TOKEN-MS", None)
print("12 OK set_active_cape: bloqueado en modo offline; con cuenta real pasa el id (o None para quitarla) con el token correcto")
