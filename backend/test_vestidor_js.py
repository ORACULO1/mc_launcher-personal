"""Pruebas de la logica JS del Vestidor con un DOM minimo, via Node (si esta disponible).
Desarrollo, no se empaqueta."""
import json, re, shutil, subprocess, sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app_js = (FRONTEND / "app.js").read_text(encoding="utf-8")
block = app_js[app_js.index("/* ---- Vestidor: cambiar skin y capa ---- */"):]
# Las funciones del vestidor llaman a toast()/DEFAULT_STEVE_SKIN/skinViewer/renderTopnavFace/state,
# que viven en otras partes de app.js: se stubean para poder probar el vestidor de forma aislada.
assert "function skinview3dModel" in block and "function renderVestidorCapes" in block

if not shutil.which("node"):
    print("0 (omitidas: no hay Node en este equipo)")
    sys.exit(0)

harness = r"""
const calls = [];
function toast(msg, type) { calls.push(["toast", msg, type]); }
const DEFAULT_STEVE_SKIN = "steve-default";
let skinViewer = null;
function renderTopnavFace() {}
const state = { account: null };

// ---- DOM minimo ----
function mkClassList(el) {
  return {
    add: (...c) => c.forEach(x => el._classes.add(x)),
    remove: (...c) => c.forEach(x => el._classes.delete(x)),
    toggle: (c, on) => { if (on) el._classes.add(c); else el._classes.delete(c); },
    contains: (c) => el._classes.has(c),
  };
}
function mkEl(tag) {
  const el = {
    tag, _classes: new Set(), children: [], attrs: {}, _listeners: {},
    style: {}, title: "",
    get className() { return [...el._classes].join(" "); },
    set className(v) { el._classes = new Set(v.split(" ").filter(Boolean)); },
    set textContent(v) { el._text = v; el.children = []; },
    get textContent() { return el._text || ""; },
    set innerHTML(v) { el.children = []; },
    set backgroundImage(v) {},
    appendChild(child) { el.children.push(child); return child; },
    addEventListener(ev, cb) { el._listeners[ev] = cb; },
    click() { if (el._listeners.click) el._listeners.click(); },
    querySelector(sel) { return findOne(el, sel); },
    querySelectorAll(sel) { return findAll(el, sel); },
    dataset: {},
  };
  el.classList = mkClassList(el);
  return el;
}
function matches(el, sel) {
  if (sel.startsWith(".")) return el._classes && el._classes.has(sel.slice(1));
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  return false;
}
function walk(el, fn) { (el.children || []).forEach(c => { fn(c); walk(c, fn); }); }
function findAll(root, sel) { const out = []; walk(root, (c) => { if (matches(c, sel)) out.push(c); }); return out; }
function findOne(root, sel) { return findAll(root, sel)[0] || null; }

function mkCanvasEl() {
  const el = mkEl("canvas");
  el.getContext = () => ({ imageSmoothingEnabled: true, clearRect() {}, drawImage() { el._drawn = true; } });
  return el;
}
global.Image = function () { this.onload = null; };
Object.defineProperty(global.Image.prototype, "src", { set() {} });

const ids = {};
global.document = {
  createElement: (t) => (t === "canvas" ? mkCanvasEl() : mkEl(t)),
  getElementById: (id) => ids[id],
  querySelector: (sel) => findOne(global.document._root, sel),
  querySelectorAll: (sel) => findAll(global.document._root, sel),
  addEventListener: () => {},
};
const root = mkEl("root"); global.document._root = root;
function register(id, el) { el.id = id; ids[id] = el; root.appendChild(el); return el; }

register("vestidorHint", mkEl("div"));
register("vestidorCapes", mkEl("div"));
register("btnVestidorConfirm", mkEl("button"));
const variantBtns = [mkEl("button"), mkEl("button")];
variantBtns[0].dataset.variant = "classic"; variantBtns[0].classList.add("vestidor-variant-btn", "active");
variantBtns[1].dataset.variant = "slim"; variantBtns[1].classList.add("vestidor-variant-btn");
variantBtns.forEach(b => root.appendChild(b));
register("vestidorOfflineNotice", mkEl("div"));
register("vestidorEditor", mkEl("div"));
register("btnPickSkin", mkEl("button"));
register("btnVestidorCancel", mkEl("button"));

let apiCalls = [];
global.window = {
  skinview3d: null,
  pywebview: { api: {
    set_active_cape: (id) => { apiCalls.push(["set_active_cape", id]); return Promise.resolve({ ok: true }); },
    get_wardrobe: () => { apiCalls.push(["get_wardrobe"]); return Promise.resolve({ ok: true, offline: false, skinUrl: null, variant: "classic", capes: [] }); },
  } },
  addEventListener: () => {},
};
""" + block + r"""

const out = {};

// 1) mapeo de modelo
out.model = [skinview3dModel("slim"), skinview3dModel("classic"), skinview3dModel(undefined)];

// 2) sin capas: "Ninguna" queda activa y se muestra el mensaje de estado vacio
renderVestidorCapes([]);
const capesBox = document.getElementById("vestidorCapes");
out.sinCapas = {
  n: capesBox.children.length,
  ningunaActiva: capesBox.children[0].classList.contains("active"),
  mensaje: capesBox.children[1] ? capesBox.children[1].textContent : null,
};

// 3) con una capa activa
renderVestidorCapes([{ id: "abc", url: "https://x/cape.png", alias: "Capa Prueba", active: true }]);
const capesBox2 = document.getElementById("vestidorCapes");
out.conCapa = {
  n: capesBox2.children.length,
  ningunaActiva: capesBox2.children[0].classList.contains("active"),
  capaActiva: capesBox2.children[1].classList.contains("active"),
  titulo: capesBox2.children[1].title,
  esCanvas: capesBox2.children[1].children[0] && capesBox2.children[1].children[0].tag === "canvas",
  tamanoCanvas: capesBox2.children[1].children[0] && [capesBox2.children[1].children[0].width, capesBox2.children[1].children[0].height],
};

// 4) click en "Ninguna" llama a set_active_cape(null)
capesBox2.children[0].click();
out.clickNinguna = apiCalls;

// 5) alternar el toggle Wide/Slim
setVestidorVariant("slim", false);
out.toggle = { wide: variantBtns[0].classList.contains("active"), slim: variantBtns[1].classList.contains("active") };

console.log(JSON.stringify(out));
"""
res = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
assert res.returncode == 0, res.stderr
out = json.loads(res.stdout)

assert out["model"] == ["slim", "default", "default"]
print("1 OK skinview3dModel: 'slim' -> slim, 'classic'/vacio -> default (coincide con lo que pide skinview3d.bundle.js)")

assert out["sinCapas"] == {"n": 2, "ningunaActiva": True, "mensaje": "Tu cuenta todavía no tiene ninguna capa oficial de Minecraft."}
print("2 OK sin capas: 'Ninguna' queda marcada y se explica que la cuenta no tiene capas")

assert out["conCapa"]["n"] == 2 and out["conCapa"]["ningunaActiva"] is False and out["conCapa"]["capaActiva"] is True
assert out["conCapa"]["titulo"] == "Capa Prueba" and out["conCapa"]["esCanvas"] is True
assert out["conCapa"]["tamanoCanvas"] == [10, 16]   # el panel visible de la capa (1,1)-(11,17): 10x16
print("3 OK con una capa activa: se resalta esa capa (no 'Ninguna'), con su alias y un canvas de 10x16 (el panel recortado, no toda la hoja)")

assert out["clickNinguna"] == [["set_active_cape", None]]
print("4 OK pulsar 'Ninguna' llama a set_active_cape(None) (quita la capa)")

assert out["toggle"] == {"wide": False, "slim": True}
print("5 OK el interruptor Wide/Slim resalta el que corresponde")
