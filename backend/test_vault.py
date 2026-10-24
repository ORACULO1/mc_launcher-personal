import os, sys, hashlib, shutil, tempfile, json
from pathlib import Path
sys.path.insert(0, ".")
import vault, securestore, keystore, paths
vault.RANDOMIZE_MOD_NAMES = False   # las pruebas 1-17 comparan por nombre; la 18 prueba los nombres aleatorios
# Las pruebas 1-24 verifican TODAS las protecciones, así que se activan aquí a propósito. El comportamiento por
# defecto (compatible con mods) se prueba al final (pruebas 25-29).
vault.PURGE_MODS_AFTER_LOAD = True
vault.DENY_ROOT_LISTING = True
vault.LIST_DENY_FOLDERS = vault._GAME_FOLDERS

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tree(base):
    return {p.relative_to(base).as_posix(): sha(p) for p in sorted(Path(base).rglob("*")) if p.is_file()}

root = Path(tempfile.mkdtemp())
inst = root / "inst"; (inst/"mods").mkdir(parents=True); (inst/"config").mkdir()
(inst/"mods"/"secreto-mod.jar").write_bytes(os.urandom(5_300_000))
(inst/"mods"/"exacto.jar").write_bytes(os.urandom(vault.CHUNK*2))      # múltiplo exacto del bloque
(inst/"mods"/"vacio.jar").write_bytes(b"")
(inst/"mods"/"sub").mkdir(); (inst/"mods"/"sub"/"x.jar").write_bytes(b"MARCADOR-SECRETO-MOD-0123456789")
(inst/"config"/"a.toml").write_text("MARCADOR-CONFIG-ABCDEFGHIJ=1")
(inst/"saves").mkdir(); (inst/"saves"/"mundo.dat").write_bytes(b"mundo")   # NO debe tocarse
(inst/"versions").mkdir(); (inst/"versions"/"v.jar").write_bytes(b"juego")
orig = {k:v for k,v in tree(inst).items() if k.split("/")[0] in vault.PROTECTED}
ID = "inst-oficial-1"

# 1) seal: nada legible en disco
vault.seal(inst, ID)
assert not (inst/"mods").exists() and not (inst/"config").exists()
blob_bytes = b"".join(p.read_bytes() for p in (inst/".vault").iterdir())
assert b"MARCADOR-SECRETO-MOD" not in blob_bytes and b"MARCADOR-CONFIG" not in blob_bytes
names = [p.name for p in (inst/".vault").iterdir()]
assert not any("secreto" in n or "jar" in n for n in names), names
assert (inst/"saves"/"mundo.dat").read_bytes()==b"mundo" and (inst/"versions"/"v.jar").exists()
print("1 OK  seal; nombres en disco:", names[:3], "...")

# 2) unseal reproduce idéntico
vault.unseal(inst, ID)
assert {k:v for k,v in tree(inst).items() if k.split("/")[0] in vault.PROTECTED} == orig
print("2 OK  unseal idéntico (incl. vacío y múltiplo de bloque)")

# 3) el juego cambia config, se cuelan mods ajenos; al cerrar se recifra
(inst/"config"/"a.toml").write_text("x=2"); (inst/"mods"/"intruso.jar").write_bytes(b"malo")
vault.seal(inst, ID)
assert not (inst/"mods").exists()
vault.unseal(inst, ID)
assert (inst/"config"/"a.toml").read_text()=="x=2"
assert not (inst/"mods"/"intruso.jar").exists()
print("3 OK  config persistente, mod intruso eliminado")

# 4) crash: queda en claro; unseal/seal siguiente asienta sin perder nada
vault.seal(inst, ID); vault.unseal(inst, ID)
(inst/"config"/"a.toml").write_text("x=3")
vault.unseal(inst, ID)            # simula relanzar tras crash
assert (inst/"config"/"a.toml").read_text()=="x=3"
vault.seal(inst, ID)
print("4 OK  recuperación tras cierre inesperado")

# 5) manipulación de un bloque
blob = next(p for p in (inst/".vault").glob("*.g4v") if p.stem!="manifest")
data = bytearray(blob.read_bytes()); data[20]^=1; blob.write_bytes(bytes(data))
try: vault.unseal(inst, ID); raise SystemExit("FALLO: aceptó bloque alterado")
except vault.VaultError as e: print("5 OK  alteración detectada:", e)
assert not (inst/"mods").exists()   # no deja descifrado parcial

# 6) truncado en límite de bloque
inst2 = root/"inst2"; (inst2/"mods").mkdir(parents=True); (inst2/"mods"/"g.jar").write_bytes(os.urandom(vault.CHUNK*3))
vault.seal(inst2, "i2")
blob = next(p for p in (inst2/".vault").glob("*.g4v") if p.stem!="manifest")
raw = blob.read_bytes(); blob.write_bytes(raw[:12 + 2*(vault.CHUNK+vault.TAG)])
try: vault.unseal(inst2, "i2"); raise SystemExit("FALLO: aceptó truncado")
except vault.VaultError: print("6 OK  truncado detectado")
except Exception as e: print("6 OK  truncado detectado (", type(e).__name__, ")")

# 7) copiar vault a otra instancia (mismo id de bloque) -> falla
inst3 = root/"inst3"; (inst3/"mods").mkdir(parents=True); (inst3/"mods"/"m.jar").write_bytes(b"z"*100)
vault.seal(inst3, "A")
shutil.copytree(inst3/".vault", root/"copia"/".vault")
try: vault.unseal(root/"copia", "B"); raise SystemExit("FALLO: vault usable con otro id")
except Exception as e: print("7 OK  vault copiado a otra instancia/id inservible:", type(e).__name__)

# 8) manifiesto con ruta maliciosa
import io
key = vault._key(inst3, "A")
raw = io.BytesIO(json.dumps({"v":1,"files":{"../../evil.dll":"00"}}).encode())
vault._atomic_write(inst3/".vault"/"manifest.g4v", lambda fh: vault._encrypt_stream(key, raw, fh, vault._aad("A","manifest")))
try: vault.unseal(inst3, "A"); raise SystemExit("FALLO: path traversal")
except vault.VaultError as e: print("8 OK  path traversal bloqueado:", e)

# 9) securestore: AES-GCM, migración desde formato antiguo y plano
f = root/"s.json"
securestore.write(f, {"a":1}); assert f.read_bytes().startswith(b"G4S-A2") and securestore.read(f)=={"a":1}
old = securestore._MAGIC_GEN + securestore._gen_encrypt(json.dumps({"b":2}).encode()); f.write_bytes(old)
assert securestore.read(f)=={"b":2}
f.write_text('{"c":3}'); assert securestore.read(f)=={"c":3}
print("9 OK  securestore AES-GCM + lectura de formatos antiguos")
print("clave maestra permisos:", oct(os.stat(paths.SYSTEM_DIR/"store.key").st_mode & 0o777))

# 10) retirada de mods con el juego abierto (purge_runtime)
inst4 = root/"inst4"; (inst4/"mods").mkdir(parents=True); (inst4/"config").mkdir()
(inst4/"mods"/"a.jar").write_bytes(os.urandom(300_000)); (inst4/"mods"/"b.jar").write_bytes(os.urandom(1000))
(inst4/"config"/"c.toml").write_text("v=1")
o4 = tree(inst4)
assert vault.purge_runtime(inst4, "I4") == (-1, False) and (inst4/"mods"/"a.jar").exists()   # sin vault: NO borra
vault.seal(inst4, "I4"); vault.unseal(inst4, "I4")
assert vault.purge_runtime(inst4, "I4") == (0, False)
assert not (inst4/"mods").exists() and (inst4/"config"/"c.toml").exists()           # config sigue (el juego la usa)
(inst4/"config"/"c.toml").write_text("v=2")                                         # el juego guarda ajustes
vault.seal(inst4, "I4")                                                             # cierre: recifra config
assert not (inst4/"config").exists()
vault.unseal(inst4, "I4")
assert tree(inst4)["mods/a.jar"] == o4["mods/a.jar"] and tree(inst4)["mods/b.jar"] == o4["mods/b.jar"]
assert (inst4/"config"/"c.toml").read_text() == "v=2"
print("10 OK purge tras carga: mods fuera del disco, config persiste, todo se restaura")

# 11) un jar bloqueado por el juego (Windows simulado): se bloquea su lectura y se limpia al cerrar
from unittest import mock
calls = []; hidden = []
def fake_icacls(*args):
    calls.append(args); return True
real_unlink = Path.unlink
def locked(self, *a, **k):
    if self.name == "a.jar": raise PermissionError("en uso por Java")
    return real_unlink(self, *a, **k)
(inst4/"mods"/"sub").mkdir(exist_ok=True); (inst4/"mods"/"sub"/"n.jar").write_bytes(b"n")
with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "_icacls", fake_icacls), \
     mock.patch.object(vault, "LOCK_JAR_READS", True), \
     mock.patch.object(vault, "_set_hidden", lambda p: hidden.append(p)):
    with mock.patch.object(Path, "unlink", locked):          # juego abierto: a.jar en uso
        left, ok = vault.purge_runtime(inst4, "I4")
    assert left == 1 and (inst4/"mods"/"a.jar").exists() and not (inst4/"mods"/"b.jar").exists()
    assert (inst4/".g4readlock").exists()
    deny = [c for c in calls if "/deny" in c]
    assert deny[-1] == (str(inst4), "/deny", "*S-1-1-0:(RD)", "/C")           # la instancia entera, la última
    assert deny[-2] == (str(inst4/"mods"), "/deny", "*S-1-1-0:(RD)", "/C")     # y antes, la carpeta mods: sin listado
    files_deny = deny[:-2]
    assert files_deny and all(c[1:3] == ("/deny", "*S-1-1-0:(R)") and c[0].endswith("*") for c in files_deny), calls
    assert files_deny[-1][0] == str(inst4/"mods"/"*")                          # archivos: de dentro hacia fuera
    assert inst4/"mods" in hidden                                          # carpeta oculta (oculta + sistema)
    calls.clear()
    vault.seal(inst4, "I4")                       # juego cerrado: ya no hay jar en uso
    unlock = [c for c in calls if "/remove:d" in c]
    assert unlock[0][0] == str(inst4)                                       # 1º la instancia (para poder listarla)
    assert any(c[0] == str(inst4/".vault") for c in unlock)                 # luego .vault (se va a reescribir)
    assert any(c[0] == str(inst4/"mods") for c in unlock)                   # raíz de mods antes de listar
    assert not (inst4/".g4readlock").exists() and not (inst4/"mods").exists()
vault.unseal(inst4, "I4"); assert tree(inst4)["mods/a.jar"] == o4["mods/a.jar"]
print("11 OK jar en uso: lectura bloqueada, se desbloquea y limpia al cerrar sin perder nada")

# 12) _icacls en Linux no hace nada y nunca falla
assert vault._icacls("x") is False
print("12 OK sin efectos fuera de Windows")

# 13) detección de carga del juego (gamewatch) + retirada de mods
import threading, gamewatch

class FakeProc:
    def __init__(self, die_at=None, clock=None): self.pid, self.die_at, self.clock = 4242, die_at, clock
    def poll(self): return 0 if (self.die_at is not None and self.clock() >= self.die_at) else None

def run_watch(*, window_at=None, log_at=None, die_at=None):
    t = [0.0]; clock = lambda: t[0]
    ev = threading.Event(); got = []
    def sleep(_):
        t[0] += 1.0
        if log_at is not None and t[0] >= log_at: ev.set()
    gamewatch.watch_until_loaded(FakeProc(die_at, clock), ev, got.append,
                                 window_check=lambda pid: window_at is not None and t[0] >= window_at,
                                 sleep=sleep, clock=clock)
    return got, t[0]

assert run_watch(window_at=3)[0] == ["ventana"] and run_watch(window_at=3)[1] >= gamewatch.MIN_SECONDS   # nunca antes del mínimo
assert run_watch(log_at=20)[0] == ["log"]
got, t = run_watch(); assert got == ["tiempo"] and t >= gamewatch.FALLBACK_SECONDS                      # sin log ni ventana
assert run_watch(die_at=5)[0] == []                                                                     # se cierra antes: no actúa
assert gamewatch.line_signals_loaded("[12:00:01] [Render thread/INFO]: Sound engine started")
assert gamewatch.line_signals_loaded(b"OpenAL initialized.") and not gamewatch.line_signals_loaded("Loading mods")
assert gamewatch.pid_has_minecraft_window(1) is False                                                  # Linux: sin efecto
print("13 OK detección de carga: ventana, log y tiempo; no actúa si el juego se cierra")

inst5 = root/"inst5"; (inst5/"mods").mkdir(parents=True); (inst5/"mods"/"m.jar").write_bytes(os.urandom(5000))
vault.seal(inst5, "I5"); vault.unseal(inst5, "I5")
got, _ = run_watch(window_at=10)
res = vault.purge_runtime(inst5, "I5") if got else None
assert res == (0, False) and not (inst5/"mods").exists()
print("14 OK flujo completo: carga detectada -> mods fuera del disco")

# 15) al descifrar, mods/config/vault quedan ocultos (Windows simulado)
hid = []
inst6 = root/"inst6"; (inst6/"mods").mkdir(parents=True); (inst6/"config").mkdir()
(inst6/"mods"/"z.jar").write_bytes(b"z"); (inst6/"config"/"c.toml").write_text("1")
vault.seal(inst6, "I6")
with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "_set_hidden", lambda p: hid.append(p.name)):
    vault.unseal(inst6, "I6")
assert {"mods", "config", ".vault"} <= set(hid), hid
print("15 OK carpetas protegidas y .vault ocultas al descifrar")

# 16) la instancia no se puede borrar a mano: .vault protegido, solo el launcher lo libera
from unittest import mock
calls2 = []
def rec(*a): calls2.append(a); return True
inst7 = root/"inst7"; (inst7/"mods").mkdir(parents=True); (inst7/"mods"/"q.jar").write_bytes(b"q")
with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "_icacls", rec), \
     mock.patch.object(vault, "_set_hidden", lambda p: None):
    vault.seal(inst7, "I7")
    assert (inst7/".vault"/".keep").exists()                       # .vault nunca queda vacía
    assert calls2[-2] == (str(inst7/".vault"), "/deny", "*S-1-1-0:(OI)(CI)(DE,DC)", "/C"), calls2[-2]   # carpeta + herencia
    assert calls2[-1] == (str(inst7/".vault"/"*"), "/deny", "*S-1-1-0:(DE)", "/C"), calls2[-1]           # y cada archivo explícito
    calls2.clear()
    vault.seal(inst7, "I7")                                         # 2º cierre: .vault ya existe y está protegida
    assert calls2[0] == (str(inst7/".vault"), "/remove:d", "*S-1-1-0", "/T", "/C")   # liberada (incluye hijos) antes de escribir
    assert calls2[-1][:3] == (str(inst7/".vault"/"*"), "/deny", "*S-1-1-0:(DE)")   # y protegida otra vez
    calls2.clear()
    vault.unseal(inst7, "I7")                                       # solo lee: no toca la protección
    assert not any(c[0] == str(inst7/".vault") for c in calls2)
    calls2.clear()
    vault.release_instance(inst7)                                   # desinstalar desde el launcher
    assert calls2[0][:2] == (str(inst7/".vault"), "/remove:d")
    calls2.clear()
    vault.destroy(inst7); assert not (inst7/".vault").exists() and calls2[0][:2] == (str(inst7/".vault"), "/remove:d")
vault._IS_WIN = False
assert vault.protect_instance(inst7) is False
print("16 OK protección contra borrado manual: se activa al cifrar, el launcher la libera para desinstalar")

# 17) modo por defecto: NO se deniega la lectura de los .jar (rompe mods como JourneyMap); solo listado + oculto
inst8 = root/"inst8"; (inst8/"mods").mkdir(parents=True); (inst8/"mods"/"journeymap.jar").write_bytes(b"jm"*50)
vault.seal(inst8, "I8"); vault.unseal(inst8, "I8")
c3, h3 = [], []
with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "_icacls", lambda *a: c3.append(a) or True), \
     mock.patch.object(vault, "_set_hidden", lambda p: h3.append(p)):
    with mock.patch.object(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(PermissionError("en uso")) if self.suffix == ".jar" else real_unlink(self, *a, **k)):
        left, ok = vault.purge_runtime(inst8, "I8")
assert left == 1
deny3 = [c for c in c3 if "/deny" in c]
assert deny3 == [(str(inst8/"mods"), "/deny", "*S-1-1-0:(RD)", "/C"),
                 (str(inst8), "/deny", "*S-1-1-0:(RD)", "/C")], deny3            # sin denegar lectura de archivos
print("17 OK por defecto no se bloquea la lectura de los .jar (el juego puede reabrirlos)")
vault.seal(inst8, "I8")

# 18) nombres aleatorios en mods/, contenido idéntico, y config con su nombre real
inst9 = root/"inst9"; (inst9/"mods").mkdir(parents=True); (inst9/"config").mkdir()
(inst9/"mods"/"sodium-fabric-1.0.jar").write_bytes(b"s"*200); (inst9/"mods"/"lithium.jar").write_bytes(b"l"*300)
(inst9/"config"/"sodium.json").write_text("{}")
with mock.patch.object(vault, "RANDOMIZE_MOD_NAMES", True):
  vault.seal(inst9, "I9"); vault.unseal(inst9, "I9")
names = sorted(p.name for p in (inst9/"mods").iterdir())
assert len(names) == 2 and all(n.endswith(".jar") and len(n) == 36 for n in names) and not any("sodium" in n or "lithium" in n for n in names), names
assert sorted(p.read_bytes() for p in (inst9/"mods").iterdir()) == sorted([b"s"*200, b"l"*300])
assert (inst9/"config"/"sodium.json").exists()
with mock.patch.object(vault, "RANDOMIZE_MOD_NAMES", True):
  vault.seal(inst9, "I9"); vault.unseal(inst9, "I9")                    # ciclo repetido: sigue íntegro
assert sorted(p.read_bytes() for p in (inst9/"mods").iterdir()) == sorted([b"s"*200, b"l"*300])
print("18 OK mods con nombre aleatorio, contenido íntegro tras varios ciclos")

# 19) comprobación real de la protección (sin borrar nada) y su informe
assert vault.delete_protection_status(inst7) == "desconocida"          # Linux: no se puede saber
with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "_icacls", lambda *a: True), \
     mock.patch.object(vault, "_set_hidden", lambda p: None):
    (inst7).mkdir(exist_ok=True); (inst7/".vault").mkdir(exist_ok=True)
    with mock.patch.object(vault, "_can_delete", lambda p: False):      # Windows deniega abrir con DELETE
        assert vault.protect_instance(inst7) is True
        assert vault.delete_protection_status(inst7) == "activa"
    with mock.patch.object(vault, "_can_delete", lambda p: True):       # si aún se puede borrar: se detecta
        assert vault.protect_instance(inst7) is False and vault.delete_protection_status(inst7) == "NO EFECTIVA"
print("19 OK la protección se verifica de verdad y se informa si NO es efectiva")

# 20) todas las carpetas del modpack se cifran; las de Minecraft/jugador no
inst10 = root/"inst10"
for d in ("mods","config","resourcepacks","shaderpacks","scripts","fancymenu_data","saves","assets","libraries","versions","logs","journeymap","runtime"):
    (inst10/d).mkdir(parents=True)
(inst10/"mods"/"a.jar").write_bytes(os.urandom(2000))
(inst10/"resourcepacks"/"pack.zip").write_bytes(os.urandom(700_000))
(inst10/"shaderpacks"/"BSL.zip").write_bytes(b"SHADER-SECRETO-" + os.urandom(900_000))
(inst10/"shaderpacks"/"BSL.zip.txt").write_text("sombras=1")
(inst10/"scripts"/"x.zs").write_text("SCRIPT-PRIVADO-DEL-PACK")
(inst10/"fancymenu_data"/"menu.txt").write_text("MENU-PRIVADO-DEL-PACK")
for d in ("saves","assets","libraries","versions","logs","journeymap","runtime"):
    (inst10/d/"f.bin").write_bytes(b"publico-" + d.encode())
(inst10/".modpack_info.json").write_text(json.dumps({"packFolders": ["mods","config","resourcepacks","shaderpacks","scripts","fancymenu_data","saves","assets"]}))
assert vault.detect_folders(inst10) == ["config","defaultconfigs","fancymenu_data","kubejs","mods","resourcepacks","scripts","shaderpacks"]  # saves/assets excluidos aunque el pack los traiga
before = {k:v for k,v in tree(inst10).items() if k.split("/")[0] in ("resourcepacks","shaderpacks","scripts","fancymenu_data","mods")}
vault.seal(inst10, "I10")
for d in ("mods","config","resourcepacks","shaderpacks","scripts","fancymenu_data"):
    assert not (inst10/d).exists(), d
for d in ("saves","assets","libraries","versions","logs","journeymap","runtime"):
    assert (inst10/d/"f.bin").exists(), d                                  # nada de Minecraft/jugador se toca
blobs = b"".join(p.read_bytes() for p in (inst10/".vault").iterdir())
assert b"SHADER-SECRETO" not in blobs and b"SCRIPT-PRIVADO" not in blobs and b"MENU-PRIVADO" not in blobs
vault.unseal(inst10, "I10")
after = {k:v for k,v in tree(inst10).items() if k.split("/")[0] in ("resourcepacks","shaderpacks","scripts","fancymenu_data")}
assert after == {k:v for k,v in before.items() if k.split("/")[0] != "mods"}
assert (inst10/"mods"/"a.jar").exists()
print("20 OK cifra mods/config/resourcepacks/shaderpacks/scripts/…; no toca saves/assets/libraries/versions/logs/…")

# 21) recifrado incremental: solo lo que el juego modificó
blob_of = lambda rel: next(p for p in (inst10/".vault").glob("*.g4v") if p.stem != "manifest")  # noqa
import time as _t
snap = {p.name: p.stat().st_mtime_ns for p in (inst10/".vault").glob("*.g4v")}
_t.sleep(0.05)
(inst10/"shaderpacks"/"BSL.zip.txt").write_text("sombras=2")             # el juego cambia un ajuste
vault.seal(inst10, "I10")
snap2 = {p.name: p.stat().st_mtime_ns for p in (inst10/".vault").glob("*.g4v")}
changed = [n for n in snap2 if n in snap and snap2[n] != snap[n] and n != "manifest.g4v"]
assert len(changed) == 1, changed                                          # solo el .txt se recifró, no los 900 KB del shader
vault.unseal(inst10, "I10")
assert (inst10/"shaderpacks"/"BSL.zip.txt").read_text() == "sombras=2"
assert after["shaderpacks/BSL.zip"] == tree(inst10)["shaderpacks/BSL.zip"]
print("21 OK recifrado incremental: solo se vuelve a cifrar lo que el juego modificó")

# 22) migración: instancia ya cifrada con el formato antiguo (solo mods/config) + carpetas en claro
inst11 = root/"inst11"; (inst11/"mods").mkdir(parents=True); (inst11/"config").mkdir()
(inst11/"mods"/"m.jar").write_bytes(b"m"*100); (inst11/"config"/"c.toml").write_text("1")
vault.seal(inst11, "I11")
key = vault._key(inst11, "I11")
files, _ = vault._load_manifest(inst11, key, "I11")
raw = io.BytesIO(json.dumps({"v": 1, "files": files}).encode())            # manifiesto v1 (sin carpetas)
vault._atomic_write(inst11/".vault"/"manifest.g4v", lambda fh: vault._encrypt_stream(key, raw, fh, vault._aad("I11", "manifest")))
(inst11/"shaderpacks").mkdir(); (inst11/"shaderpacks"/"s.zip").write_bytes(b"SHADER-VIEJO-EN-CLARO"*50)
(inst11/"saves").mkdir(); (inst11/"saves"/"w.dat").write_bytes(b"mundo")
vault.seal(inst11, "I11")                                                   # el launcher al abrir
assert not (inst11/"shaderpacks").exists() and (inst11/"saves"/"w.dat").exists()
vault.unseal(inst11, "I11")
assert (inst11/"shaderpacks"/"s.zip").read_bytes() == b"SHADER-VIEJO-EN-CLARO"*50 and (inst11/"config"/"c.toml").read_text() == "1"
assert len(list((inst11/"mods").iterdir())) == 1
print("22 OK migración: instancias antiguas adoptan las carpetas nuevas sin perder nada")

# 23) path traversal / carpetas excluidas en el manifiesto siguen bloqueadas
for evil in ("../x", "saves/w.dat", ".vault/salt.bin", "assets/a"):
    key = vault._key(inst11, "I11")
    raw = io.BytesIO(json.dumps({"v": 2, "folders": ["mods"], "files": {evil: "00"}}).encode())
    vault._atomic_write(inst11/".vault"/"manifest.g4v", lambda fh: vault._encrypt_stream(key, raw, fh, vault._aad("I11", "manifest")))
    try: vault.unseal(inst11, "I11"); raise SystemExit("FALLO: aceptó " + evil)
    except vault.VaultError: pass
print("23 OK el manifiesto no puede apuntar a carpetas de Minecraft, al vault ni fuera de la instancia")

# 24) la instancia entera: todo oculto, sin listado de la raíz ni de las carpetas que el juego no lista
inst12 = root/"inst12"
for d in ("mods","resourcepacks","saves","libraries","assets","versions","runtime","logs","screenshots","journeymap","carpeta_nueva"):
    (inst12/d).mkdir(parents=True)
(inst12/"mods"/"m.jar").write_bytes(b"m"*500); (inst12/"resourcepacks"/"p.zip").write_bytes(b"p"*500)
(inst12/".modpack_info.json").write_text(json.dumps({"packFolders": ["mods","resourcepacks"]}))
vault.seal(inst12, "I12"); vault.unseal(inst12, "I12")
c4, h4 = [], []
with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "_icacls", lambda *a: c4.append(a) or True), \
     mock.patch.object(vault, "_set_hidden", lambda p: h4.append(p.name)):
    vault.purge_runtime(inst12, "I12")
    d4 = [c for c in c4 if "/deny" in c]
    paths4 = [c[0] for c in d4]
    assert paths4[-1] == str(inst12)                                            # raíz: la última
    for n in ("libraries", "assets", "versions", "runtime"):
        assert str(inst12/n) in paths4, n                                       # el juego no las lista
    for n in ("resourcepacks", "saves", "logs", "screenshots", "journeymap", "carpeta_nueva"):
        assert str(inst12/n) not in paths4, n                                   # el juego SÍ las lista: no se bloquean
    assert {"saves","resourcepacks","libraries","logs","screenshots","journeymap","carpeta_nueva"} <= set(h4), h4   # todas ocultas
    assert (inst12/".g4readlock").exists()
    # cierre inesperado: el siguiente arranque debe poder listar y limpiar
    c4.clear()
    vault.unseal(inst12, "I12")
    rem = [c for c in c4 if "/remove:d" in c]
    assert rem and rem[0][0] == str(inst12)                                      # primero se libera la raíz
    assert not (inst12/".g4readlock").exists()
print("24 OK instancia oculta y sin listado de la raíz; libraries/assets/versions/runtime sin listado; las que el juego lista, no")


# 25) por defecto la configuración es la compatible con mods
vault.apply_settings(vault.load_settings(Path(tempfile.mkdtemp()) / "inexistente.json", create=False))
assert (vault.PURGE_MODS_AFTER_LOAD, vault.DENY_ROOT_LISTING, vault.LIST_DENY_FOLDERS) == (False, False, ())
assert vault.DENY_MODS_LISTING and vault.RANDOMIZE_MOD_NAMES and vault.HIDE_FOLDERS
print("25 OK por defecto: no se borran los .jar, no se bloquea el listado de la instancia ni de libraries/versions/runtime/assets")

# 26) con el modo por defecto, los .jar siguen en disco durante la partida (los mods pueden reabrir su archivo) pero la carpeta queda protegida
inst13 = root/"inst13"; (inst13/"mods").mkdir(parents=True); (inst13/"config"/"fancymenu"/"assets").mkdir(parents=True)
(inst13/"mods"/"watermedia.jar").write_bytes(os.urandom(5000)); (inst13/"mods"/"fancymenu.jar").write_bytes(os.urandom(5000))
VIDEO = os.urandom(3_000_000)
(inst13/"config"/"fancymenu"/"assets"/"menu.mp4").write_bytes(VIDEO); (inst13/"config"/"fancymenu"/"layout.txt").write_text("video=assets/menu.mp4")
(inst13/".modpack_info.json").write_text(json.dumps({"packFolders": ["mods", "config"]}))
vault.seal(inst13, "I13"); vault.unseal(inst13, "I13")
c5, h5 = [], []
with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "_icacls", lambda *a: c5.append(a) or True), \
     mock.patch.object(vault, "_set_hidden", lambda p: h5.append(p.name)):
    left, ok = vault.purge_runtime(inst13, "I13")
assert left == 2 and len(list((inst13/"mods").iterdir())) == 2                      # los .jar SIGUEN ahí: un mod puede volver a abrirlo
denies = [c[0] for c in c5 if "/deny" in c]
assert denies == [str(inst13/"mods")]                                                 # solo se bloquea el listado de mods (nada de raíz ni carpetas del juego)
assert "mods" in h5 and "config" in h5
assert (inst13/"config"/"fancymenu"/"assets"/"menu.mp4").read_bytes() == VIDEO        # el vídeo de FancyMenu está intacto y accesible
print("26 OK modo por defecto: los .jar siguen en disco (los mods pueden reabrirlos), la carpeta mods queda oculta y sin listado, y el vídeo de FancyMenu está intacto")
vault.seal(inst13, "I13")
assert not (inst13/"mods").exists() and not (inst13/"config").exists()               # al cerrar: todo cifrado de nuevo
vault.unseal(inst13, "I13")
assert (inst13/"config"/"fancymenu"/"assets"/"menu.mp4").read_bytes() == VIDEO and (inst13/"config"/"fancymenu"/"layout.txt").read_text() == "video=assets/menu.mp4"
print("27 OK al cerrar se recifra todo y el siguiente arranque restaura el vídeo y el diseño de FancyMenu idénticos")

# 28) archivo de ajustes: se crea, se respeta y tolera errores
sf = Path(tempfile.mkdtemp()) / "seguridad.json"
v = vault.load_settings(sf); assert sf.exists() and v == vault._SETTINGS_DEFAULTS and "_ayuda" in json.loads(sf.read_text(encoding="utf-8"))
sf.write_text(json.dumps({"retirar_mods_tras_cargar": True, "bloquear_listado_instancia": True, "nombres_aleatorios_mods": False, "ocultar_carpetas": "si"}), encoding="utf-8")
v2 = vault.load_settings(sf)
assert v2["retirar_mods_tras_cargar"] is True and v2["bloquear_listado_instancia"] is True and v2["nombres_aleatorios_mods"] is False
assert v2["ocultar_carpetas"] is True and v2["bloquear_listado_mods"] is True           # valor inválido o ausente -> el de por defecto
sf.write_text("{ esto no es json", encoding="utf-8"); assert vault.load_settings(sf) == vault._SETTINGS_DEFAULTS
vault.apply_settings(v2); assert vault.PURGE_MODS_AFTER_LOAD and vault.DENY_ROOT_LISTING and not vault.RANDOMIZE_MOD_NAMES
vault.apply_settings(vault._SETTINGS_DEFAULTS)
print("28 OK seguridad.json: se crea solo, se respeta lo que pongas y un archivo mal escrito no rompe nada (usa los valores por defecto)")

# 29) ocultar_carpetas: con true se marca "oculta + sistema"; con false NO se toca ninguna carpeta
fake_ctypes = mock.MagicMock()
for hide in (True, False):
    fake_ctypes.reset_mock()
    with mock.patch.object(vault, "_IS_WIN", True), mock.patch.object(vault, "HIDE_FOLDERS", hide), mock.patch.dict(sys.modules, {"ctypes": fake_ctypes}):
        vault._set_hidden(inst13/"mods"); vault.hide_every_dir(inst13)
    calls = fake_ctypes.windll.kernel32.SetFileAttributesW.call_args_list
    assert bool(calls) == hide, (hide, calls)
    if hide: assert all(c[0][1] == 0x6 for c in calls) and str(inst13/"mods") in [c[0][0] for c in calls]
print("29 OK ocultar_carpetas: activado marca las carpetas (oculta+sistema); desactivado no toca ninguna")
