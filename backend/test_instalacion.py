"""Pruebas: textos genéricos, barra que solo avanza y carpeta propia de instancias (desarrollo, no se empaqueta)."""
import hashlib, http.server, io, json, os, re, sys, tempfile, threading, time, types, zipfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("minecraft_launcher_lib","minecraft_launcher_lib.utils","minecraft_launcher_lib.install","minecraft_launcher_lib.command",
             "minecraft_launcher_lib.fabric","minecraft_launcher_lib.forge","minecraft_launcher_lib.microsoft_account",
             "minecraft_launcher_lib.types","minecraft_launcher_lib.exceptions","minecraft_launcher_lib.quilt","minecraft_launcher_lib.mod_loader",
             "minecraft_launcher_lib.runtime","pypresence","webview"):
    try: __import__(name)
    except Exception: sys.modules[name] = mock.MagicMock()
import paths, profiles, launcher_core as core, modpacks_manager, smooth_progress, instance_migration, fabric_installer

GENERIC = {"Descargando Java…", "Instalando Java…", "Instalando el cargador de mods…", "Descargando recursos del juego…",
           "Descargando librerías…", "Descargando el juego…", "Instalando archivos del juego…", "Descargando archivos del juego…"}
HEX40 = lambda i: hashlib.sha1(str(i).encode()).hexdigest()

# ── 1) textos genéricos ───────────────────────────────────────────────────────
g = core.generic_status
assert g("Download libraries") == "Descargando librerías…"
assert g("Download asm-9.6.jar") == "Descargando librerías…"
assert g("Download assets") == "Descargando recursos del juego…" and g("Download " + HEX40(1)) == "Descargando recursos del juego…"
assert g("Download runtime/java-runtime-gamma/bin/java.exe") == "Descargando Java…" and g("Install java runtime") == "Instalando Java…"
assert g("Running forge installer") == "Instalando el cargador de mods…" and g("Download fabric-loader-0.15.jar") == "Instalando el cargador de mods…"
assert g("Download client.jar") == "Descargando el juego…"
assert g("Install something") == "Instalando archivos del juego…"
assert g("Download totally-unknown", "Descargando librerías…") == "Descargando librerías…"       # lo desconocido mantiene el texto anterior
assert g("", "") == "Descargando archivos del juego…"
for nasty in ("Download sodium-fabric-0.5.8+mc1.20.1.jar", "Download " + HEX40(7), "Download C:\\Users\\Pepe\\x.dll", "Download 日本語.jar", "Download mods/secreto.jar", "x" * 500):
    assert g(nasty) in GENERIC, nasty                                                              # SIEMPRE una frase fija, jamás un nombre
print("1 OK textos genéricos: ninguna entrada devuelve nombres de archivo, solo frases fijas (Descargando librerías…, recursos del juego…, Java…)")

# ── 2) la barra solo avanza ───────────────────────────────────────────────────
def mll_like_sequence():
    """Imita a la librería de Minecraft: cada archivo cambia el texto, cada fase reinicia el contador."""
    ev = []
    cb = core._make_lib_callback(lambda t, v, m: ev.append((t, v, m)))
    cb["setStatus"]("Download libraries"); cb["setMax"](40)
    for i in range(40): cb["setStatus"](f"Download lib-{i}.jar"); cb["setProgress"](i + 1)
    cb["setStatus"]("Download assets"); cb["setMax"](3000)
    for i in range(0, 3000, 7): cb["setStatus"]("Download " + HEX40(i)); cb["setProgress"](i)
    cb["setStatus"]("Download runtime"); cb["setMax"](25)
    for i in range(25): cb["setStatus"](f"Download runtime/f{i}"); cb["setProgress"](i)
    cb["setStatus"]("Download client.jar"); cb["setMax"](1); cb["setProgress"](1)
    return ev
raw = mll_like_sequence()
raw_fracs = [v / m for _, v, m in raw]
assert any(b < a - 0.3 for a, b in zip(raw_fracs, raw_fracs[1:])), "la secuencia de prueba debería reproducir el vaivén original"
sp = smooth_progress.SmoothProgress(); out = [sp.update(v, m) for _, v, m in raw]
fr = [v / m for v, m in out]
assert all(b >= a for a, b in zip(fr, fr[1:])), "la barra retrocedió"
assert max(fr) < 1.0 and fr[0] == 0.0 and fr[-1] > 0.8 and all(0 <= f <= 1 for f in fr)
assert {t for t, _, _ in raw} <= GENERIC
print(f"2 OK la barra solo avanza ({len(raw)} avisos de Minecraft: sin ningún retroceso, de {fr[0]:.0%} a {fr[-1]:.0%}) y los textos son siempre frases fijas")
sp = smooth_progress.SmoothProgress(); sp.update(10, 40)
a = sp.update(0, 1)[0]; b = sp.update(0, 1)[0]
assert a == b > 0                                            # un cambio de texto no mueve la barra
sp.update(1, 1); assert sp.overall >= 0.9                    # hito del launcher ("Comprobando archivos…"): barra casi llena
print("3 OK un cambio de texto no mueve la barra; los hitos del launcher la dejan casi llena")

# ── 3) modpack de Modrinth simulado: sin nombres de mods en la pantalla ──────
FILES = {"mods/sodium-fabric-0.5.8.jar": b"a" * 3000, "mods/lithium-SECRETO.jar": b"b" * 3000, "shaderpacks/BSL-v8.zip": b"c" * 3000,
         "resourcepacks/Faithful.zip": b"d" * 3000, "config/extra.toml": b"x=1"}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = PACK if self.path == "/pack.mrpack" else FILES[self.path[1:]]
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
idx = {"name": "Pack", "versionId": "1", "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
       "files": [{"path": p, "downloads": [f"{base}/{p}"], "env": {"client": "required"}} for p in FILES if not p.startswith("config")]}
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("modrinth.index.json", json.dumps(idx)); z.writestr("overrides/config/extra.toml", "x=1"); z.writestr("overrides/kubejs/secret.js", "// privado")
PACK = buf.getvalue()
events = []
instd = Path(tempfile.mkdtemp()) / "inst"
modpacks_manager.install_modpack(f"{base}/pack.mrpack", "Mi-Pack-SECRETO-1.0.mrpack", "Pack", "1.0", instd, lambda t, v, m: events.append((t, v, m)))
texts = [t for t, _, _ in events]
leaks = [t for t in texts if any(x in t.lower() for x in (".jar", ".zip", ".mrpack", "sodium", "lithium", "bsl", "faithful", "secreto", "modrinth"))]
assert not leaks, leaks
assert {"Descargando el modpack…", "Descargando mods…", "Descargando shaders…", "Descargando resource packs…"} <= set(texts), set(texts)
fr = [v / m for _, v, m in events]
assert all(b >= a for a, b in zip(fr, fr[1:])) and fr[-1] == 1.0
assert (instd / "mods" / "sodium-fabric-0.5.8.jar").read_bytes() == FILES["mods/sodium-fabric-0.5.8.jar"] and (instd / "kubejs" / "secret.js").exists()
print("4 OK instalar un modpack: la pantalla dice solo", sorted(set(texts)), "— sin nombres de mods y la barra sube sin retroceder")
srv.shutdown()

# fabric_installer: ya no muestra contadores de archivos
src = Path(fabric_installer.__file__).read_text(encoding="utf-8")
assert "Descargando Fabric (" not in src and "Descargando el cargador de mods…" in src
print("5 OK la instalación de Fabric tampoco muestra nombres ni contadores")

# ── 4) lanzamiento completo a través del bridge real ─────────────────────────
import bridge
prof = profiles.create_profile("Prueba", "1.20.1", loader="fabric")
api = bridge.Api.__new__(bridge.Api)
ev = []; done = threading.Event()
def emit(name, payload):
    ev.append((name, payload))
    if name == "launch_done": done.set()
api._emit = emit; api._running = {}; api._mc_dir = Path(tempfile.mkdtemp())
api._account = types.SimpleNamespace(username="u", uuid="1", access_token="t", is_offline=False)
api._access_status = lambda: "allowed"; api._mark_running = lambda *a, **k: None; api._stream_process_output = lambda *a, **k: None
def fake_install_fabric(version, instance_dir, loader_version, progress):
    for t, v, m in mll_like_sequence_for_bridge(progress): pass
    return "fabric-loader-0.15.0-1.20.1"
def mll_like_sequence_for_bridge(progress):
    cb = core._make_lib_callback(progress)
    cb["setStatus"]("Download libraries"); cb["setMax"](40)
    for i in range(40): cb["setStatus"](f"Download lib-{i}.jar"); cb["setProgress"](i + 1)
    cb["setStatus"]("Download assets"); cb["setMax"](600)
    for i in range(0, 600, 3): cb["setStatus"]("Download " + HEX40(i)); cb["setProgress"](i)
    cb["setStatus"]("Download runtime"); cb["setMax"](25)
    for i in range(25): cb["setStatus"](f"Download runtime/f{i}"); cb["setProgress"](i)
    return []
fake_core = types.SimpleNamespace(
    is_version_installed=lambda *a, **k: False, get_latest_fabric_loader_version=lambda: ("0.15.0", False),
    install_fabric=fake_install_fabric, ensure_game_jar=lambda *a, **k: None,
    launch=lambda *a, **k: types.SimpleNamespace(pid=999, stdout=None, poll=lambda: None))
with mock.patch.object(bridge, "core", fake_core), \
     mock.patch.object(bridge, "discord_presence", mock.MagicMock()), mock.patch.object(bridge, "app_settings", mock.MagicMock(get_ram_mb=lambda: 2048)):
    res = api.launch_profile(prof.id)
    assert res.get("ok"), res
    assert done.wait(10), "el lanzamiento no terminó"
prog = [p for n, p in ev if n == "install_progress"]
fr = [p["value"] / p["max"] for p in prog]; tx = [p["text"] for p in prog]
assert [p for n, p in ev if n == "launch_done"][0]["ok"] is True
assert all(b >= a for a, b in zip(fr, fr[1:])), "la barra de lanzamiento retrocedió"
assert fr[-1] == 1.0 and max(fr[:-1]) < 1.0 and tx[-1] == "Iniciando Minecraft…"
assert {t for t in tx[:-1]} <= GENERIC | {"Comprobando archivos del juego…", "Usando la instalación ya descargada…"}, set(tx)
assert not [t for t in tx if re.search(r"\.jar|lib-\d|[0-9a-f]{20,}|runtime/", t)]
print(f"6 OK lanzar una instancia (flujo real del launcher, {len(prog)} avisos): barra 0 %→100 % sin retroceder y textos solo de {sorted(set(tx))}")

# ── 5) carpeta propia + migración desde .minecraft ───────────────────────────
class P:  # perfil mínimo
    def __init__(self, i, name): self.id, self.name, self.instance_dir_name = i, name, name
root = Path(tempfile.mkdtemp()); old_base, new_base = root / ".minecraft", root / "ChechenitzaStudio"
def make(name, content=b"x"):
    d = old_base / "instances" / name; (d / "mods").mkdir(parents=True); (d / "mods" / "m.jar").write_bytes(content); (d / ".vault").mkdir(); (d / ".vault" / "blob.g4v").write_bytes(b"blob")
    return P(name, name)
a, b, c = make("Oficial", b"AAA"), make("Otra", b"BBB"), make("Corriendo", b"CCC")
ajena = old_base / "instances" / "InstanciaDeOtroLauncher"; ajena.mkdir(parents=True); (ajena / "x.txt").write_text("no tocar")
released = []; logs = []
r = instance_migration.migrate_instances(old_base, new_base, [a, b, c], skip_ids={"Corriendo"}, release=released.append, log=logs.append)
assert sorted(r["moved"]) == ["Oficial", "Otra"] and not r["failed"]
assert (new_base / "instances" / "Oficial" / "mods" / "m.jar").read_bytes() == b"AAA" and (new_base / "instances" / "Otra" / ".vault" / "blob.g4v").exists()
assert not (old_base / "instances" / "Oficial").exists()
assert (old_base / "instances" / "Corriendo" / "mods" / "m.jar").exists() and not (new_base / "instances" / "Corriendo").exists()    # con el juego abierto: no se mueve
assert (ajena / "x.txt").read_text() == "no tocar"                                                                           # lo de otros launchers, intacto
assert len(released) == 2 and (old_base / "instances").exists()                                                              # se liberó la protección antes de mover
print("7 OK migración: mueve las instancias de este launcher, deja intactas las de otros launchers y la que está en ejecución")
r2 = instance_migration.migrate_instances(old_base, new_base, [a, b], release=released.append)
assert r2 == {"moved": [], "failed": []}
print("8 OK repetirla no hace nada (no duplica ni pisa)")
# otro disco: os.rename falla -> copia y borra
d = make("OtroDisco", b"DDD"); real_rename = os.rename
def rename_cross(src, dst):
    if str(src).endswith("OtroDisco") and "migrando" not in str(dst): raise OSError(18, "Invalid cross-device link")
    return real_rename(src, dst)
with mock.patch.object(instance_migration.os, "rename", rename_cross):
    r3 = instance_migration.migrate_instances(old_base, new_base, [d])
assert r3["moved"] == ["OtroDisco"] and (new_base / "instances" / "OtroDisco" / "mods" / "m.jar").read_bytes() == b"DDD" and not (old_base / "instances" / "OtroDisco").exists()
assert not list((new_base / "instances").glob("*.migrando"))
print("9 OK entre discos distintos: copia completa, cambia el nombre y borra el original")
# fallo a mitad: el original NO se pierde y no queda una copia a medias
e = make("Falla", b"EEE")
def boom(*a, **k): raise OSError("disco lleno")
with mock.patch.object(instance_migration.os, "rename", side_effect=OSError(18, "x")), mock.patch.object(instance_migration.shutil, "copytree", boom):
    r4 = instance_migration.migrate_instances(old_base, new_base, [e], log=logs.append)
assert r4["failed"] == ["Falla"] and (old_base / "instances" / "Falla" / "mods" / "m.jar").read_bytes() == b"EEE" and not (new_base / "instances" / "Falla").exists()
assert not list((new_base / "instances").glob("*.migrando")) and any("NO se pudo mover" in l for l in logs)
print("10 OK si algo falla a mitad, la instancia original se conserva intacta, no queda nada a medias y se anota en el log")
# restos de un intento interrumpido
f = make("Interrumpida", b"FFF"); stale = new_base / "instances" / "Interrumpida.migrando"; stale.mkdir(parents=True); (stale / "basura").write_text("x")
with mock.patch.object(instance_migration.os, "rename", side_effect=[OSError(18, "x"), None]) as rn, mock.patch.object(instance_migration.shutil, "copytree", lambda s, d, **k: Path(d).mkdir(parents=True, exist_ok=True)):
    pass
r5 = instance_migration.migrate_instances(old_base, new_base, [f])
assert r5["moved"] == ["Interrumpida"] and (new_base / "instances" / "Interrumpida" / "mods" / "m.jar").read_bytes() == b"FFF" and not stale.exists()
print("11 OK restos de un intento anterior interrumpido se limpian")
# vacía la carpeta antigua si queda vacía
assert (old_base / "instances").exists() and (old_base / "instances" / "Falla").exists()      # con contenido (aunque sea 1 instancia que falló) NO se retira
for n in ("Corriendo", "Falla"): __import__("shutil").rmtree(old_base / "instances" / n)
__import__("shutil").rmtree(ajena)
instance_migration.migrate_instances(old_base, new_base, [])
assert not (old_base / "instances").exists()
print("12 OK si .minecraft\\instances queda vacía, se retira (nunca se borra si contiene algo)")

# Api: usa la carpeta propia y migra al arrancar
old2 = Path(tempfile.mkdtemp()) / ".minecraft"
pr = profiles.create_profile("Migrar", "1.20.1"); old_dir = profiles.instance_directory(old2, pr); (old_dir / "mods").mkdir(parents=True); (old_dir / "mods" / "z.jar").write_bytes(b"Z")
with mock.patch.object(bridge.threading, "Thread"), mock.patch.object(bridge.running_state, "load_alive", return_value={}), \
     mock.patch.object(bridge.core, "default_minecraft_directory", return_value=old2):
    api2 = bridge.Api()
assert api2._mc_dir == paths.GAME_DIR and "ChechenitzaStudio" in str(paths.GAME_DIR) and ".minecraft" not in str(paths.GAME_DIR)
assert (paths.GAME_DIR / "instances" / (pr.instance_dir_name or pr.id) / "mods" / "z.jar").read_bytes() == b"Z" and not old_dir.exists()
print("13 OK al arrancar el launcher usa su carpeta propia (", paths.GAME_DIR.name, ") y mueve lo que había en .minecraft")

# ── 6) "Iniciando Minecraft…" y la barra SIEMPRE llega al 100% exacto, sin saltarse la barra suave ──
sp = smooth_progress.SmoothProgress()
sp.update(1, 1)                                  # "Usando la instalación ya descargada…" -> ~90%
assert sp.overall < 1.0
v, m = sp.finish()
assert (v, m) == (smooth_progress.SCALE, smooth_progress.SCALE) and sp.overall == 1.0
print("14 OK smooth.finish() fuerza el 100% real, aunque la fase anterior se hubiera quedado en ~90%")

def full_game2(instalado_ya: bool, fallback_loader: bool):
    prof = profiles.create_profile("L", "1.20.1", loader="fabric")
    api = bridge.Api.__new__(bridge.Api)
    ev = []; done = threading.Event()
    def emit(name, payload):
        ev.append((name, payload))
        if name == "launch_done": done.set()
    api._emit = emit; api._running = {}; api._mc_dir = Path(tempfile.mkdtemp())
    api._account = types.SimpleNamespace(username="u", uuid="1", access_token="t", is_offline=False)
    api._access_status = lambda: "allowed"; api._mark_running = lambda *a, **k: None; api._stream_process_output = lambda *a, **k: None
    fake_core = types.SimpleNamespace(
        is_version_installed=lambda *a, **k: instalado_ya,
        get_latest_fabric_loader_version=lambda: ("0.15.0", fallback_loader),
        install_fabric=lambda version, instance_dir, loader_version, progress: (
            [progress(f"Download lib-{i}.jar", i, 20) for i in range(20)], "fabric-loader-0.15.0-1.20.1")[-1],
        ensure_game_jar=lambda *a, **k: None,
        launch=lambda *a, **k: types.SimpleNamespace(pid=1, stdout=None, poll=lambda: None))
    with mock.patch.object(bridge, "core", fake_core), \
         mock.patch.object(bridge, "discord_presence", mock.MagicMock()), mock.patch.object(bridge, "app_settings", mock.MagicMock(get_ram_mb=lambda: 2048)):
        api.launch_profile(prof.id)
        assert done.wait(10)
    prog = [p for n, p in ev if n == "install_progress"]
    fr = [p["value"] / p["max"] for p in prog]
    assert all(b >= a for a, b in zip(fr, fr[1:])), "la barra retrocedio"
    assert prog[-1]["text"] == "Iniciando Minecraft…" and fr[-1] == 1.0        # SIEMPRE 100% exacto al final
    return fr, [p["text"] for p in prog]

for instalado in (True, False):
    for fb in (True, False):
        fr, tx = full_game2(instalado, fb)
        assert "Lanzando" not in " ".join(tx)                 # el texto antiguo ya no aparece en ningun caso
        if fb and not instalado:   # si ya estaba instalado, no se vuelve a comprobar el loader (no aplica el aviso)
            assert "usando una de respaldo" in " ".join(tx)
print("15 OK en los 4 caminos (instancia ya instalada / nueva, con y sin aviso de respaldo del loader): texto final 'Iniciando Minecraft…' y barra en 100% exacto, nunca retrocede")
