"""Pruebas del resumen de errores del juego y de la partida completa en los dos modos (desarrollo, no se empaqueta)."""
import json, os, sys, tempfile, threading, time, types
from pathlib import Path
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("minecraft_launcher_lib","minecraft_launcher_lib.utils","minecraft_launcher_lib.install","minecraft_launcher_lib.command",
             "minecraft_launcher_lib.fabric","minecraft_launcher_lib.forge","minecraft_launcher_lib.microsoft_account",
             "minecraft_launcher_lib.types","minecraft_launcher_lib.exceptions","minecraft_launcher_lib.quilt","minecraft_launcher_lib.mod_loader",
             "minecraft_launcher_lib.runtime","pypresence","webview"):
    try: __import__(name)
    except Exception: sys.modules[name] = mock.MagicMock()
import paths, profiles, vault, gamelog, bridge

# ── 1) resumen del log del juego ─────────────────────────────────────────────
LOG = """[12:00:01] [main/INFO]: Loading Minecraft 1.20.1 with Fabric Loader 0.15.0
[12:00:05] [main/INFO]: Loading 142 mods
[12:00:20] [Render thread/INFO]: Sound engine started
[12:00:21] [Render thread/WARN]: [FancyMenu] Loading customization layouts
[12:00:22] [Render thread/ERROR]: [WATERMeDIA] Failed to load VLC: java.nio.file.AccessDeniedException: C:\\Users\\Pepito Pérez\\AppData\\Roaming\\ChechenitzaStudio\\instances\\Oficial\\cache\\watermedia\\vlc
[12:00:22] [Render thread/ERROR]: [FancyMenu] Couldn't play video assets/menu.mp4
java.nio.file.NoSuchFileException: C:/Users/Pepito Pérez/AppData/Roaming/ChechenitzaStudio/instances/Oficial/mods/3f9a.jar
	at java.base/sun.nio.fs.WindowsException.translateToIOException(WindowsException.java:85)
[12:00:23] [Render thread/INFO]: Narrator library loaded
[12:00:23] [Render thread/INFO]: [vlc] using backend OK
"""
d = Path(tempfile.mkdtemp()); (d / "latest.log").write_text(LOG, encoding="utf-8")
out = gamelog.summarize(d / "latest.log")
joined = "\n".join(out)
assert any("Failed to load VLC" in l for l in out) and any("NoSuchFileException" in l for l in out) and any("Couldn't play video" in l for l in out)
assert any("FancyMenu] Loading customization" in l for l in out) and any("using backend" in l for l in out)       # líneas de mods de vídeo aunque no sean error
assert not any("Narrator" in l or "Loading 142 mods" in l for l in out)                                           # ruido normal fuera
assert "Pepito" not in joined and "Pérez" not in joined and "C:\\Users\\<usuario>" in joined and "C:/Users/<usuario>" in joined
print("1 OK el resumen recoge los errores de FancyMenu/WaterMedia/VLC y las rutas con acceso denegado, y oculta el nombre de usuario de Windows")
assert gamelog.summarize(d / "no_existe.log") == []
big = d / "big.log"; big.write_text("INFO normal\n" * 400_000 + "ERROR final importante\n", encoding="utf-8")
t0 = time.time(); r = gamelog.summarize(big); assert r == ["ERROR final importante"] and time.time() - t0 < 2
many = d / "many.log"; many.write_text("\n".join(f"ERROR distinto {i}" for i in range(500)), encoding="utf-8")
assert len(gamelog.summarize(many)) == 30 and all(len(l) <= 300 for l in gamelog.summarize(many))
print("2 OK sin log no falla; con un log enorme solo lee el final y es rápido; nunca anota más de 30 errores")

# ── 2) partida completa a través del bridge en los DOS modos ──────────────────
def full_game(purge: bool):
    prof = profiles.create_profile(f"Oficial-{purge}", "1.20.1", loader="fabric", instance_ref=f"ref-{purge}")
    mc_dir = Path(tempfile.mkdtemp()); inst = profiles.instance_directory(mc_dir, prof)
    for dd in ("mods", "config/fancymenu/assets", "resourcepacks", "logs"): (inst / dd).mkdir(parents=True)
    (inst / "mods" / "fancymenu.jar").write_bytes(os.urandom(4000)); (inst / "mods" / "watermedia.jar").write_bytes(os.urandom(4000))
    video = os.urandom(2_500_000)
    (inst / "config/fancymenu/assets/menu.mp4").write_bytes(video); (inst / "config/fancymenu/layout.txt").write_text("video=assets/menu.mp4")
    (inst / "resourcepacks" / "pack.zip").write_bytes(b"pack" * 100)
    (inst / ".modpack_info.json").write_text(json.dumps({"packFolders": ["mods", "config", "resourcepacks"]}))
    api = bridge.Api.__new__(bridge.Api); api._mc_dir = mc_dir; api._running = {}; api._window = None
    api._emit = lambda *a, **k: None; api._mark_stopped = lambda pid: api._running.pop(pid, None); api._sync_discord_after_stop = lambda *a, **k: None
    api._vault_recover()
    assert not (inst / "mods").exists()
    vault.unseal(inst, prof.instance_ref)
    state = {"alive": True}
    class FakeProc:
        pid = 4343
        def __init__(self):
            def gen():
                yield "[12:00:20] [Render thread/INFO]: Sound engine started\n"
                time.sleep(11)
                (inst / "logs" / "latest.log").write_text("[12:00:22] [Render thread/ERROR]: [FancyMenu] prueba de error en C:\\Users\\Luis\\x\n", encoding="utf-8")
                state["alive"] = False
            self.stdout = gen()
        def poll(self): return None if state["alive"] else 0
        def wait(self):
            while state["alive"]: time.sleep(0.1)
            return 0
    api._running[prof.id] = {"process": None, "pid": 4343}
    with mock.patch.object(vault, "PURGE_MODS_AFTER_LOAD", purge):
        th = threading.Thread(target=api._stream_process_output, args=(FakeProc(), prof.id)); th.start()
        time.sleep(10)
        mods_mid = sorted(p.name for p in (inst / "mods").iterdir()) if (inst / "mods").exists() else []
        video_mid = (inst / "config/fancymenu/assets/menu.mp4").read_bytes() == video
        layout_mid = (inst / "config/fancymenu/layout.txt").read_text()
        th.join(timeout=25)
    assert not (inst / "mods").exists() and not (inst / "config").exists() and not (inst / "resourcepacks").exists()
    vault.unseal(inst, prof.instance_ref)
    assert (inst / "config/fancymenu/assets/menu.mp4").read_bytes() == video
    vault.seal(inst, prof.instance_ref)
    return mods_mid, video_mid, layout_mid

mods_mid, video_ok, layout = full_game(purge=False)
assert len(mods_mid) == 2 and all(n.endswith(".jar") and "fancymenu" not in n and "watermedia" not in n for n in mods_mid)   # siguen ahí (nombres aleatorios)
assert video_ok and layout == "video=assets/menu.mp4"
print("3 OK partida con la configuración por defecto: durante el juego los 2 .jar siguen en disco (con nombre aleatorio), el vídeo y el diseño de FancyMenu intactos; al cerrar todo vuelve a cifrarse")
mods_mid, video_ok, layout = full_game(purge=True)
assert mods_mid == [] and video_ok and layout == "video=assets/menu.mp4"
print("4 OK partida con retirar_mods_tras_cargar=true: los .jar desaparecen del disco tras la carga y el vídeo/diseño siguen accesibles")

log = (paths.SYSTEM_DIR / "access.log").read_text(encoding="utf-8")
assert "relevantes de latest.log" in log and "prueba de error" in log and "Luis" not in log and "C:\\Users\\<usuario>" in log
print("5 OK tras cada partida, access.log recibe las líneas de error del juego (sin el nombre de usuario)")
