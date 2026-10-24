// Puente entre la interfaz y Tauri.
//  * window.pywebview.api.<método>(...)  ->  comando Rust "rpc" -> motor de Python (así app.js no cambia).
//  * Eventos del motor ("launcher-event")  ->  window.onLauncherEvent(evento, datos).
//  * Actualización automática al abrir: busca, descarga, instala y reinicia sin pedir nada.
(function () {
  const T = window.__TAURI__;
  if (!T) return;
  const invoke = T.core.invoke;

  window.pywebview = {
    api: new Proxy({}, {
      get: (_t, method) => {
        if (typeof method !== "string" || method === "then") return undefined;
        return (...args) => invoke("rpc", { method, args });
      },
    }),
  };

  T.event.listen("launcher-event", (e) => {
    const m = e.payload || {};
    if (typeof window.onLauncherEvent === "function") window.onLauncherEvent(m.event, m.payload);
  });

  // Arrastrar la ventana desde la barra de título (los botones quedan fuera).
  function enableDrag() {
    const bar = document.querySelector(".titlebar");
    if (!bar) return;
    bar.setAttribute("data-tauri-drag-region", "");
    bar.querySelectorAll(".titlebar-brand, .titlebar-brand *").forEach((n) => n.setAttribute("data-tauri-drag-region", ""));
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", enableDrag);
  else enableDrag();

  // ---- Actualización automática ----
  function buildOverlay() {
    const o = document.createElement("div");
    o.id = "autoUpdateOverlay";
    o.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;" +
      "background:#12161d;color:#f1ece0;font-family:inherit;flex-direction:column;gap:14px;";
    o.innerHTML =
      '<img src="assets/logo.png" style="width:72px;height:72px;border-radius:14px" alt="">' +
      '<div id="autoUpdateTitle" style="font-size:18px;font-weight:700">Actualizando Chechenitza Studio…</div>' +
      '<div style="width:320px;height:8px;border-radius:99px;background:rgba(255,255,255,.1);overflow:hidden">' +
      '<div id="autoUpdateFill" style="height:100%;width:0%;background:#d2c9a5;transition:width .2s"></div></div>' +
      '<div id="autoUpdateText" style="font-size:12px;opacity:.7">Buscando actualización…</div>';
    document.body.appendChild(o);
    return o;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const mb = (n) => (n / 1048576).toFixed(1);

  // Abre la ventanita updater.html y espera a que esté lista. Devuelve la ventana, o null si no se pudo.
  async function openUpdaterWindow() {
    try {
      const W = T.webviewWindow && T.webviewWindow.WebviewWindow;
      if (!W) return null;
      let ready;
      const readyP = new Promise((res) => { ready = res; });
      const unlisten = await T.event.listen("updater-ready", () => ready(true));
      const win = new W("updater", {
        url: "updater.html", title: "Actualizando Chechenitza Studio",
        width: 440, height: 230, center: true, resizable: false, maximizable: false,
        minimizable: false, decorations: false, alwaysOnTop: true, focus: true,
      });
      const failed = new Promise((res) => { win.once("tauri://error", () => res(false)); });
      const ok = await Promise.race([readyP, failed, sleep(6000).then(() => false)]);
      unlisten();
      if (!ok) { try { await win.close(); } catch (_) {} return null; }
      return win;
    } catch (_) { return null; }
  }

  window.__autoUpdate = (async function () {
    if (!T.updater) return;
    const mainWin = (T.window && T.window.getCurrentWindow) ? T.window.getCurrentWindow() : null;
    let win = null, overlay = null, hidden = false;

    // Un único sitio que pinta el estado: la ventanita, o el aviso dentro del launcher si no se pudo abrir.
    const ui = (msg) => {
      if (win) { T.event.emit("updater-ui", msg).catch(() => {}); return; }
      if (!overlay) return;
      const text = document.getElementById("autoUpdateText");
      const fill = document.getElementById("autoUpdateFill");
      if (msg.type === "progress") { fill.style.width = msg.percent + "%"; text.textContent = "Descargando… " + Math.floor(msg.percent) + "%"; }
      if (msg.type === "installing") { fill.style.width = "100%"; text.textContent = "Instalando…"; }
    };

    try {
      const update = await T.updater.check();
      if (!update) return;

      win = await openUpdaterWindow();
      if (win) {
        if (mainWin) { try { await mainWin.hide(); hidden = true; } catch (_) {} }
      } else {
        overlay = buildOverlay();
      }
      ui({ type: "versions", from: update.currentVersion, to: update.version });

      let total = 0, got = 0;
      await update.download((ev) => {
        if (ev.event === "Started") total = (ev.data && ev.data.contentLength) || 0;
        if (ev.event === "Progress") {
          got += (ev.data && ev.data.chunkLength) || 0;
          const percent = total ? Math.min(100, (got / total) * 100) : 0;
          ui({ type: "progress", percent, detail: total ? `${mb(got)} / ${mb(total)} MB` : "" });
        }
        if (ev.event === "Finished") ui({ type: "progress", percent: 100, detail: "" });
      });
      ui({ type: "installing" });
      await sleep(400);
      try { await invoke("rpc", { method: "stop_backend", args: [] }); } catch (_) {}
      await update.install();   // en Windows cierra la app, instala y la vuelve a abrir
      await T.process.relaunch();
    } catch (err) {
      // Sin internet o fallo: el launcher abre normal.
      console.warn("Actualización automática:", err);
      if (win) { ui({ type: "error" }); await sleep(1800); ui({ type: "close" }); try { await win.close(); } catch (_) {} }
      if (overlay) overlay.remove();
      if (hidden && mainWin) { try { await mainWin.show(); } catch (_) {} }
    }
  })();
})();
