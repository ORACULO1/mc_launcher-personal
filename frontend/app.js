const state = {
  profiles: [],
  selectedProfileId: null,
  account: null,
  newProfileColor: "#d0c8a4",
  runningProfileIds: new Set(),
  modpackInstall: null,
  editingProfileId: null,
  instanceLaunch: null,
  installActivity: {},
  launchActivity: {},
  instancesById: {},
  installScreen: null,
};

const COLORS = ["#d0c8a4", "#5e7254", "#d5ae8b", "#efe3a4", "#57b47c", "#64748b"];

function api() {
  return window.pywebview.api;
}

class Dropdown {
  constructor(container, { options = [], value = null, placeholder = "Selecciona…" } = {}) {
    this.container = container;
    this.options = options;
    this.value = value;
    this.placeholder = placeholder;
    this.onChangeCallback = null;
    this._render();
    document.addEventListener("click", (e) => {
      if (!this.container.contains(e.target)) this.close();
    });
  }

  setOptions(options, selectValue = undefined) {
    this.options = options;
    if (selectValue !== undefined) {
      this.value = selectValue;
    } else if (!options.find(o => o.value === this.value)) {
      this.value = options.length ? options[0].value : null;
    }
    this._render();
  }

  setValue(value) {
    this.value = value;
    this._render();
  }

  getValue() { return this.value; }

  onChange(callback) { this.onChangeCallback = callback; }

  isOpen() { return this.container.classList.contains("open"); }
  close() { this.container.classList.remove("open"); }
  toggle() { this.container.classList.toggle("open"); }

  _currentLabel() {
    const found = this.options.find(o => o.value === this.value);
    return found ? found.label : this.placeholder;
  }

  _render() {
    const wasOpen = this.isOpen();
    this.container.classList.add("dropdown");
    this.container.innerHTML = `
      <button type="button" class="dropdown-toggle">
        <span class="dropdown-toggle-label">${escapeHtml(this._currentLabel())}</span>
        <span class="dropdown-chevron"></span>
      </button>
      <div class="dropdown-menu">
        ${this.options.map(o => `
          <div class="dropdown-item ${o.value === this.value ? 'selected' : ''}" data-value="${escapeHtml(String(o.value))}">
            ${escapeHtml(o.label)}
          </div>`).join("")}
      </div>
    `;
    if (wasOpen) this.container.classList.add("open");

    this.container.querySelector(".dropdown-toggle").addEventListener("click", (e) => {
      e.stopPropagation();
      this.toggle();
    });
    this.container.querySelectorAll(".dropdown-item").forEach(item => {
      item.addEventListener("click", (e) => {
        e.stopPropagation();
        this.value = item.dataset.value;
        this.close();
        this._render();
        if (this.onChangeCallback) this.onChangeCallback(this.value);
      });
    });
  }
}

function toast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity 0.3s ease";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, 4200);
}

function loaderLabel(loader) {
  if (loader === "forge") return "Forge";
  if (loader === "fabric") return "Fabric";
  if (loader === "neoforge") return "NeoForge";
  if (loader === "quilt") return "Quilt";
  return "Vanilla";
}

function switchView(viewName) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  document.getElementById(`view-${viewName}`).classList.add("active");
  const navBtn = document.querySelector(`.nav-item[data-view="${viewName}"]`);
  if (navBtn) navBtn.classList.add("active");

  if (viewName === "games") loadGamesGrid();
  if (viewName === "library") loadLibraryList();
  if (viewName === "settings") loadSettingsView();
  if (viewName === "mods") renderModsProfileSelect();
  if (viewName === "modpacks") renderModpacksProfileSelect();
  if (viewName === "shaderpacks") renderShaderpacksProfileSelect();
  if (viewName === "resourcepacks") renderResourcepacksProfileSelect();
  if (viewName === "skin") initSkinViewerIfNeeded();
  if (viewName === "vestidor") initVestidorIfNeeded();
}

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

function updateAccountUI() {
  const nameEl = document.getElementById("accountMiniName");
  const subEl = document.getElementById("accountMiniSub");
  const avatar = document.getElementById("avatarMini");

  const loggedOutRow = document.getElementById("loggedOutRow");
  const loggedInRow = document.getElementById("loggedInRow");
  const settingsAvatar = document.getElementById("settingsAvatar");
  const settingsName = document.getElementById("settingsAccountName");
  const settingsSub = document.getElementById("settingsAccountSub");
  const topnavBtn = document.getElementById("topnavProfileBtn");
  const topnavInitial = document.getElementById("topnavProfileInitial");

  if (state.account) {
    nameEl.textContent = state.account.username;
    subEl.textContent = state.account.isOffline ? "Modo offline" : "Cuenta Microsoft";
    avatar.style.background = "var(--accent-a)";

    loggedOutRow.style.display = "none";
    loggedInRow.style.display = "flex";
    settingsAvatar.style.background = "var(--accent-a)";
    settingsName.textContent = state.account.username;
    settingsSub.textContent = state.account.isOffline ? "Modo offline" : "Cuenta Microsoft";

    topnavBtn.classList.remove("is-guest", "is-offline");
    if (state.account.isOffline) topnavBtn.classList.add("is-offline");
    topnavInitial.textContent = state.account.username.slice(0, 1).toUpperCase();
    renderTopnavFace(state.account.skinUrl || DEFAULT_STEVE_SKIN);
  } else {
    nameEl.textContent = "Sin sesión";
    subEl.textContent = "Inicia sesión";
    avatar.style.background = "var(--accent-a)";

    loggedOutRow.style.display = "flex";
    loggedInRow.style.display = "none";

    topnavBtn.classList.remove("is-offline");
    topnavBtn.classList.add("is-guest");
    topnavInitial.textContent = "?";
    topnavBtn.classList.remove("has-face");
  }
  updatePlayButtonMode();
}

document.getElementById("sidebarAccount").addEventListener("click", () => switchView("account"));
document.getElementById("topnavProfileBtn").addEventListener("click", () => switchView("account"));

async function doLogout() {
  await api().logout();
  state.account = null;
  updateAccountUI();
  document.querySelectorAll(".modal-backdrop.open").forEach(m => m.classList.remove("open"));
  switchView("games");
  toast("Sesión cerrada", "info");
  enforceAccess();
}

document.getElementById("btnLogout").addEventListener("click", doLogout);

const accessGate = document.getElementById("accessGate");

function hideAccessGate() { accessGate.style.display = "none"; }

function showAccessGate(status, username) {
  const el = (id) => document.getElementById(id);
  const isLogin = status === "login", isRestoring = status === "restoring", unverified = status === "unverified";

  const copy = {
    login: ["Inicia sesión", "Para usar el launcher tienes que iniciar sesión con tu cuenta de Microsoft."],
    restoring: ["Reconectando…", "Estamos recuperando tu sesión de Microsoft."],
    unverified: ["No se pudo comprobar tu acceso", "No fue posible consultar la lista de jugadores autorizados. Comprueba tu conexión a internet e inténtalo de nuevo."],
    denied: ["No autorizado", "El acceso a este launcher está restringido en este momento. Si esperas participar, proporciona tu nombre de usuario de Minecraft a los organizadores del estudio."],
  }[status] || ["No autorizado", ""];

  el("accessGateTitle").textContent = copy[0];
  el("accessGateText").textContent = copy[1];
  el("accessGateSession").textContent = (!isLogin && !isRestoring && username) ? `Sesión iniciada como “${username}”.` : "";
  el("btnGateLogin").style.display = isLogin ? "inline-flex" : "none";
  el("btnAccessRetry").style.display = unverified ? "inline-flex" : "none";
  el("btnAccessLogout").style.display = (isLogin || isRestoring) ? "none" : "inline-flex";
  accessGate.classList.toggle("is-neutral", isLogin || isRestoring);
  accessGate.style.display = "flex";
}

async function enforceAccess(force = false, attempt = 1) {
  if (!state.account) {
    showAccessGate(state.restoringSession ? "restoring" : "login");
    return;
  }
  const res = await api().check_access(force);
  if (res.ok && res.status === "unverified") {
    const MAX_ATTEMPTS = 3;
    if (attempt < MAX_ATTEMPTS) {
      setTimeout(() => enforceAccess(true, attempt + 1), 1500);
      return;
    }
    showAccessGate(res.status, res.username);
    return;
  }
  if (res.ok && res.status === "denied") {
    showAccessGate(res.status, res.username);
    return;
  }
  hideAccessGate();
  loadGamesGrid();
}

setInterval(async () => {
  if (!state.account || accessGate.style.display === "flex") return;
  try {
    const res = await api().check_access(true);
    if (res.ok && res.status === "denied") showAccessGate("denied", res.username);
  } catch (e) {  }
}, 120000);

document.getElementById("btnAccessLogout").addEventListener("click", doLogout);
document.getElementById("btnAccessRetry").addEventListener("click", () => enforceAccess(true));

async function startMicrosoftLogin() {
  const buttons = [document.getElementById("btnLoginMicrosoft"), document.getElementById("btnGateLogin")];
  if (buttons[0].disabled) return;
  buttons.forEach(b => b.disabled = true);
  document.getElementById("accountStatusText").textContent = "Iniciando…";
  document.getElementById("accessGateSession").textContent = "Iniciando… se abrirá tu navegador.";
  const res = await api().login_microsoft();
  if (!res.ok) {
    toast("No se pudo iniciar el login", "error");
    buttons.forEach(b => b.disabled = false);
  }
}

document.getElementById("btnLoginMicrosoft").addEventListener("click", startMicrosoftLogin);
document.getElementById("btnGateLogin").addEventListener("click", startMicrosoftLogin);

window.onLauncherEvent = function (event, payload) {
  handleUpdateEvent(event, payload);
  if (event === "session_restored") {
    state.restoringSession = false;
    if (payload.ok) {
      state.account = payload.account;
      updateAccountUI();
      document.getElementById("accountStatusText").textContent = `Conectado como ${payload.account.username}`;
      refreshSkinViewerTexture();
      enforceAccess();
    } else {
      document.getElementById("accountStatusText").textContent = "";
      enforceAccess();
    }
  }
  if (event === "ms_login_status") {
    document.getElementById("accountStatusText").textContent = payload.message;
    if (state.account === null) document.getElementById("accessGateSession").textContent = payload.message;
  }
  if (event === "ms_login_done") {
    document.getElementById("btnLoginMicrosoft").disabled = false;
    document.getElementById("btnGateLogin").disabled = false;
    if (payload.ok) {
      state.account = payload.account;
      updateAccountUI();
      document.getElementById("accountStatusText").textContent = `Conectado como ${payload.account.username}`;
      toast(`Sesión iniciada como ${payload.account.username}`, "success");
      refreshSkinViewerTexture();
      enforceAccess();
    } else {
      document.getElementById("accountStatusText").textContent = "";
      document.getElementById("accessGateSession").textContent = "";
      toast(payload.error || "Error al iniciar sesión con Microsoft", "error");
    }
  }
  if (event === "install_progress") {
    if (payload.profileId === state.selectedProfileId) {
      const pct = payload.max ? Math.min(100, Math.round((payload.value / payload.max) * 100)) : 0;
      document.getElementById("progressFill").style.width = pct + "%";
      document.getElementById("progressText").textContent = payload.text;
    }
  }
  if (event === "launch_done") {
    const il = state.instanceLaunch;
    const handledByInstanceFlow = !!(il && il.mode === "launch" && il.profileId === payload.profileId);
    const wrap = document.getElementById("progressWrap");
    const btn = document.getElementById("btnPlay");
    btn.disabled = false;
    if (payload.ok) {
      state.runningProfileIds.add(payload.profileId);
      updatePlayButtonMode();
      if (!handledByInstanceFlow) toast("Minecraft en ejecución", "success");
      setTimeout(() => { wrap.style.display = "none"; }, 1500);
    } else {
      document.getElementById("btnPlayLabel").textContent = "JUGAR";
      if (!handledByInstanceFlow) toast(payload.error || "Error al instalar/lanzar", "error");
      wrap.style.display = "none";
    }
  }
  if (event === "game_closed") {
    if (state.runningProfileIds.has(payload.profileId)) {
      state.runningProfileIds.delete(payload.profileId);
      updatePlayButtonMode();
    }
    delete state.launchActivity[payload.profileId];
    refreshRunningButtons();
    toast("Minecraft se cerró.", "info");
  }
  if (event === "instance_install_progress") {
    const top = Math.round((payload.overall != null ? payload.overall : (payload.max ? payload.value / payload.max : 0)) * 100);
    const sub = Math.round((payload.sub != null ? payload.sub : 0) * 100);
    const activity = state.installActivity[payload.instanceId];
    let shownTop = top, shownSub = sub;
    if (activity) {
      activity.top = shownTop = Math.max(activity.top || 0, top);
      activity.sub = shownSub = Math.max(activity.sub || 0, sub);
    }
    const sc = state.installScreen;
    if (sc && sc.instanceId === payload.instanceId && sc.mode !== "launch") setInstallBars(shownTop, shownSub);
  }
  if (event === "instance_install_done") {
    delete state.installActivity[payload.instanceId];
    finishInstallScreen(payload);
    const il = state.instanceLaunch;
    if (il && il.mode === "install" && il.instanceId === payload.instanceId) {
      if (payload.ok) {
        toast(`${payload.instance.name} instalado — dale a Jugar`, "success");
      } else {
        toast(payload.error || "No se pudo instalar la instancia", "error");
      }
      state.instanceLaunch = null;
    }
    loadGamesGrid();
    loadLibraryList();
  }
  if (event === "install_progress") {
    const pct = payload.max ? Math.min(100, Math.round((payload.value / payload.max) * 100)) : 0;
    const activity = state.launchActivity[payload.profileId];
    let shown = pct;
    if (activity) activity.pct = shown = Math.max(activity.pct || 0, pct);
    const sc = state.installScreen;
    if (sc && sc.mode === "launch" && sc.profileId === payload.profileId) setInstallBars(shown, shown);
  }
  if (event === "launch_done") {
    delete state.launchActivity[payload.profileId];
    const il = state.instanceLaunch;
    const sc = state.installScreen;
    const screenIsThis = !!(sc && sc.mode === "launch" && sc.profileId === payload.profileId);
    if (payload.ok) {
      if (screenIsThis) closeInstallScreen();
      if (il && il.mode === "launch" && il.profileId === payload.profileId) {
        toast("Minecraft en ejecución", "success");
        state.instanceLaunch = null;
      }
    } else {
      if (screenIsThis) failInstallScreen(payload.error || "Error al iniciar");
      if (il && il.mode === "launch" && il.profileId === payload.profileId) {
        toast(payload.error || "Error al instalar/lanzar", "error");
        state.instanceLaunch = null;
      }
    }
    if (payload.ok) state.runningProfileIds.add(payload.profileId);
    loadGamesGrid();
    loadLibraryList();
  }
  if (event === "modpack_install_progress") {
    const install = state.modpackInstall;
    if (install && install.installId === payload.installId) {
      const pct = payload.max ? Math.min(100, Math.round((payload.value / payload.max) * 100)) : 0;
      install.vbtn.textContent = `Instalando… ${pct}%`;
    }
  }
  if (event === "modpack_install_done") {
    const install = state.modpackInstall;
    if (install && install.installId === payload.installId) {
      if (payload.ok) {
        const mp = payload.modpack;
        install.vbtn.textContent = "✓ Instalado";
        if (install.originalResultBtn) {
          install.originalResultBtn.textContent = "✓ Instalado";
          install.originalResultBtn.classList.add("installed");
        }
        toast(
          mp.unsupportedLoader
            ? `Perfil "${payload.profile.name}" creado, pero el loader del modpack no está soportado por este launcher — puede que no arranque.`
            : `Perfil "${payload.profile.name}" creado e instalado correctamente`,
          mp.unsupportedLoader ? "error" : "success"
        );
        loadProfiles();
        loadInstalledModpacksList();
        setTimeout(() => { document.getElementById("modVersionsModalBackdrop").classList.remove("open"); }, 900);
      } else {
        install.vbtn.disabled = false;
        install.vbtn.textContent = "Instalar";
        toast(payload.error || "No se pudo instalar el modpack", "error");
      }
      state.modpackInstall = null;
    }
  }
};

async function loadProfiles() {
  state.profiles = await api().list_profiles();
  if (!state.selectedProfileId && state.profiles.length) {
    state.selectedProfileId = state.profiles[0].id;
  }
  renderProfileCarousel();
  renderProfilesListView();
  renderLaunchPanel();
}

function renderProfileCarousel() {
  const el = document.getElementById("profileCarousel");
  if (!state.profiles.length) {
    el.innerHTML = `<div class="empty-hint">No tienes perfiles todavía. Ve a la pestaña "Perfiles" para crear uno.</div>`;
    return;
  }
  el.innerHTML = state.profiles.map(p => `
    <div class="profile-card ${p.id === state.selectedProfileId ? 'selected' : ''}"
         style="--card-color:${p.iconColor}" data-id="${p.id}">
      <div class="profile-card-name">${escapeHtml(p.name)}</div>
      <div class="profile-card-meta">${p.version} · ${loaderLabel(p.loader)}</div>
    </div>
  `).join("");
  el.querySelectorAll(".profile-card").forEach(card => {
    card.addEventListener("click", () => {
      state.selectedProfileId = card.dataset.id;
      renderProfileCarousel();
      renderLaunchPanel();
    });
  });
}

function renderLaunchPanel() {
  const profile = state.profiles.find(p => p.id === state.selectedProfileId);
  const nameEl = document.getElementById("selectedProfileName");
  const metaEl = document.getElementById("selectedProfileMeta");
  if (!profile) {
    nameEl.textContent = "Ningún perfil seleccionado";
    metaEl.textContent = "Crea un perfil para empezar";
    document.getElementById("btnPlay").disabled = true;
    return;
  }
  nameEl.textContent = profile.name;
  metaEl.textContent = `${profile.version} · ${loaderLabel(profile.loader)} · ${formatRam(profile.ramMb)} RAM`;
  updatePlayButtonMode();
}

function updatePlayButtonState() {
  const btn = document.getElementById("btnPlay");
  btn.disabled = !(state.account && state.selectedProfileId);
}

function updatePlayButtonMode() {
  const btn = document.getElementById("btnPlay");
  const label = document.getElementById("btnPlayLabel");
  const isRunningThisProfile = state.selectedProfileId !== null && state.runningProfileIds.has(state.selectedProfileId);

  if (isRunningThisProfile) {
    label.textContent = "CERRAR MINECRAFT";
    btn.classList.add("btn-play-stop");
    btn.disabled = false;
  } else {
    label.textContent = "JUGAR";
    btn.classList.remove("btn-play-stop");
    updatePlayButtonState();
  }
}

function renderProfilesListView() {
  const el = document.getElementById("profilesList");
  if (!state.profiles.length) {
    el.innerHTML = `<div class="empty-hint">Aún no has creado ningún perfil.</div>`;
    return;
  }
  el.innerHTML = state.profiles.map(p => `
    <div class="profile-row">
      <div class="profile-row-dot" style="background:${p.iconColor}"></div>
      <div class="profile-row-info">
        <div class="profile-row-name">${escapeHtml(p.name)}</div>
        <div class="profile-row-meta">${p.version} · ${loaderLabel(p.loader)} · ${formatRam(p.ramMb)}</div>
      </div>
      <button class="btn-secondary profile-row-edit" data-id="${p.id}">Editar</button>
      <button class="profile-row-delete" data-id="${p.id}">Eliminar</button>
    </div>
  `).join("");
  el.querySelectorAll(".profile-row-edit").forEach(btn => {
    btn.addEventListener("click", () => openModal(btn.dataset.id));
  });
  el.querySelectorAll(".profile-row-delete").forEach(btn => {
    btn.addEventListener("click", async () => {
      const profile = state.profiles.find(p => p.id === btn.dataset.id);
      const ok = confirm(`¿Eliminar el perfil "${profile ? profile.name : ''}"? Esto borrará también su carpeta (mundos, mods, configs…) de forma permanente.`);
      if (!ok) return;
      const res = await api().delete_profile(btn.dataset.id);
      if (!res.ok) { toast(res.error || "No se pudo eliminar el perfil", "error"); return; }
      if (state.selectedProfileId === btn.dataset.id) state.selectedProfileId = null;
      await loadProfiles();
      toast("Perfil y su carpeta eliminados", "success");
    });
  });
}

document.getElementById("btnPlay").addEventListener("click", async () => {
  if (!state.selectedProfileId) return;

  if (state.runningProfileIds.has(state.selectedProfileId)) {
    const btn = document.getElementById("btnPlay");
    btn.disabled = true;
    const res = await api().close_game(state.selectedProfileId);
    btn.disabled = false;
    if (!res.ok) toast(res.error || "No se pudo cerrar Minecraft", "error");
    return;
  }

  const btn = document.getElementById("btnPlay");
  btn.disabled = true;
  document.getElementById("btnPlayLabel").textContent = "INSTALANDO…";
  const wrap = document.getElementById("progressWrap");
  wrap.style.display = "block";
  document.getElementById("progressFill").style.width = "0%";
  document.getElementById("progressText").textContent = "Preparando…";

  const res = await api().launch_profile(state.selectedProfileId);
  if (!res.ok) {
    toast(res.error || "No se pudo lanzar", "error");
    btn.disabled = false;
    document.getElementById("btnPlayLabel").textContent = "JUGAR";
    wrap.style.display = "none";
  }
});

const modal = document.getElementById("modalBackdrop");

const newProfileVersionDropdown = new Dropdown(document.getElementById("newProfileVersion"), {
  placeholder: "Cargando versiones…",
});
const newProfileLoaderDropdown = new Dropdown(document.getElementById("newProfileLoader"), {
  options: [
    { value: "none", label: "Ninguno" },
    { value: "forge", label: "Forge" },
    { value: "fabric", label: "Fabric" },
    { value: "neoforge", label: "NeoForge" },
    { value: "quilt", label: "Quilt" },
  ],
  value: "none",
});

function openModal(profileId = null) {
  state.editingProfileId = profileId;
  const profile = profileId ? state.profiles.find(p => p.id === profileId) : null;

  document.getElementById("profileModalTitle").textContent = profile ? "Editar perfil" : "Nuevo perfil";
  document.getElementById("btnCreateProfile").textContent = profile ? "Guardar cambios" : "Crear perfil";
  document.getElementById("newProfileName").value = profile ? profile.name : "";

  state.newProfileColor = profile ? profile.iconColor : COLORS[0];
  ramSlider.value = profile ? profile.ramMb : 2048;
  document.getElementById("newProfileRamLabel").textContent = formatRam(parseInt(ramSlider.value, 10));

  modal.classList.add("open");
  populateModalVersions(profile ? profile.version : null);
  newProfileLoaderDropdown.setValue(profile ? profile.loader : "none");
  renderColorSwatches();
}
function closeModal() { modal.classList.remove("open"); state.editingProfileId = null; }

document.getElementById("btnNewProfile").addEventListener("click", () => openModal());
document.getElementById("btnCancelProfile").addEventListener("click", closeModal);
modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });

function renderColorSwatches() {
  const el = document.getElementById("colorSwatches");
  el.innerHTML = COLORS.map(c => `
    <div class="color-swatch ${c === state.newProfileColor ? 'selected' : ''}" style="background:${c}" data-color="${c}"></div>
  `).join("");
  el.querySelectorAll(".color-swatch").forEach(sw => {
    sw.addEventListener("click", () => {
      state.newProfileColor = sw.dataset.color;
      renderColorSwatches();
    });
  });
}

function withTimeout(promise, ms, timeoutMessage) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(timeoutMessage)), ms)),
  ]);
}

async function populateModalVersions(currentVersion = null) {
  newProfileVersionDropdown.setOptions([{ value: "", label: "Cargando…" }], "");
  try {
    const res = await withTimeout(
      api().get_vanilla_versions(false),
      12000,
      "La conexión tardó demasiado. Revisa tu conexión a internet o si el Firewall de Windows está bloqueando la app."
    );
    if (res.ok) {
      const options = res.versions.slice(0, 60).map(v => ({ value: v, label: v }));
      if (currentVersion && !options.some(o => o.value === currentVersion)) {
        options.unshift({ value: currentVersion, label: currentVersion });
      }
      const preferred = currentVersion && options.some(o => o.value === currentVersion)
        ? currentVersion
        : (options.length ? options[0].value : "");
      newProfileVersionDropdown.setOptions(options, preferred);
    } else {
      newProfileVersionDropdown.setOptions([{ value: "", label: "Error al cargar versiones" }], "");
      toast(res.error || "Error al cargar versiones", "error");
    }
  } catch (e) {
    newProfileVersionDropdown.setOptions([{ value: "", label: "Sin conexión — reintentar" }], "");
    toast(e.message || "No se pudo conectar para obtener las versiones", "error");
  }
}

function formatRam(mb) {
  return mb >= 1024 ? `${(mb / 1024).toFixed(mb % 1024 === 0 ? 0 : 1)} GB` : `${mb} MB`;
}

const ramSlider = document.getElementById("newProfileRam");
ramSlider.addEventListener("input", () => {
  document.getElementById("newProfileRamLabel").textContent = formatRam(parseInt(ramSlider.value, 10));
});

document.getElementById("btnCreateProfile").addEventListener("click", async () => {
  const name = document.getElementById("newProfileName").value.trim();
  const version = newProfileVersionDropdown.getValue();
  const loader = newProfileLoaderDropdown.getValue();
  const ram = parseInt(ramSlider.value, 10);

  if (!version) { toast("Elige una versión", "error"); return; }

  if (state.editingProfileId) {
    const res = await api().edit_profile(
      state.editingProfileId, name, version, loader, null, ram, state.newProfileColor
    );
    if (!res.ok) { toast(res.error || "No se pudo guardar el perfil", "error"); return; }
    state.selectedProfileId = res.profile.id;
    await loadProfiles();
    loadInstalledModpacksList();
    closeModal();
    toast(`Perfil "${res.profile.name}" actualizado`, "success");
    return;
  }

  const profile = await api().create_profile(
    name || version, version, loader, null, ram, state.newProfileColor
  );
  state.selectedProfileId = profile.id;
  await loadProfiles();
  closeModal();
  document.getElementById("newProfileName").value = "";
  toast(`Perfil "${profile.name}" creado`, "success");
});

const modsProfileDropdown = new Dropdown(document.getElementById("modsProfileSelect"), {
  placeholder: "No hay perfiles",
});
modsProfileDropdown.onChange((profileId) => loadMods(profileId));

function renderModsProfileSelect() {
  if (!state.profiles.length) {
    modsProfileDropdown.setOptions([], null);
    document.getElementById("modsList").innerHTML = `<div class="empty-hint">Crea un perfil primero.</div>`;
    return;
  }
  const options = state.profiles.map(p => ({ value: p.id, label: p.name }));
  const preferred = state.selectedProfileId && options.find(o => o.value === state.selectedProfileId)
    ? state.selectedProfileId
    : options[0].value;
  modsProfileDropdown.setOptions(options, preferred);
  loadMods(preferred);
}

document.getElementById("btnOpenModsFolder").addEventListener("click", async () => {
  const profileId = modsProfileDropdown.getValue();
  if (!profileId) return;
  const res = await api().open_mods_folder(profileId);
  if (!res.ok) toast(res.error || "No se pudo abrir la carpeta", "error");
});

async function loadMods(profileId) {
  const listEl = document.getElementById("modsList");
  if (!profileId) { listEl.innerHTML = ""; return; }
  const res = await api().list_mods(profileId);
  if (!res.ok) { listEl.innerHTML = `<div class="empty-hint">${res.error}</div>`; return; }
  if (!res.mods.length) {
    listEl.innerHTML = `<div class="empty-hint">Esta carpeta de mods está vacía. Coloca archivos .jar en ella y vuelve a abrir esta pestaña.</div>`;
    return;
  }
  listEl.innerHTML = res.mods.map(m => `
    <div class="mod-row">
      <div>
        <div class="mod-row-name">${escapeHtml(m.filename)}</div>
        <div class="mod-row-size">${m.sizeKb} KB</div>
      </div>
      <div style="flex:1"></div>
      <label class="switch">
        <input type="checkbox" data-filename="${escapeHtml(m.filename)}" ${m.enabled ? "checked" : ""}>
        <span class="switch-track"></span>
      </label>
    </div>
  `).join("");
  listEl.querySelectorAll("input[type=checkbox]").forEach(chk => {
    chk.addEventListener("change", async () => {
      const profileId = modsProfileDropdown.getValue();
      const res = await api().toggle_mod(profileId, chk.dataset.filename);
      if (!res.ok) { toast(res.error, "error"); chk.checked = !chk.checked; }
    });
  });
}

function setupPacksView({ dropdownId, listId, openButtonId, listMethod, openMethod, searchMethod, versionsMethod, installMethod, searchInputId, searchButtonId, searchHintId, searchResultsId, packType, rowIcon, emptyMessage }) {
  const dropdown = new Dropdown(document.getElementById(dropdownId), { placeholder: "No hay perfiles" });

  async function load(profileId) {
    const listEl = document.getElementById(listId);
    if (!profileId) { listEl.innerHTML = ""; return; }
    const res = await api()[listMethod](profileId);
    if (!res.ok) { listEl.innerHTML = `<div class="empty-hint">${escapeHtml(res.error)}</div>`; return; }
    if (!res.packs.length) {
      listEl.innerHTML = `<div class="empty-hint">${emptyMessage}</div>`;
      return;
    }
    listEl.innerHTML = res.packs.map(pack => `
      <div class="pack-row">
        <div class="pack-row-icon">${rowIcon}</div>
        <div>
          <div class="pack-row-name">${escapeHtml(pack.filename)}</div>
          <div class="pack-row-size">${pack.sizeKb} KB</div>
        </div>
      </div>
    `).join("");
  }

  dropdown.onChange(load);
  document.getElementById(openButtonId).addEventListener("click", async () => {
    const profileId = dropdown.getValue();
    if (!profileId) return;
    const res = await api()[openMethod](profileId);
    if (!res.ok) toast(res.error || "No se pudo abrir la carpeta", "error");
  });

  async function search() {
    const profileId = dropdown.getValue();
    const query = document.getElementById(searchInputId).value.trim();
    const hintEl = document.getElementById(searchHintId);
    const resultsEl = document.getElementById(searchResultsId);
    if (!profileId) { hintEl.textContent = "Crea un perfil primero para buscar packs compatibles."; return; }
    if (!query) { hintEl.textContent = "Escribe algo para buscar."; return; }
    hintEl.textContent = "Buscando en Modrinth…"; resultsEl.innerHTML = "";
    const res = await api()[searchMethod](profileId, query);
    if (!res.ok) { hintEl.textContent = res.error || "No se pudo buscar en Modrinth."; return; }
    if (!res.hits.length) { hintEl.textContent = `Sin resultados para "${query}".`; return; }
    hintEl.textContent = `${res.totalHits} resultado(s) — mostrando los primeros ${res.hits.length}.`;
    resultsEl.innerHTML = res.hits.map(hit => `<div class="mod-result-card">
      <img class="mod-result-icon" src="${escapeHtml(hit.iconUrl || "")}" onerror="this.style.visibility='hidden'" alt="">
      <div class="mod-result-info"><div class="mod-result-title">${escapeHtml(hit.title)}<span class="mod-result-author">por ${escapeHtml(hit.author || "?")}</span></div><div class="mod-result-desc">${escapeHtml(hit.description || "")}</div></div>
      <div class="mod-result-downloads">${formatDownloadCount(hit.downloads)}<br>descargas</div><button class="mod-install-btn" data-project-id="${escapeHtml(hit.id)}">Instalar</button>
    </div>`).join("");
    resultsEl.querySelectorAll(".mod-install-btn").forEach(btn => btn.addEventListener("click", async () => {
      btn.disabled = true; btn.textContent = "Buscando versión…";
      const versionsRes = await api()[versionsMethod](profileId, btn.dataset.projectId);
      if (!versionsRes.ok || !versionsRes.versions.length) { toast(versionsRes.error || "No hay una versión compatible con tu perfil.", "error"); btn.disabled = false; btn.textContent = "Instalar"; return; }
      const best = versionsRes.versions[0]; btn.textContent = "Instalando…";
      const installRes = await api()[installMethod](profileId, best.downloadUrl, best.filename);
      if (!installRes.ok) { toast(installRes.error || `No se pudo instalar el ${packType}`, "error"); btn.disabled = false; btn.textContent = "Instalar"; return; }
      btn.textContent = "✓ Instalado"; btn.classList.add("installed"); toast(`${best.filename} instalado correctamente`, "success"); load(profileId);
    }));
  }
  document.getElementById(searchButtonId).addEventListener("click", search);
  document.getElementById(searchInputId).addEventListener("keydown", event => { if (event.key === "Enter") search(); });

  return function renderProfileSelect() {
    const listEl = document.getElementById(listId);
    if (!state.profiles.length) {
      dropdown.setOptions([], null);
      listEl.innerHTML = `<div class="empty-hint">Crea un perfil primero.</div>`;
      return;
    }
    const options = state.profiles.map(p => ({ value: p.id, label: p.name }));
    const preferred = state.selectedProfileId && options.some(o => o.value === state.selectedProfileId)
      ? state.selectedProfileId : options[0].value;
    dropdown.setOptions(options, preferred);
    load(preferred);
  };
}

const renderShaderpacksProfileSelect = setupPacksView({
  dropdownId: "shaderpacksProfileSelect", listId: "shaderpacksList",
  openButtonId: "btnOpenShaderpacksFolder", listMethod: "list_shaderpacks",
  openMethod: "open_shaderpacks_folder", searchMethod: "search_shaderpacks_online", versionsMethod: "get_shaderpack_online_versions", installMethod: "install_shaderpack_online",
  searchInputId: "shaderpacksSearchInput", searchButtonId: "btnShaderpacksSearch", searchHintId: "shaderpacksSearchHint", searchResultsId: "shaderpacksSearchResults", packType: "shaderpack", rowIcon: "✺",
  emptyMessage: "Esta carpeta está vacía. Coloca aquí archivos .zip de shaders y vuelve a abrir esta pestaña.",
});

const renderResourcepacksProfileSelect = setupPacksView({
  dropdownId: "resourcepacksProfileSelect", listId: "resourcepacksList",
  openButtonId: "btnOpenResourcepacksFolder", listMethod: "list_resourcepacks",
  openMethod: "open_resourcepacks_folder", searchMethod: "search_resourcepacks_online", versionsMethod: "get_resourcepack_online_versions", installMethod: "install_resourcepack_online",
  searchInputId: "resourcepacksSearchInput", searchButtonId: "btnResourcepacksSearch", searchHintId: "resourcepacksSearchHint", searchResultsId: "resourcepacksSearchResults", packType: "resourcepack", rowIcon: "▤",
  emptyMessage: "Esta carpeta está vacía. Coloca aquí archivos .zip o carpetas de resource packs y vuelve a abrir esta pestaña.",
});

document.querySelectorAll(".mods-subtab:not([data-pack-tab])").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".mods-subtab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".mods-subview").forEach(v => v.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`modsSubview-${tab.dataset.subtab}`).classList.add("active");
  });
});

document.querySelectorAll(".mods-subtab[data-pack-tab]").forEach(tab => {
  tab.addEventListener("click", () => {
    const packTab = tab.dataset.packTab;
    document.querySelectorAll(`.mods-subtab[data-pack-tab="${packTab}"]`).forEach(item => item.classList.remove("active"));
    document.querySelectorAll(`[id^="${packTab}Subview-"]`).forEach(view => view.classList.remove("active"));
    tab.classList.add("active"); document.getElementById(`${packTab}Subview-${tab.dataset.subtab}`).classList.add("active");
  });
});

let modSearchDebounceTimer = null;

document.getElementById("btnModSearch").addEventListener("click", runModSearch);
document.getElementById("modSearchInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runModSearch();
});

async function runModSearch() {
  const profileId = modsProfileDropdown.getValue();
  const query = document.getElementById("modSearchInput").value.trim();
  const hintEl = document.getElementById("modSearchHint");
  const resultsEl = document.getElementById("modSearchResults");

  if (!profileId) {
    hintEl.textContent = "Crea un perfil primero para poder buscar mods compatibles con él.";
    return;
  }
  if (!query) {
    hintEl.textContent = "Escribe algo para buscar.";
    return;
  }

  const profile = state.profiles.find(p => p.id === profileId);
  if (profile && profile.loader === "none") {
    hintEl.textContent = "Este perfil no tiene Forge ni Fabric — la mayoría de los mods no van a funcionar sin uno de los dos. Puedes buscar igual, pero revisa la compatibilidad.";
  } else {
    hintEl.textContent = "Buscando…";
  }

  resultsEl.innerHTML = "";
  const res = await api().search_mods_online(profileId, query);
  if (!res.ok) {
    hintEl.textContent = res.error || "No se pudo buscar en Modrinth.";
    return;
  }
  if (!res.hits.length) {
    hintEl.textContent = `Sin resultados para "${query}".`;
    return;
  }
  hintEl.textContent = `${res.totalHits} resultado(s) — mostrando los primeros ${res.hits.length}.`;

  resultsEl.innerHTML = res.hits.map(hit => `
    <div class="mod-result-card" data-project-id="${escapeHtml(hit.id)}">
      <img class="mod-result-icon" src="${escapeHtml(hit.iconUrl || '')}" onerror="this.style.visibility='hidden'" alt="">
      <div class="mod-result-info">
        <div class="mod-result-title">${escapeHtml(hit.title)}<span class="mod-result-author">por ${escapeHtml(hit.author || '?')}</span></div>
        <div class="mod-result-desc">${escapeHtml(hit.description || '')}</div>
      </div>
      <div class="mod-result-downloads">${formatDownloadCount(hit.downloads)}<br>descargas</div>
      <button class="mod-install-btn" data-project-id="${escapeHtml(hit.id)}" data-title="${escapeHtml(hit.title)}">Instalar</button>
    </div>
  `).join("");

  resultsEl.querySelectorAll(".mod-install-btn").forEach(btn => {
    btn.addEventListener("click", () => openModVersionPicker(btn, profileId));
  });
}

function formatDownloadCount(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function formatModDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("es", { year: "numeric", month: "short", day: "numeric" });
  } catch (e) {
    return "";
  }
}

async function openModVersionPicker(btn, profileId) {
  const projectId = btn.dataset.projectId;
  const modTitle = btn.dataset.title || "Mod";

  btn.disabled = true;
  btn.textContent = "Cargando versiones…";
  const versionsRes = await api().get_mod_online_versions(profileId, projectId);
  btn.disabled = false;
  btn.textContent = "Instalar";

  if (!versionsRes.ok) {
    toast(versionsRes.error || "No se pudieron obtener las versiones", "error");
    return;
  }
  if (!versionsRes.versions.length) {
    toast("No hay ninguna versión de este mod compatible con tu perfil (versión de Minecraft / loader).", "error");
    return;
  }

  document.getElementById("modVersionsModalTitle").textContent = modTitle;
  document.getElementById("modVersionsHint").textContent =
    `${versionsRes.versions.length} versión(es) compatible(s) con tu perfil — la más reciente primero.`;

  const listEl = document.getElementById("modVersionsList");
  listEl.innerHTML = versionsRes.versions.map((v, i) => `
    <div class="mod-version-row">
      <div class="mod-version-info">
        <div class="mod-version-name">
          ${escapeHtml(v.name || v.versionNumber)}
          ${i === 0 ? '<span class="mod-version-latest-badge">más reciente</span>' : ''}
        </div>
        <div class="mod-version-meta">${escapeHtml(v.gameVersions.join(', '))} · ${escapeHtml(v.loaders.join(', '))} · ${formatModDate(v.datePublished)}</div>
      </div>
      <button class="mod-install-btn" data-index="${i}">Instalar</button>
    </div>
  `).join("");

  listEl.querySelectorAll(".mod-install-btn").forEach(vbtn => {
    const version = versionsRes.versions[parseInt(vbtn.dataset.index, 10)];
    vbtn.addEventListener("click", () => installChosenModVersion(vbtn, profileId, version, btn));
  });

  document.getElementById("modVersionsModalBackdrop").classList.add("open");
}

document.getElementById("btnCloseModVersions").addEventListener("click", () => {
  document.getElementById("modVersionsModalBackdrop").classList.remove("open");
});

async function installChosenModVersion(vbtn, profileId, version, originalResultBtn) {
  vbtn.disabled = true;
  vbtn.textContent = "Instalando…";

  const installRes = await api().install_mod_online(profileId, version.downloadUrl, version.filename);
  if (!installRes.ok) {
    toast(installRes.error || "No se pudo instalar el mod", "error");
    vbtn.disabled = false;
    vbtn.textContent = "Instalar";
    return;
  }

  vbtn.textContent = "✓ Instalado";
  toast(`${version.filename} instalado correctamente`, "success");
  if (originalResultBtn) {
    originalResultBtn.textContent = "✓ Instalado";
    originalResultBtn.classList.add("installed");
  }

  loadMods(profileId);

  setTimeout(() => {
    document.getElementById("modVersionsModalBackdrop").classList.remove("open");
  }, 700);
}

async function renderModpacksProfileSelect() {
  await loadInstalledModpacksList();
}

async function loadInstalledModpacksList() {
  const el = document.getElementById("modpacksInstalledList");
  const res = await api().list_installed_modpacks();
  if (!res.ok) { el.innerHTML = `<div class="empty-hint">${escapeHtml(res.error)}</div>`; return; }
  if (!res.modpacks.length) {
    el.innerHTML = `<div class="empty-hint">Todavía no has instalado ningún modpack. Ve a "Buscar modpacks" para instalar uno.</div>`;
    return;
  }
  el.innerHTML = res.modpacks.map(({ profile, modpack }) => `
    <div class="mod-row">
      <div>
        <div class="mod-row-name">${escapeHtml(profile.name)}${modpack.versionNumber ? ` · v${escapeHtml(String(modpack.versionNumber))}` : ""}</div>
        <div class="mod-row-size">${escapeHtml(modpack.minecraftVersion || "?")} · ${loaderLabel(modpack.loader)}${modpack.unsupportedLoader ? " · loader no soportado por este launcher" : ""}</div>
      </div>
      <div style="flex:1"></div>
      <button class="btn-secondary modpack-edit-btn" data-id="${escapeHtml(profile.id)}">Editar</button>
      <button class="btn-secondary modpack-play-btn" data-id="${escapeHtml(profile.id)}">Jugar →</button>
    </div>
  `).join("");

  el.querySelectorAll(".modpack-edit-btn").forEach(btn => {
    btn.addEventListener("click", () => openModal(btn.dataset.id));
  });
  el.querySelectorAll(".modpack-play-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.selectedProfileId = btn.dataset.id;
      switchView("home");
      renderProfileCarousel();
      renderLaunchPanel();
    });
  });
}

document.getElementById("btnModpackSearch").addEventListener("click", runModpackSearch);
document.getElementById("modpackSearchInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runModpackSearch();
});

async function runModpackSearch() {
  const query = document.getElementById("modpackSearchInput").value.trim();
  const hintEl = document.getElementById("modpackSearchHint");
  const resultsEl = document.getElementById("modpackSearchResults");

  if (!query) { hintEl.textContent = "Escribe algo para buscar."; return; }

  hintEl.textContent = "Buscando en Modrinth…";
  resultsEl.innerHTML = "";
  const res = await api().search_modpacks_online(query);
  if (!res.ok) { hintEl.textContent = res.error || "No se pudo buscar en Modrinth."; return; }
  if (!res.hits.length) { hintEl.textContent = `Sin resultados para "${query}".`; return; }
  hintEl.textContent = `${res.totalHits} resultado(s) — mostrando los primeros ${res.hits.length}.`;

  resultsEl.innerHTML = res.hits.map(hit => `
    <div class="mod-result-card" data-project-id="${escapeHtml(hit.id)}">
      <img class="mod-result-icon" src="${escapeHtml(hit.iconUrl || '')}" onerror="this.style.visibility='hidden'" alt="">
      <div class="mod-result-info">
        <div class="mod-result-title">${escapeHtml(hit.title)}<span class="mod-result-author">por ${escapeHtml(hit.author || '?')}</span></div>
        <div class="mod-result-desc">${escapeHtml(hit.description || '')}</div>
      </div>
      <div class="mod-result-downloads">${formatDownloadCount(hit.downloads)}<br>descargas</div>
      <button class="mod-install-btn" data-project-id="${escapeHtml(hit.id)}" data-title="${escapeHtml(hit.title)}">Instalar</button>
    </div>
  `).join("");

  resultsEl.querySelectorAll(".mod-install-btn").forEach(btn => {
    btn.addEventListener("click", () => openModpackVersionPicker(btn));
  });
}

async function openModpackVersionPicker(btn) {
  const projectId = btn.dataset.projectId;
  const modpackTitle = btn.dataset.title || "Modpack";

  btn.disabled = true;
  btn.textContent = "Cargando versiones…";
  const versionsRes = await api().get_modpack_online_versions(projectId);
  btn.disabled = false;
  btn.textContent = "Instalar";

  if (!versionsRes.ok) {
    toast(versionsRes.error || "No se pudieron obtener las versiones", "error");
    return;
  }
  if (!versionsRes.versions.length) {
    toast("Este modpack no tiene ninguna versión disponible.", "error");
    return;
  }

  document.getElementById("modVersionsModalTitle").textContent = modpackTitle;
  document.getElementById("modVersionsHint").textContent =
    `${versionsRes.versions.length} versión(es) disponible(s) — la más reciente primero. Instalar creará un perfil nuevo llamado "${modpackTitle}", configurado según lo que traiga el modpack.`;

  const listEl = document.getElementById("modVersionsList");
  listEl.innerHTML = versionsRes.versions.map((v, i) => `
    <div class="mod-version-row">
      <div class="mod-version-info">
        <div class="mod-version-name">
          ${escapeHtml(v.name || v.versionNumber)}
          ${i === 0 ? '<span class="mod-version-latest-badge">más reciente</span>' : ''}
        </div>
        <div class="mod-version-meta">${escapeHtml(v.gameVersions.join(', '))} · ${escapeHtml(v.loaders.join(', '))} · ${formatModDate(v.datePublished)}</div>
      </div>
      <button class="mod-install-btn" data-index="${i}">Instalar</button>
    </div>
  `).join("");

  listEl.querySelectorAll(".mod-install-btn").forEach(vbtn => {
    const version = versionsRes.versions[parseInt(vbtn.dataset.index, 10)];
    vbtn.addEventListener("click", () => installChosenModpackVersion(vbtn, version, modpackTitle, btn));
  });

  document.getElementById("modVersionsModalBackdrop").classList.add("open");
}

async function installChosenModpackVersion(vbtn, version, modpackTitle, originalResultBtn) {
  vbtn.disabled = true;
  vbtn.textContent = "Creando perfil…";

  const res = await api().install_modpack_online(
    version.downloadUrl, version.filename, modpackTitle, version.versionNumber
  );
  if (!res.ok) {
    toast(res.error || "No se pudo instalar el modpack", "error");
    vbtn.disabled = false;
    vbtn.textContent = "Instalar";
    return;
  }
  state.modpackInstall = { installId: res.installId, vbtn, originalResultBtn };
}

let skinViewer = null;

function initSkinViewerIfNeeded() {
  ensureSkinViewerCreated();
  refreshSkinViewerTexture();
}

function ensureSkinViewerCreated() {
  if (skinViewer) return;
  if (!window.skinview3d) {
    window.addEventListener("skinview3dready", ensureSkinViewerCreated, { once: true });
    setTimeout(() => {
      if (!skinViewer && window.skinview3d) { ensureSkinViewerCreated(); refreshSkinViewerTexture(); }
      else if (!skinViewer) showSkinError("No se pudo cargar la librería del visor 3D (skinview3d). Revisa tu conexión a internet o si algún firewall/antivirus está bloqueando cdn.jsdelivr.net.");
    }, 2500);
    return;
  }
  const canvas = document.getElementById("skinCanvas");
  const wrap = canvas.parentElement;
  try {
    skinViewer = new skinview3d.SkinViewer({
      canvas,
      width: wrap.clientWidth,
      height: wrap.clientHeight,
    });
    skinViewer.autoRotate = true;
    skinViewer.controls.enableZoom = true;
    skinViewer.animation = new skinview3d.WalkingAnimation();
  } catch (e) {
    showSkinError("Error al iniciar el visor 3D: " + e.message);
  }
}

const DEFAULT_STEVE_SKIN = "https://textures.minecraft.net/texture/1a4af718455d4aab528e7a61f86fa25e6a369d1768dcb13f7df319a713eb810b";

function renderTopnavFace(skinUrl) {
  const canvas = document.getElementById("topnavProfileFace");
  const btn = document.getElementById("topnavProfileBtn");
  if (!canvas || !skinUrl) { if (btn) btn.classList.remove("has-face"); return; }

  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 8, 8, 8, 8, 0, 0, canvas.width, canvas.height);
    if (img.height >= 16) {
      ctx.drawImage(img, 40, 8, 8, 8, 0, 0, canvas.width, canvas.height);
    }
    btn.classList.add("has-face");
  };
  img.onerror = () => { btn.classList.remove("has-face"); };
  img.src = skinUrl;
}

function refreshSkinViewerTexture() {
  if (!skinViewer) return;
  const hint = document.querySelector(".skin-hint");
  if (hint) { hint.textContent = "Arrastra para girar"; hint.style.color = ""; }

  const skinUrl = (state.account && state.account.skinUrl) ? state.account.skinUrl : DEFAULT_STEVE_SKIN;
  skinViewer.loadSkin(skinUrl).catch((e) => {
    showSkinError("No se pudo cargar la skin (" + (e.message || "error desconocido") + ").");
  });
  const capeUrl = state.account && state.account.capeUrl;
  if (capeUrl) {
    const p = skinViewer.loadCape(capeUrl);
    if (p && p.catch) p.catch(() => {});
  } else {
    skinViewer.resetCape();
  }
}

function showSkinError(message) {
  const hint = document.querySelector(".skin-hint");
  if (hint) { hint.textContent = message; hint.style.color = "var(--danger)"; }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

if (window.pywebview) {
  // Primero la comprobación de actualización: si hay una, se instala y el launcher se reinicia solo.
  Promise.resolve(window.__autoUpdate).then(init, init);
} else {
  window.addEventListener("pywebviewready", init);
}

async function init() {
  const account = await api().get_account();
  if (account) { state.account = account; }
  else {
    const hasSaved = await api().has_saved_session();
    if (hasSaved) {
      state.restoringSession = true;
      document.getElementById("accountStatusText").textContent = "Reconectando con tu cuenta de Microsoft…";
      showAccessGate("restoring");
      await api().try_restore_session();
    }
  }
  updateAccountUI();
  await syncRunningGameState();
  enforceAccess();
  await loadProfiles();
  showCurrentVersion();
  if (!state.restoringSession) loadGamesGrid();
}

async function syncRunningGameState() {
  try {
    const res = await api().get_running_game();
    state.runningProfileIds = new Set(res.profiles || []);
    if (res.running) updatePlayButtonMode();
  } catch (e) {
  }
}

async function showCurrentVersion() {
  try {
    const T = window.__TAURI__;
    const version = (T && T.app && T.app.getVersion) ? await T.app.getVersion() : await api().get_current_version();
    document.getElementById("brandVersion").textContent = `v${version}`;
  } catch (e) {
  }
}

function handleUpdateEvent(event, payload) {
  if (event === "presence_update") {
    updateOnlineIndicator(payload.count, payload.available);
  }
}

function updateOnlineIndicator(count, available) {
  const el = document.getElementById("onlineIndicator");
  const countEl = document.getElementById("onlineCount");
  if (!el || !countEl) return;
  if (!available) {
    el.style.display = "none";
    return;
  }
  el.style.display = "flex";
  el.classList.toggle("offline", false);
  countEl.textContent = count === 1 ? "1 persona" : `${count} personas`;
}

async function loadGamesGrid(attempt = 1) {
  const el = document.getElementById("gamesGrid");
  if (!el.children.length) el.innerHTML = `<div class="empty-hint">Cargando instancias…</div>`;

  let res;
  try {
    res = await api().list_instances();
  } catch (e) {
    res = { ok: false, error: "No se pudo conectar con el launcher." };
  }

  const MAX_ATTEMPTS = 3;
  const RETRY_DELAY_MS = 1500;

  if (!res.ok || (res.fetchFailed && !res.instances.length)) {
    if (attempt < MAX_ATTEMPTS) {
      setTimeout(() => loadGamesGrid(attempt + 1), RETRY_DELAY_MS);
      return;
    }
    el.innerHTML = `<div class="empty-hint">${escapeHtml(res.error || "No se pudieron cargar las instancias. Comprueba tu conexión.")}<button class="btn-secondary retry-btn" id="retryGamesGrid">Reintentar</button></div>`;
    document.getElementById("retryGamesGrid").addEventListener("click", () => loadGamesGrid());
    return;
  }
  if (res.blocked) {
    el.innerHTML = `<div class="empty-hint">${res.blocked === "login"
      ? "Inicia sesión con tu cuenta de Microsoft para ver las instancias."
      : "No tienes acceso a las instancias."}</div>`;
    return;
  }
  if (!res.instances.length) {
    el.innerHTML = `<div class="empty-hint">Todavía no hay ninguna instancia pública.</div>`;
    return;
  }

  state.instancesById = Object.fromEntries(res.instances.map(i => [i.id, i]));

  el.innerHTML = res.instances.map(inst => {
    const installAct = state.installActivity[inst.id];
    const launchAct = inst.profileId ? state.launchActivity[inst.profileId] : null;
    const isRunning = !!(inst.profileId && state.runningProfileIds.has(inst.profileId));
    const busy = installAct || launchAct;

    let label = !inst.installed ? "Instalar" : inst.updateAvailable ? "Actualizar" : "Jugar";
    let stopClass = "";
    if (busy) {
      label = installAct ? (installAct.mode === "update" ? "Actualizando…" : "Progreso") : "Iniciando…";
    } else if (isRunning) {
      label = "Cerrar Minecraft";
      stopClass = "btn-stop";
    }

    return `
    <div class="game-card" data-instance-id="${escapeHtml(inst.id)}">
      <div class="game-card-image" data-img-url="${escapeHtml(inst.image || "")}" data-video-url="${escapeHtml(inst.video || "")}" data-video-fallback="${escapeHtml(inst.videoRemote || "")}"></div>
      <div class="game-card-body">
        <div class="game-card-name">${escapeHtml(inst.name)}</div>
        <div class="game-card-actions">
          <button class="btn-primary game-card-btn ${stopClass}" data-instance-id="${escapeHtml(inst.id)}"
                  data-profile-id="${escapeHtml(inst.profileId || "")}" data-installed="${inst.installed}"
                  data-update="${inst.updateAvailable}" data-running="${isRunning}">
            ${label}
          </button>
          <button class="btn-secondary game-card-info-btn" data-instance-id="${escapeHtml(inst.id)}">Información</button>
        </div>
      </div>
    </div>
  `;
  }).join("");

  el.querySelectorAll(".game-card-btn").forEach(btn => {
    btn.addEventListener("click", () => onGameCardClick(btn));
  });
  el.querySelectorAll(".game-card-info-btn").forEach(btn => {
    btn.addEventListener("click", () => openInfoModal(btn.dataset.instanceId));
  });
  el.querySelectorAll(".game-card-image").forEach(div => {
    loadCardImage(div, div.dataset.imgUrl);
    if (div.dataset.videoUrl) attachCoverVideo(div, div.dataset.videoUrl, { cache: true, fallback: div.dataset.videoFallback });
  });
}

const coverVideoCache = new Map();

function attachCoverVideo(div, url, { cache = false, fallback = "" } = {}) {
  if (!url || !div.isConnected) return;

  let video = cache ? coverVideoCache.get(url) : null;
  if (!video) {
    video = document.createElement("video");
    video.className = "cover-video";
    video.muted = true;
    video.defaultMuted = true;
    video.loop = true;
    video.autoplay = true;
    video.playsInline = true;
    video.preload = "auto";
    video.disablePictureInPicture = true;
    video.setAttribute("muted", "");
    const show = () => video.classList.add("ready");
    video.addEventListener("loadeddata", show);
    video.addEventListener("playing", show);
    video.addEventListener("error", () => {
      if (fallback && video.src !== fallback) {
        video.src = fallback;
        video.play().catch(() => {});
        return;
      }
      coverVideoCache.delete(url);
      video.remove();
    });
    video.src = url;
    video.load();
    if (cache) coverVideoCache.set(url, video);
  }
  div.appendChild(video);
  if (video.readyState >= 2) video.classList.add("ready");
  const p = video.play();
  if (p && p.catch) p.catch(() => {});
}

document.addEventListener("visibilitychange", () => {
  document.querySelectorAll(".cover-video").forEach(v => {
    if (document.hidden) v.pause(); else v.play().catch(() => {});
  });
});

// Carga una imagen remota de forma fiable: primero directa; si falla, la descarga el launcher (Python, con
// reintentos) y se usa la copia local. Devuelve la URL que sí carga, o "" si ninguna funciona.
const resolvedImages = new Map();

function probeImage(url) {
  return new Promise((resolve) => {
    const im = new Image();
    const timer = setTimeout(() => { im.src = ""; resolve(false); }, 15000);
    im.onload = () => { clearTimeout(timer); resolve(true); };
    im.onerror = () => { clearTimeout(timer); resolve(false); };
    im.src = url;
  });
}

async function resolveImage(...urls) {
  const list = urls.filter(Boolean);
  const cacheKey = list.join("|");
  if (resolvedImages.has(cacheKey)) return resolvedImages.get(cacheKey);
  const job = (async () => {
    // 1) copia local del launcher (ya descargada en segundo plano, sale al instante)
    for (const u of list) {
      if (u.startsWith("file:") || u.startsWith("data:")) { if (await probeImage(u)) return u; continue; }
      try {
        const res = await api().cache_image(u);
        if (res && res.ok && res.uri && await probeImage(res.uri)) return res.uri;
      } catch (e) { console.warn("cache_image falló", e); }
    }
    // 2) último recurso: carga directa desde la red
    for (const u of list) { if (await probeImage(u)) return u; }
    return "";
  })();
  resolvedImages.set(cacheKey, job);
  const result = await job;
  if (!result) resolvedImages.delete(cacheKey);
  return result;
}

function loadCardImage(div, url) {
  if (!url || !div.isConnected) return;
  resolveImage(url).then((ok) => {
    if (ok && div.isConnected) div.style.backgroundImage = `url('${ok}')`;
  });
}


// ---- Pantalla de instalación (video de fondo + dos barras) ----
function setInstallBars(top, sub) {
  const sc = state.installScreen;
  const topLabel = !sc ? "Instalando…" : sc.mode === "launch" ? "Iniciando…" : sc.mode === "update" ? "Actualizando…" : "Instalando…";
  document.getElementById("installTopLabel").textContent = topLabel;
  document.getElementById("installBottomLabel").textContent = sub >= 100 ? "Librerías descargadas" : "Descargando librerías…";
  document.getElementById("installTopPct").textContent = top + "%";
  document.getElementById("installTopFill").style.width = top + "%";
  document.getElementById("installBottomPct").textContent = sub + "%";
  document.getElementById("installBottomFill").style.width = sub + "%";
}

// mode: "install" | "update" | "launch". Se puede volver a abrir mientras dure la descarga.
function openInstallScreen(instanceId, mode, profileId = null) {
  const inst = state.instancesById[instanceId] || { id: instanceId, name: "Instancia" };
  const screen = document.getElementById("installScreen");
  const bg = document.getElementById("installScreenBg");

  bg.querySelectorAll(".cover-video").forEach(v => { v.pause(); v.remove(); });
  bg.style.backgroundImage = "";
  if (inst.image) loadCardImage(bg, inst.image);
  if (inst.video) attachCoverVideo(bg, inst.video, { fallback: inst.videoRemote });

  const verb = mode === "update" ? "Actualizando" : mode === "launch" ? "Iniciando" : "Instalando";
  state.installScreen = { instanceId, profileId, mode, verb };
  screen.classList.remove("is-done", "is-error");
  screen.classList.toggle("is-single", mode === "launch");
  document.getElementById("installScreenTitle").textContent = inst.name;
  document.getElementById("btnInstallBack").textContent = "\u2190 Volver";

  let top = 0, sub = 0;
  if (mode === "launch") {
    const act = profileId ? state.launchActivity[profileId] : null;
    top = sub = act ? (act.pct || 0) : 0;
  } else {
    const act = state.installActivity[instanceId];
    if (act) { top = act.top || 0; sub = act.sub || 0; }
  }
  setInstallBars(top, sub);
  screen.style.display = "block";
}

function closeInstallScreen() {
  const screen = document.getElementById("installScreen");
  document.querySelectorAll("#installScreenBg .cover-video").forEach(v => { v.pause(); v.remove(); });
  screen.style.display = "none";
  state.installScreen = null;
}

function failInstallScreen(message) {
  const screen = document.getElementById("installScreen");
  screen.classList.add("is-error");
  document.getElementById("installScreenTitle").textContent = "No se pudo iniciar";
  document.getElementById("installTopLabel").textContent = message;
  document.getElementById("btnInstallBack").textContent = "\u2190 Volver";
}

function finishInstallScreen(payload) {
  const sc = state.installScreen;
  if (!sc || sc.instanceId !== payload.instanceId) return;
  const screen = document.getElementById("installScreen");
  if (payload.ok) {
    screen.classList.add("is-done");
    document.getElementById("installScreenTitle").textContent = "\u00a1Instalaci\u00f3n completa!";
    document.getElementById("installTopLabel").textContent = sc.mode === "update" ? "Actualizada" : "Instalada";
    document.getElementById("installBottomLabel").textContent = "Librerías descargadas";
    document.getElementById("installTopPct").textContent = "100%";
    document.getElementById("installTopFill").style.width = "100%";
    document.getElementById("installBottomPct").textContent = "100%";
    document.getElementById("installBottomFill").style.width = "100%";
    document.getElementById("btnInstallBack").textContent = "\u2190 Volver";
  } else {
    screen.classList.add("is-error");
    document.getElementById("installScreenTitle").textContent = "No se pudo instalar";
    document.getElementById("installTopLabel").textContent = payload.error || "Error al instalar";
    document.getElementById("btnInstallBack").textContent = "\u2190 Volver";
  }
}

document.getElementById("btnInstallBack").addEventListener("click", closeInstallScreen);

async function onGameCardClick(btn) {
  const instanceId = btn.dataset.instanceId;
  const profileId = btn.dataset.profileId;

  if (btn.dataset.running === "true") {
    btn.disabled = true;
    const res = await api().close_game(profileId);
    btn.disabled = false;
    if (!res.ok) toast(res.error || "No se pudo cerrar Minecraft", "error");
    return;
  }

  // Si ya se está instalando / actualizando / iniciando, el botón vuelve a abrir la pantalla.
  const installAct = state.installActivity[instanceId];
  if (installAct) { openInstallScreen(instanceId, installAct.mode); return; }
  if (profileId && state.launchActivity[profileId]) { openInstallScreen(instanceId, "launch", profileId); return; }

  if (btn.dataset.installed === "true" && btn.dataset.update !== "true") {
    if (!profileId) { toast("No se encontró la instancia instalada", "error"); return; }
    launchInstanceProfile(profileId, instanceId);
    return;
  }

  const isUpdate = btn.dataset.update === "true";
  const mode = isUpdate ? "update" : "install";
  state.instanceLaunch = { instanceId, mode: "install" };
  state.installActivity[instanceId] = { mode, top: 0, sub: 0 };
  openInstallScreen(instanceId, mode);

  const res = await api().install_instance(instanceId);
  if (!res.ok) {
    closeInstallScreen();
    toast(res.error || "No se pudo instalar la instancia", "error");
    state.instanceLaunch = null;
    delete state.installActivity[instanceId];
  }
}

async function launchInstanceProfile(profileId, instanceId = null) {
  state.instanceLaunch = { profileId, instanceId, mode: "launch" };
  state.launchActivity[profileId] = { pct: 0 };
  if (instanceId) openInstallScreen(instanceId, "launch", profileId);

  const res = await api().launch_profile(profileId);
  if (!res.ok) {
    closeInstallScreen();
    toast(res.error || "No se pudo lanzar", "error");
    state.instanceLaunch = null;
    delete state.launchActivity[profileId];
  }
}

function refreshRunningButtons() {
  loadGamesGrid();
  loadLibraryList();
}

// ---- Pantalla de Información (pantalla completa) ----
// Todo el contenido sale de archivos (.txt / Google Doc) de la carpeta de la instancia en Drive.
state.infoScreenInstanceId = null;

const INFO_ICONS = {
  version: '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>',
  mods: '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  experience: '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 17.5L3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4M19 21l2-2M14.5 6.5L18 3h3v3l-3.5 3.5M5 14l4 4M7 17l-4 4M3 19l2 2"/></svg>',
  status: '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/></svg>',
};

// Tarjeta "SERVIDOR": En línea / Sin conexión + jugadores. La IP viene de Drive (archivo "servidor").
const INFO_SERVER_ICON = '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01M11 7h6M11 17h6"/></svg>';

function addServerCard(grid, instanceId, address) {
  const card = document.createElement("div");
  card.className = "info-screen-card info-server-card";
  const ico = document.createElement("div");
  ico.className = "info-screen-card-icon";
  ico.innerHTML = INFO_SERVER_ICON;
  const body = document.createElement("div");
  body.className = "info-server-body";
  const label = document.createElement("div");
  label.className = "info-screen-card-label";
  label.textContent = "SERVIDOR";
  const row = document.createElement("div");
  row.className = "info-screen-card-value info-server-row";
  const dot = document.createElement("span");
  dot.className = "info-server-dot";
  const statusEl = document.createElement("span");
  statusEl.textContent = "Comprobando…";
  const players = document.createElement("span");
  players.className = "info-server-players";
  players.style.display = "none";
  row.append(dot, statusEl, players);
  body.append(label, row);
  card.append(ico, body);
  grid.appendChild(card);

  const refresh = async () => {
    let res = null;
    try { res = await api().get_server_status(address); } catch (e) { res = null; }
    if (state.infoScreenInstanceId !== instanceId) return;
    const online = !!(res && res.ok && res.online);
    card.classList.toggle("is-online", online);
    card.classList.toggle("is-offline", !online);
    statusEl.textContent = online ? "En línea" : "Sin conexión";
    if (online) {
      players.textContent = `${res.players}${res.max ? "/" + res.max : ""} jugadores`;
      players.style.display = "";
    } else {
      players.style.display = "none";
    }
  };
  refresh();
  clearInterval(state.infoServerTimer);
  state.infoServerTimer = setInterval(refresh, 30000);
}

// Descripción + imágenes. En el texto de Drive, una línea como  [img 1, 2]  coloca esas imágenes ahí
// (de 2 en 2). Las imágenes que no se nombren van al final.
const INFO_IMG_MARKER = /^\s*\[\s*(?:img|imagen|imagenes|imágenes|foto|fotos|galeria|galería)s?\s*:?\s*([\d\s,;\-y]+)\]\s*$/i;

function parseInfoImageRefs(spec) {
  const out = [];
  (spec.match(/\d+(?:\s*-\s*\d+)?/g) || []).forEach((tok) => {
    const parts = tok.split("-").map(t => parseInt(t, 10));
    if (parts.length === 2 && parts[1] >= parts[0] && parts[1] - parts[0] < 100) {
      for (let n = parts[0]; n <= parts[1]; n++) out.push(n);
    } else {
      out.push(parts[0]);
    }
  });
  return out;
}

function buildInfoGallery(images) {
  const box = document.createElement("div");
  box.className = "info-screen-gallery";
  images.forEach((g) => {
    const img = document.createElement("img");
    img.alt = "";
    img.addEventListener("click", () => { if (img.src) openImageViewer({ ...g, resolved: img.src }); });
    box.appendChild(img);
    resolveImage(g.url, g.fallback).then((ok) => { if (ok) img.src = ok; });
  });
  return box;
}

// Visor de imagen a pantalla completa. La pantalla de Información queda debajo, tal como estaba
// (misma posición del scroll), y "Volver" regresa a ella.
let imageViewerToken = 0;

function openImageViewer(g) {
  const viewer = document.getElementById("imageViewer");
  const img = document.getElementById("imageViewerImg");
  const token = ++imageViewerToken;
  img.src = g.resolved || g.url;         // primero la versión rápida...
  if (g.fallback && g.fallback !== g.url) {
    resolveImage(g.fallback).then((full) => {   // ...y cuando llega el original, se cambia por él
      if (full && token === imageViewerToken) img.src = full;
    });
  }
  viewer.style.display = "flex";
}

function closeImageViewer() {
  imageViewerToken++;
  document.getElementById("imageViewer").style.display = "none";
  document.getElementById("imageViewerImg").removeAttribute("src");
}

document.getElementById("btnImageBack").addEventListener("click", closeImageViewer);

function renderInfoContent(container, text, gallery) {
  container.innerHTML = "";
  const byN = new Map();
  (gallery || []).forEach((g) => { if (!byN.has(g.n)) byN.set(g.n, g); });
  const used = new Set();

  let buffer = [];
  const flushText = () => {
    const t = buffer.join("\n").trim();
    buffer = [];
    if (!t) return;
    const p = document.createElement("p");
    p.className = "info-screen-desc";
    p.textContent = t;
    container.appendChild(p);
  };

  (text || "").split(/\r?\n/).forEach((line) => {
    const m = line.match(INFO_IMG_MARKER);
    if (!m) { buffer.push(line); return; }
    const imgs = parseInfoImageRefs(m[1]).map(n => byN.get(n)).filter(Boolean);
    if (!imgs.length) return;
    flushText();
    imgs.forEach(g => used.add(g.n));
    container.appendChild(buildInfoGallery(imgs));
  });
  flushText();

  const rest = (gallery || []).filter(g => !used.has(g.n));
  if (rest.length) container.appendChild(buildInfoGallery(rest));

  if (!container.children.length) {
    const p = document.createElement("p");
    p.className = "info-screen-desc";
    p.textContent = "Sin información.";
    container.appendChild(p);
  }
}

function addInfoCard(grid, key, label, value, extraClass = "") {
  if (!value) return;
  const card = document.createElement("div");
  card.className = "info-screen-card " + extraClass;
  const ico = document.createElement("div");
  ico.className = "info-screen-card-icon";
  ico.innerHTML = INFO_ICONS[key];
  const body = document.createElement("div");
  const l = document.createElement("div");
  l.className = "info-screen-card-label";
  l.textContent = label;
  const v = document.createElement("div");
  v.className = "info-screen-card-value";
  v.textContent = value;
  body.append(l, v);
  card.append(ico, body);
  grid.appendChild(card);
}

async function openInfoModal(instanceId) {
  state.infoScreenInstanceId = instanceId;
  const gridRes = await api().list_instances();
  const inst = gridRes.ok ? gridRes.instances.find(i => i.id === instanceId) : null;
  const d = (inst && inst.details) || {};

  document.getElementById("infoScreenTitle").textContent = inst ? inst.name : "Información";

  // Icono: el archivo "icono" de Drive; si no existe o no carga, se usa la portada.
  const icon = document.getElementById("infoScreenIcon");
  icon.style.backgroundImage = "";
  if (inst && inst.icon) {
    resolveImage(inst.icon).then((ok) => {
      if (state.infoScreenInstanceId !== instanceId) return;
      if (ok) icon.style.backgroundImage = `url('${ok}')`;
      else if (inst.image) loadCardImage(icon, inst.image);
    });
  } else if (inst && inst.image) {
    loadCardImage(icon, inst.image);
  }

  // Fondo de toda la pantalla: el vídeo de la instancia (o su portada si no tiene vídeo).
  const bg = document.getElementById("infoScreenBg");
  bg.querySelectorAll(".cover-video").forEach(v => { v.pause(); v.remove(); });
  bg.style.backgroundImage = "";
  if (inst && inst.image) loadCardImage(bg, inst.image);
  if (inst && inst.video) attachCoverVideo(bg, inst.video, { fallback: inst.videoRemote });

  renderInfoContent(
    document.getElementById("infoScreenDesc"),
    (inst && (inst.info || inst.description)) || "",
    (inst && inst.gallery) || [],
  );

  const status = d.status || (!inst ? "" : !inst.installed ? "Sin instalar" : inst.updateAvailable ? "Actualización disponible" : "Lista para jugar");
  const grid = document.getElementById("infoScreenGrid");
  grid.innerHTML = "";
  const versionFallback = (inst && inst.installed && inst.version)
    ? `Minecraft ${inst.version}${inst.loader ? " · " + loaderLabel(inst.loader) : ""}` : "";
  addInfoCard(grid, "version", "VERSIÓN", d.version || versionFallback);
  addInfoCard(grid, "mods", "MODS", d.mods);
  addInfoCard(grid, "experience", "TIPO DE EXPERIENCIA", d.experience);
  addInfoCard(grid, "status", "ESTADO", status, (inst && inst.installed && !inst.updateAvailable && !d.status) ? "is-ok" : "");
  clearInterval(state.infoServerTimer);
  if (d.server) addServerCard(grid, instanceId, d.server);
  grid.style.display = grid.children.length ? "grid" : "none";

  const before = Array.isArray(d.before) ? d.before : [];
  const beforeBox = document.getElementById("infoScreenBefore");
  const list = document.getElementById("infoScreenBeforeList");
  list.innerHTML = "";
  before.forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    list.appendChild(li);
  });
  beforeBox.style.display = before.length ? "block" : "none";

  const newsBtn = document.getElementById("btnInfoNews");
  newsBtn.dataset.url = d.news || "";
  newsBtn.style.display = d.news ? "inline-flex" : "none";

  document.getElementById("infoScreen").style.display = "flex";
  document.querySelector("#infoScreen .info-screen-scroll").scrollTop = 0;
}

function closeInfoModal() {
  clearInterval(state.infoServerTimer);
  document.querySelectorAll("#infoScreenBg .cover-video").forEach(v => { v.pause(); v.remove(); });
  document.getElementById("infoScreen").style.display = "none";
  state.infoScreenInstanceId = null;
}

document.getElementById("btnInfoBack").addEventListener("click", closeInfoModal);
document.getElementById("btnInfoNews").addEventListener("click", (e) => {
  const url = e.currentTarget.dataset.url;
  if (!url) return;
  api().open_external_url(url).then((res) => {
    if (res && !res.ok) toast(res.error || "No se pudo abrir el enlace", "error");
  });
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (document.getElementById("imageViewer").style.display !== "none") closeImageViewer();
  else if (state.infoScreenInstanceId) closeInfoModal();
});

async function loadLibraryList(attempt = 1) {
  const el = document.getElementById("libraryList");
  let res;
  try {
    res = await api().list_library();
  } catch (e) {
    res = { ok: false, error: "No se pudo conectar con el launcher." };
  }

  const MAX_ATTEMPTS = 3;
  const RETRY_DELAY_MS = 1500;

  if (!res.ok || (res.fetchFailed && !res.instances.length)) {
    if (attempt < MAX_ATTEMPTS) {
      setTimeout(() => loadLibraryList(attempt + 1), RETRY_DELAY_MS);
      return;
    }
    el.innerHTML = `<div class="empty-hint">${escapeHtml(res.error || "No se pudo cargar la biblioteca. Comprueba tu conexión.")}<button class="btn-secondary retry-btn" id="retryLibraryList">Reintentar</button></div>`;
    document.getElementById("retryLibraryList").addEventListener("click", () => loadLibraryList());
    return;
  }
  if (!res.instances.length) {
    el.innerHTML = "";
    return;
  }

  el.innerHTML = res.instances.map(inst => {
    const launchAct = state.launchActivity[inst.profileId];
    const isRunning = state.runningProfileIds.has(inst.profileId);
    let label = "Jugar";
    let stopClass = "";
    if (launchAct) {
      label = "Iniciando…";
    } else if (isRunning) {
      label = "Cerrar Minecraft";
      stopClass = "btn-stop";
    }
    return `
    <div class="library-row" data-instance-id="${escapeHtml(inst.id)}" data-profile-id="${escapeHtml(inst.profileId)}">
      <div class="library-row-info">
        <div class="library-row-name">${escapeHtml(inst.name)}</div>
      </div>
      <button class="btn-secondary library-uninstall-btn" ${launchAct || isRunning ? "disabled" : ""}>Desinstalar</button>
      <button class="btn-secondary library-screenshots-btn">Screenshots</button>
      <button class="btn-primary library-play-btn ${stopClass}" data-running="${isRunning}" >${label}</button>
    </div>
  `;
  }).join("");

  el.querySelectorAll(".library-row").forEach(row => {
    const instanceId = row.dataset.instanceId;
    const profileId = row.dataset.profileId;
    const playBtn = row.querySelector(".library-play-btn");

    playBtn.addEventListener("click", async () => {
      if (playBtn.dataset.running === "true") {
        playBtn.disabled = true;
        const res = await api().close_game(profileId);
        playBtn.disabled = false;
        if (!res.ok) toast(res.error || "No se pudo cerrar Minecraft", "error");
        return;
      }
      if (state.launchActivity[profileId]) { openInstallScreen(instanceId, "launch", profileId); return; }
      launchInstanceProfile(profileId, instanceId);
    });

    row.querySelector(".library-screenshots-btn").addEventListener("click", async () => {
      const res = await api().open_screenshots_folder(profileId);
      if (!res.ok) toast(res.error || "No se pudo abrir la carpeta de screenshots", "error");
    });

    const name = row.querySelector(".library-row-name").textContent;
    row.querySelector(".library-uninstall-btn").addEventListener("click", () => askUninstall(instanceId, name));
  });
}

const confirmModal = document.getElementById("confirmModalBackdrop");
let pendingUninstallId = null;

function askUninstall(instanceId, name) {
  pendingUninstallId = instanceId;
  document.getElementById("confirmModalTitle").textContent = `¿Estás seguro que deseas desinstalar ${name}?`;
  const confirmText = document.getElementById("confirmModalText");
  confirmText.textContent = "";
  confirmText.style.display = "none";
  confirmModal.classList.add("open");
}

function closeConfirmModal() {
  confirmModal.classList.remove("open");
  pendingUninstallId = null;
}

document.getElementById("btnConfirmCancel").addEventListener("click", closeConfirmModal);
confirmModal.addEventListener("click", (e) => { if (e.target === confirmModal) closeConfirmModal(); });

document.getElementById("btnConfirmOk").addEventListener("click", async () => {
  if (!pendingUninstallId) return;
  const okBtn = document.getElementById("btnConfirmOk");
  okBtn.disabled = true;
  okBtn.textContent = "Desinstalando…";
  const res = await api().uninstall_instance(pendingUninstallId);
  okBtn.disabled = false;
  okBtn.textContent = "Desinstalar";
  closeConfirmModal();
  if (!res.ok) { toast(res.error || "No se pudo desinstalar", "error"); return; }
  toast("Instancia desinstalada", "success");
  loadLibraryList();
  loadGamesGrid();
});

const ramSettingSlider = document.getElementById("settingsRamSlider");
const downloadSettingSlider = document.getElementById("settingsDownloadSlider");
let settingsLoaded = false;
let settingsSaveTimer = null;

function paintSliderFill(slider) {
  const min = parseFloat(slider.min), max = parseFloat(slider.max), val = parseFloat(slider.value);
  slider.style.setProperty("--pct", (max > min ? ((val - min) / (max - min)) * 100 : 0) + "%");
}

function renderSettingsLabels() {
  paintSliderFill(ramSettingSlider);
  paintSliderFill(downloadSettingSlider);
  document.getElementById("settingsRamLabel").textContent = formatRam(parseInt(ramSettingSlider.value, 10));
  const dl = parseInt(downloadSettingSlider.value, 10);
  document.getElementById("settingsDownloadLabel").textContent = dl === 0 ? "Sin límite" : `${dl} MB/s`;
}

async function loadSettingsView() {
  const res = await api().get_settings();
  if (!res.ok) { toast(res.error || "No se pudieron cargar los ajustes", "error"); return; }
  ramSettingSlider.min = res.minRamMb;
  ramSettingSlider.max = res.maxRamMb;
  ramSettingSlider.value = res.ramMb;
  downloadSettingSlider.max = res.maxDownloadLimitMb;
  downloadSettingSlider.value = res.downloadLimitMb;
  renderSettingsLabels();
  settingsLoaded = true;
}

async function saveSettingsNow() {
  if (!settingsLoaded) return;
  const res = await api().save_settings(
    parseInt(ramSettingSlider.value, 10),
    parseInt(downloadSettingSlider.value, 10)
  );
  if (!res.ok) { toast(res.error || "No se pudieron guardar los ajustes", "error"); return; }
  ramSettingSlider.value = res.ramMb;
  downloadSettingSlider.value = res.downloadLimitMb;
  renderSettingsLabels();
  toast(res.gameRunning ? "Guardado — la memoria se aplica al reiniciar Minecraft" : "Ajustes guardados", "success");
}

[ramSettingSlider, downloadSettingSlider].forEach(slider => {
  slider.addEventListener("input", renderSettingsLabels);
  slider.addEventListener("change", () => {
    clearTimeout(settingsSaveTimer);
    settingsSaveTimer = setTimeout(saveSettingsNow, 150);
  });
});

document.getElementById("btnWinMinimize").addEventListener("click", () => api().minimize_window());
document.getElementById("btnWinMaximize").addEventListener("click", () => api().toggle_maximize_window());
document.getElementById("btnWinClose").addEventListener("click", () => api().close_window());

/* ---- Vestidor: cambiar skin y capa ---- */
let vestidorViewer = null;
let vestidorPending = null;    // { path, dataUrl, variant } mientras hay un archivo elegido sin confirmar
let vestidorLoaded = false;
let vestidorWardrobe = null;   // últimos datos del Vestidor (skin, modelo, capas) por si el visor 3D tarda en crearse

// Muestra una capa (o ninguna) en la vista previa 3D del Vestidor.
function setVestidorCapePreview(url) {
  if (!vestidorViewer) return;
  if (!url) { vestidorViewer.resetCape(); return; }
  try {
    const p = vestidorViewer.loadCape(url);
    if (p && p.catch) p.catch((e) => showVestidorError("No se pudo mostrar la capa (" + (e.message || "error") + ")."));
  } catch (e) {
    showVestidorError("No se pudo mostrar la capa (" + (e.message || "error") + ").");
  }
}

function applyVestidorWardrobeToViewer() {
  if (!vestidorViewer || !vestidorWardrobe) return;
  const res = vestidorWardrobe;
  vestidorViewer.loadSkin(res.skinUrl || DEFAULT_STEVE_SKIN, { model: skinview3dModel(res.variant) })
    .catch((e) => showVestidorError("No se pudo cargar tu skin (" + (e.message || "error") + ")."));
  const active = (res.capes || []).find(c => c.active);
  setVestidorCapePreview(active ? active.url : null);
}

function initVestidorIfNeeded() {
  ensureVestidorViewerCreated();
  loadVestidorWardrobe();
}

function ensureVestidorViewerCreated() {
  if (vestidorViewer) return;
  if (!window.skinview3d) {
    window.addEventListener("skinview3dready", ensureVestidorViewerCreated, { once: true });
    setTimeout(() => {
      if (!vestidorViewer && window.skinview3d) ensureVestidorViewerCreated();
      else if (!vestidorViewer) showVestidorError("No se pudo cargar la librería del visor 3D.");
    }, 2500);
    return;
  }
  const canvas = document.getElementById("vestidorCanvas");
  const wrap = canvas.parentElement;
  try {
    vestidorViewer = new skinview3d.SkinViewer({ canvas, width: wrap.clientWidth, height: wrap.clientHeight });
    vestidorViewer.autoRotate = true;
    vestidorViewer.controls.enableZoom = true;
    vestidorViewer.animation = new skinview3d.WalkingAnimation();
    applyVestidorWardrobeToViewer();
  } catch (e) {
    showVestidorError("Error al iniciar el visor 3D: " + e.message);
  }
}

function showVestidorError(message) {
  const hint = document.getElementById("vestidorHint");
  if (hint) { hint.textContent = message; hint.style.color = "var(--danger)"; }
}

function clearVestidorHint() {
  const hint = document.getElementById("vestidorHint");
  if (hint) { hint.textContent = "Arrastra para girar"; hint.style.color = ""; }
}

function skinview3dModel(variant) {
  return variant === "slim" ? "slim" : "default";
}

function setVestidorVariant(variant, fromPendingPreview) {
  document.querySelectorAll(".vestidor-variant-btn").forEach(b => b.classList.toggle("active", b.dataset.variant === variant));
  if (fromPendingPreview && vestidorPending) {
    vestidorPending.variant = variant;
    if (vestidorViewer) {
      vestidorViewer.loadSkin(vestidorPending.dataUrl, { model: skinview3dModel(variant) })
        .catch((e) => showVestidorError("No se pudo mostrar la vista previa (" + (e.message || "error") + ")."));
    }
  }
}

function loadVestidorWardrobe() {
  if (!window.pywebview) return;
  vestidorPending = null;
  document.getElementById("btnVestidorConfirm").disabled = true;
  window.pywebview.api.get_wardrobe().then((res) => {
    const notice = document.getElementById("vestidorOfflineNotice");
    const editor = document.getElementById("vestidorEditor");
    if (!res || !res.ok) {
      notice.style.display = "block";
      notice.textContent = (res && res.error) || "No se pudo cargar el Vestidor.";
      editor.style.display = "none";
      return;
    }
    if (res.offline) {
      notice.style.display = "block";
      editor.style.display = "none";
      return;
    }
    notice.style.display = "none";
    editor.style.display = "flex";
    vestidorLoaded = true;
    setVestidorVariant(res.variant === "slim" ? "slim" : "classic", false);
    clearVestidorHint();
    vestidorWardrobe = res;
    applyVestidorWardrobeToViewer();
    renderVestidorCapes(res.capes || []);
  }).catch((e) => {
    toast("No se pudo cargar el Vestidor: " + (e.message || "error"), "error");
  });
}

// La textura de una capa es una hoja de 64x32 casi toda transparente: el dibujo "de verdad"
// (el que se ve al llevarla puesta) ocupa solo el panel de 10x16 que empieza en (1,1). Mostrar
// la hoja entera con "cover" da un recorte sin sentido (justo lo que se veia mal); se recorta
// ese panel con un canvas en vez de usarlo como imagen de fondo.
const CAPE_PANEL = { sx: 1, sy: 1, sw: 10, sh: 16 };

function paintCapeThumbnail(canvas, url) {
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  const img = new Image();
  img.onload = () => {
    try {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, CAPE_PANEL.sx, CAPE_PANEL.sy, CAPE_PANEL.sw, CAPE_PANEL.sh, 0, 0, canvas.width, canvas.height);
    } catch (e) { /* una textura rara no debe romper el resto de la lista */ }
  };
  img.src = url;
}

function renderVestidorCapes(capes) {
  const box = document.getElementById("vestidorCapes");
  box.innerHTML = "";
  const none = document.createElement("div");
  none.className = "vestidor-cape vestidor-cape-empty" + (capes.every(c => !c.active) ? " active" : "");
  none.textContent = "Ninguna";
  none.title = "Sin capa";
  none.addEventListener("click", () => applyVestidorCape(null, none));
  box.appendChild(none);

  capes.forEach((cape) => {
    const el = document.createElement("div");
    el.className = "vestidor-cape" + (cape.active ? " active" : "");
    el.title = cape.alias || "Capa";
    el.addEventListener("click", () => applyVestidorCape(cape.id, el));
    const canvas = document.createElement("canvas");
    canvas.width = CAPE_PANEL.sw; canvas.height = CAPE_PANEL.sh;
    canvas.className = "vestidor-cape-canvas";
    el.appendChild(canvas);
    box.appendChild(el);
    paintCapeThumbnail(canvas, cape.url);
  });

  if (capes.length === 0) {
    const msg = document.createElement("p");
    msg.className = "vestidor-hint";
    msg.style.flexBasis = "100%";
    msg.textContent = "Tu cuenta todavía no tiene ninguna capa oficial de Minecraft.";
    box.appendChild(msg);
  }
}

function applyVestidorCape(capeId, el) {
  if (!window.pywebview) return;
  document.querySelectorAll(".vestidor-cape").forEach(c => c.classList.remove("active"));
  el.classList.add("active");
  const chosen = capeId ? ((vestidorWardrobe && vestidorWardrobe.capes) || []).find(c => c.id === capeId) : null;
  setVestidorCapePreview(chosen ? chosen.url : null);
  window.pywebview.api.set_active_cape(capeId).then((res) => {
    if (!res || !res.ok) {
      toast((res && res.error) || "No se pudo cambiar la capa", "error");
      loadVestidorWardrobe();
      return;
    }
    if (vestidorWardrobe && vestidorWardrobe.capes) {
      vestidorWardrobe.capes.forEach(c => { c.active = (c.id === capeId); });
    }
    if (state.account) state.account.capeUrl = chosen ? chosen.url : null;
    if (typeof skinViewer !== "undefined" && skinViewer) refreshSkinViewerTexture();
    toast("Capa actualizada.", "success");
  }).catch((e) => toast("No se pudo cambiar la capa: " + (e.message || "error"), "error"));
}

document.querySelectorAll(".vestidor-variant-btn").forEach((btn) => {
  btn.addEventListener("click", () => setVestidorVariant(btn.dataset.variant, true));
});

document.getElementById("btnPickSkin").addEventListener("click", () => {
  if (!window.pywebview) return;
  window.pywebview.api.pick_skin_file().then((res) => {
    if (!res || !res.ok) { toast((res && res.error) || "No se pudo abrir el selector de archivos", "error"); return; }
    if (!res.path) return;   // el jugador cerró el selector sin elegir nada
    return window.pywebview.api.read_skin_preview(res.path).then((prev) => {
      if (!prev || !prev.ok) { toast((prev && prev.error) || "El archivo no es una skin válida", "error"); return; }
      const activeVariant = document.querySelector(".vestidor-variant-btn.active")?.dataset.variant || "classic";
      vestidorPending = { path: res.path, dataUrl: prev.dataUrl, variant: activeVariant };
      document.getElementById("btnVestidorConfirm").disabled = false;
      clearVestidorHint();
      if (vestidorViewer) {
        vestidorViewer.loadSkin(prev.dataUrl, { model: skinview3dModel(activeVariant) })
          .catch((e) => showVestidorError("No se pudo mostrar la vista previa (" + (e.message || "error") + ")."));
      }
      toast("Vista previa lista. Pulsa Confirmar para guardarla.", "info");
    });
  }).catch((e) => toast("No se pudo elegir el archivo: " + (e.message || "error"), "error"));
});

document.getElementById("btnVestidorCancel").addEventListener("click", () => {
  loadVestidorWardrobe();
});

document.getElementById("btnVestidorConfirm").addEventListener("click", () => {
  if (!vestidorPending || !window.pywebview) return;
  const btn = document.getElementById("btnVestidorConfirm");
  btn.disabled = true;
  btn.textContent = "Guardando…";
  window.pywebview.api.apply_skin(vestidorPending.path, vestidorPending.variant).then((res) => {
    btn.textContent = "Confirmar";
    if (!res || !res.ok) {
      toast((res && res.error) || "No se pudo guardar la skin", "error");
      btn.disabled = false;
      return;
    }
    toast("¡Tu skin se actualizó! (puede tardar un poco en verse igual en otros sitios)", "success");
    if (state.account) {
      state.account.skinUrl = vestidorPending.dataUrl;
      renderTopnavFace(state.account.skinUrl);
      if (skinViewer) skinViewer.loadSkin(state.account.skinUrl).catch(() => {});
    }
    vestidorPending = null;
  }).catch((e) => {
    btn.textContent = "Confirmar";
    btn.disabled = false;
    toast("No se pudo guardar la skin: " + (e.message || "error"), "error");
  });
});
