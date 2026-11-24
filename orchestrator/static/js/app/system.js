// Chati web: creditos, errores, dispositivos, equipos, actualizaciones, autoarranque y avisos push.
const CREDITS = [
  ["Ollama", "https://ollama.com", "Ejecuta los modelos de texto, programacion y vision."],
  ["Qwen (Alibaba)", "https://qwenlm.github.io", "Los modelos de texto, del agente y de vision (qwen2.5, qwen3, qwen3-coder, qwen2.5-vl)."],
  ["ComfyUI", "https://www.comfy.org", "Genera las imagenes y los videos."],
  ["FLUX.1 (Black Forest Labs)", "https://blackforestlabs.ai", "Modelo de imagen por defecto."],
  ["Stable Diffusion XL (Stability AI)", "https://stability.ai", "Otro modelo de imagen."],
  ["LTX-Video (Lightricks)", "https://github.com/Lightricks/LTX-Video", "Modelo de video."],
  ["OpenCode", "https://opencode.ai", "El agente que trabaja con tus archivos."],
  ["faster-whisper", "https://github.com/SYSTRAN/faster-whisper", "Entiende lo que dices en el modo Voz."],
  ["Piper", "https://github.com/rhasspy/piper", "La voz con la que responde Chati."],
  ["Playwright", "https://playwright.dev", "Maneja el navegador del buscador de empleo."],
  ["ChromaDB", "https://www.trychroma.com", "Guarda la memoria y tus documentos para buscarlos."],
  ["FastAPI", "https://fastapi.tiangolo.com", "El servidor interno de Chati."],
  ["pywebview", "https://pywebview.flowrl.com", "La ventana de la aplicacion."],
];
const creditsModal = document.getElementById("creditsModal");
document.getElementById("optCreditsBtn").addEventListener("click", () => {
  optionsModal.style.display = "none";
  const list = document.getElementById("creditsList");
  list.innerHTML = "";
  for (const [name, url, what] of CREDITS) {
    const row = document.createElement("div");
    const a = document.createElement("a");
    a.href = webUrl(url);
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = name;
    const w = document.createElement("div");
    w.className = "what";
    w.textContent = what;
    row.append(a, w);
    list.appendChild(row);
  }
  creditsModal.style.display = "block";
});
document.getElementById("closeCreditsBtn").addEventListener("click", () => { creditsModal.style.display = "none"; });
creditsModal.addEventListener("click", (e) => { if (e.target === creditsModal) creditsModal.style.display = "none"; });

const errorsModal = document.getElementById("errorsModal");

async function loadErrors() {
  const list = document.getElementById("errorsList");
  list.textContent = "Cargando…";
  let data;
  try { data = await (await fetch("/admin/errors")).json(); } catch (e) { list.textContent = "No se ha podido leer."; return; }
  list.textContent = "";
  const entries = data.entries || [];
  if (!entries.length) { list.textContent = "Sin errores registrados."; return; }
  for (const text of entries) {
    const row = document.createElement("div");
    row.className = "err" + (/ (ERROR|CRITICAL) /.test(text) ? " error" : "");
    row.textContent = text;
    list.appendChild(row);
  }
}

document.getElementById("optErrorsBtn").addEventListener("click", () => {
  optionsModal.style.display = "none";
  errorsModal.style.display = "block";
  loadErrors();
});
document.getElementById("errorsRefreshBtn").addEventListener("click", loadErrors);
document.getElementById("closeErrorsBtn").addEventListener("click", () => { errorsModal.style.display = "none"; });
errorsModal.addEventListener("click", (e) => { if (e.target === errorsModal) errorsModal.style.display = "none"; });

const devicesModal = document.getElementById("devicesModal");
let pairTimer = null;

function stopPairing() {
  if (pairTimer) clearInterval(pairTimer);
  pairTimer = null;
  document.getElementById("pairBox").style.display = "none";
}

async function loadDevices() {
  const list = document.getElementById("devicesList");
  list.textContent = "";
  let items = [];
  try { items = await (await fetch("/devices")).json(); } catch (e) {  }
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "personas-intro";
    empty.textContent = "Ninguno todavía.";
    list.appendChild(empty);
    return;
  }
  for (const d of items) {
    const row = document.createElement("div");
    row.className = "device-row";
    const info = document.createElement("div");
    info.className = "dname";
    const name = document.createElement("div");
    name.textContent = d.name + (d.current ? " (este)" : "");
    const meta = document.createElement("div");
    meta.className = "dmeta";
    meta.textContent = "Vinculado " + formatRelativeTime(new Date(d.created * 1000).toISOString()) + " · usado " + formatRelativeTime(new Date(d.last_seen * 1000).toISOString());
    info.append(name, meta);
    const btn = document.createElement("button");
    btn.className = "profile-link danger";
    btn.textContent = "Desconectar";
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Desconectar "${d.name}"? Para volver a usarlo habrá que vincularlo otra vez.`)) return;
      await fetch(`/devices/${encodeURIComponent(d.id)}`, { method: "DELETE" });
      loadDevices();
    });
    row.append(info, btn);
    list.appendChild(row);
  }
}

const computersModal = document.getElementById("computersModal");

async function fetchComputers() {
  try { return await (await fetch("/computers")).json(); } catch (e) { return []; }
}

async function loadComputers() {
  const list = document.getElementById("computersList");
  list.textContent = "Comprobando…";
  const items = await fetchComputers();
  list.innerHTML = "";
  if (!items.length) { list.textContent = "No se ve Tailscale en este ordenador."; return; }
  for (const pc of items) {
    const row = document.createElement("div");
    row.className = "pc-row";
    const dot = document.createElement("span");
    dot.className = "pc-dot" + (pc.chati ? " on" : "");
    const name = document.createElement("span");
    name.className = "pc-name";
    name.textContent = pc.name;
    const state = document.createElement("span");
    state.className = "pc-state";
    state.textContent = pc.this ? "Estás aquí" : (pc.chati ? "Encendido" : (pc.online ? "Encendido, sin Chati" : "Apagado"));
    row.append(dot, name, state);
    if (!pc.this && pc.chati) {
      const open = document.createElement("a");
      open.className = "personas-primary";
      open.href = pc.url;
      open.textContent = "Abrir";
      row.appendChild(open);
    }
    list.appendChild(row);
  }
}

document.getElementById("optComputersBtn").addEventListener("click", () => {
  optionsModal.style.display = "none";
  computersModal.style.display = "block";
  loadComputers();
});
document.getElementById("closeComputersBtn").addEventListener("click", () => { computersModal.style.display = "none"; });

async function showCurrentComputer() {
  const here = (await fetchComputers()).find((pc) => pc.this);
  const name = here ? here.name : location.hostname.split(".")[0];
  if (!name || name === "127" || name === "localhost") return;
  document.getElementById("pcNameBadge").textContent = "🖥 " + name;
  document.title = `Chati IA · ${name}`;
}

async function announceOtherComputers() {
  try { if (sessionStorage.getItem("chati_other_pc_seen")) return; } catch (e) {  }
  const others = (await fetchComputers()).filter((pc) => !pc.this && pc.chati);
  if (!others.length) return;
  const banner = document.getElementById("otherComputerBanner");
  const here = (await fetchComputers()).find((pc) => pc.this);
  document.getElementById("otherComputerText").textContent =
    `Estás en ${here ? here.name : "este ordenador"}. También está encendida la Chati de ${others.map((pc) => pc.name).join(" y ")}.`;
  const open = document.getElementById("otherComputerOpen");
  open.href = others[0].url;
  open.textContent = others.length === 1 ? `Ir a ${others[0].name}` : "Ver ordenadores";
  if (others.length > 1) open.addEventListener("click", (e) => { e.preventDefault(); computersModal.style.display = "block"; loadComputers(); });
  banner.style.display = "flex";
  const dismiss = () => { banner.style.display = "none"; try { sessionStorage.setItem("chati_other_pc_seen", "1"); } catch (e) {  } };
  document.getElementById("otherComputerClose").addEventListener("click", dismiss);
  open.addEventListener("click", dismiss);
}

async function fetchAppUpdate(force) {
  try {
    const resp = await fetch(`/app/update${force ? "?force=true" : ""}`);
    return resp.ok ? await resp.json() : null;
  } catch (e) { return null; }
}

function showAppUpdateBanner(info) {

  const here = ["127.0.0.1", "localhost"].includes(location.hostname);
  document.getElementById("appUpdateText").textContent =
    `Hay una versión nueva de Chati: la ${info.latest} (tienes la ${info.current}).` +
    (here ? "" : " Actualízala desde el ordenador.");
  document.getElementById("appUpdateInstall").style.display = here ? "" : "none";
  document.getElementById("appUpdateBanner").style.display = "flex";
}

async function installAppUpdate() {
  if (!confirm("Se va a descargar e instalar la versión nueva. Windows pedirá permiso de administrador y Chati se cerrará un par de minutos; luego se vuelve a abrir sola. ¿Continuar?")) return;
  const text = document.getElementById("appUpdateText");
  const btn = document.getElementById("appUpdateInstall");
  btn.style.display = "none";
  text.textContent = "Descargando la versión nueva...";
  const resp = await fetch("/app/update", { method: "POST" }).catch(() => null);
  const data = resp ? await resp.json().catch(() => ({})) : {};
  if (!resp || !resp.ok) {
    text.textContent = data.detail || "No se pudo actualizar.";
    btn.style.display = "";
    return;
  }
  text.textContent = `Instalando la ${data.version}: acepta el aviso de Windows. Chati se volverá a abrir sola.`;
}

async function setupAppUpdates() {
  const checkNow = async () => {
    const info = await fetchAppUpdate(true);
    if (!info) { alert("No se pudo comprobar si hay actualizaciones."); return; }
    if (info.error && (info.falta_clave || info.error.includes("clave"))) {
      const token = prompt(`${info.error}\n\nPega un token de GitHub de solo lectura (github.com > Settings > Developer settings > Fine-grained tokens, repo Serberar/chati, permiso Contents: Read-only):`);
      if (!token) return;
      const resp = await sendJSON("/app/github_token", { token });
      if (!resp.ok) { alert((await resp.json()).detail || "No se pudo guardar."); return; }
      return checkNow();
    }
    if (info.error) { alert(`No se pudo comprobar si hay actualizaciones: ${info.error}`); return; }
    if (!info.available) { alert(`Chati está al día (versión ${info.current}).`); return; }
    optionsModal.style.display = "none";
    showAppUpdateBanner(info);
  };
  for (const id of ["optAppUpdateBtn", "footerUpdateLink"]) {
    const el = document.getElementById(id);
    el.style.display = "";
    el.addEventListener("click", checkNow);
  }
  document.getElementById("appUpdateInstall").addEventListener("click", installAppUpdate);
  document.getElementById("appUpdateClose").addEventListener("click", () => {
    document.getElementById("appUpdateBanner").style.display = "none";
  });
  const info = await fetchAppUpdate(false);
  if (!info) return;
  document.getElementById("optAppUpdateText").textContent = `Buscar actualizaciones de Chati (v${info.current})`;
  if (info.available) showAppUpdateBanner(info);
}

async function setupAutostart() {
  const row = document.getElementById("optAutostartBtn");
  const text = document.getElementById("optAutostartText");
  let enabled;
  const show = () => { text.textContent = `Arrancar con Windows: ${enabled ? "sí" : "no"}`; };
  try {
    const resp = await fetch("/app/autostart");
    if (!resp.ok) return;
    enabled = (await resp.json()).enabled;
  } catch (e) { return; }
  show();
  row.style.display = "";
  row.addEventListener("click", async () => {
    const question = enabled
      ? "Chati dejará de arrancar al encender el ordenador: no ocupará memoria hasta que la abras (tardará un poco más en estar lista). ¿Continuar?"
      : "Chati arrancará al encender el ordenador y estará lista al abrirla, pero ocupará memoria aunque no la uses. ¿Continuar?";
    if (!confirm(question)) return;
    const resp = await sendJSON("/app/autostart", { enabled: !enabled }).catch(() => null);
    const data = resp ? await resp.json().catch(() => ({})) : {};
    if (!resp || !resp.ok) { alert(data.detail || "No se pudo cambiar."); return; }
    enabled = data.enabled;
    show();
  });
}

function pushOn() {
  try { return localStorage.getItem("ia_push") === "on"; } catch (e) { return false; }
}

function pushB64ToBytes(text) {
  const b64 = (text + "=".repeat((4 - (text.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function pushDeviceName() {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Android/.test(ua)) return "Android";
  return /Windows/.test(ua) ? "Ordenador (Windows)" : "Ordenador";
}

function renderPushRow() {
  document.getElementById("optPushText").textContent =
    pushOn() ? "Avisos en este dispositivo: activados ✓" : "Avisos en este dispositivo";
}

async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !window.Notification) {
    const iphone = /iPhone|iPad/.test(navigator.userAgent);
    alert(iphone
      ? "En el iPhone los avisos solo funcionan con Chati instalado: en Safari pulsa Compartir → «Añadir a pantalla de inicio», abre Chati desde ese icono y vuelve aquí."
      : "Este navegador no admite avisos.");
    return;
  }
  if (await Notification.requestPermission() !== "granted") {
    alert("Sin permiso no te puedo avisar. Puedes darlo en los ajustes del navegador (o del iPhone: Ajustes → Notificaciones → Chati).");
    return;
  }
  await syncPushSubscription();
  try { localStorage.setItem("ia_push", "on"); } catch (e) {  }
  await agentPost("/push/test");
}

function pushBytesToB64(buf) {
  let bin = "";
  new Uint8Array(buf).forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function syncPushSubscription() {
  const reg = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;
  const { key } = await (await fetch("/push/key")).json();
  let sub = await reg.pushManager.getSubscription();
  const used = sub && sub.options && sub.options.applicationServerKey;
  if (used && pushBytesToB64(used) !== key) {
    await sub.unsubscribe();
    sub = null;
  }
  sub = sub || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: pushB64ToBytes(key) });
  await agentPost("/push/subscribe", { subscription: sub.toJSON(), device: pushDeviceName() });
}

async function repairPush() {
  if (!pushOn() || !("serviceWorker" in navigator) || !window.Notification) return;
  if (Notification.permission !== "granted") {
    try { localStorage.removeItem("ia_push"); } catch (e) {  }
    renderPushRow();
    return;
  }
  try { await syncPushSubscription(); } catch (e) {  }
}

async function disablePush() {
  try {
    const reg = await navigator.serviceWorker.getRegistration("/");
    const sub = reg && await reg.pushManager.getSubscription();
    if (sub) {
      await agentPost("/push/unsubscribe", { subscription: { endpoint: sub.endpoint } });
      await sub.unsubscribe();
    }
  } finally {
    try { localStorage.removeItem("ia_push"); } catch (e) {  }
  }
}

function takeLauncherPush() {
  const m = location.hash.match(/[#&]push=([A-Za-z0-9_-]+)/);
  if (!m) return;
  try { sessionStorage.setItem("chati_launcher_push", m[1]); } catch (e) {  }
  history.replaceState(null, "", location.pathname + location.search);
}
takeLauncherPush();

async function adoptLauncherPush() {
  let raw = null;
  try { raw = sessionStorage.getItem("chati_launcher_push"); } catch (e) { return; }
  if (!raw) return;
  try {
    const sub = JSON.parse(new TextDecoder().decode(pushB64ToBytes(raw)));
    await agentPost("/push/subscribe", { subscription: sub, device: pushDeviceName() + " (lanzador)" });
    sessionStorage.removeItem("chati_launcher_push");
    localStorage.setItem("ia_push", "on");
    renderPushRow();
  } catch (e) {  }
}

document.getElementById("optPushBtn").addEventListener("click", async () => {
  try {
    if (!pushOn()) {
      await enablePush();
    } else if (confirm("Los avisos están activados en este dispositivo.\n\nAceptar: mandar un aviso de prueba\nCancelar: dejarlo como está")) {
      await agentPost("/push/test");
    } else if (confirm("¿Desactivar los avisos en este dispositivo?")) {
      await disablePush();
    }
  } catch (err) {
    alert("No se pudieron activar los avisos: " + (err.message || err));
  }
  renderPushRow();
});
renderPushRow();

document.getElementById("optDevicesBtn").addEventListener("click", () => {
  optionsModal.style.display = "none";
  stopPairing();
  document.getElementById("devicesMsg").textContent = "";
  devicesModal.style.display = "block";
  loadDevices();
});

document.getElementById("pairStartBtn").addEventListener("click", async () => {
  const msgEl = document.getElementById("devicesMsg");
  msgEl.textContent = "";
  let data;
  try {
    const resp = await fetch("/devices/pair", { method: "POST" });
    data = await resp.json();
    if (!resp.ok) { msgEl.textContent = data.detail || "No se ha podido."; return; }
  } catch (e) { msgEl.textContent = "No se ha podido."; return; }
  stopPairing();
  document.getElementById("pairQr").src = data.qr;
  document.getElementById("pairUrl").textContent = data.url;
  document.getElementById("pairCode").textContent = data.code;
  document.getElementById("pairBox").style.display = "";
  const ends = Date.now() + data.expires_in * 1000;
  const timerEl = document.getElementById("pairTimer");
  const before = new Set();
  try { (await (await fetch("/devices")).json()).forEach((d) => before.add(d.id)); } catch (e) {  }
  const tick = async () => {
    const left = Math.round((ends - Date.now()) / 1000);
    if (left <= 0) { stopPairing(); msgEl.textContent = "El código ha caducado. Pide otro."; return; }
    timerEl.textContent = `Válido ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    if (left % 3 === 0) {
      try {
        const now = await (await fetch("/devices")).json();
        if (now.some((d) => !before.has(d.id))) { stopPairing(); msgEl.textContent = "¡Vinculado!"; loadDevices(); }
      } catch (e) {  }
    }
  };
  tick();
  pairTimer = setInterval(tick, 1000);
});

document.getElementById("closeDevicesBtn").addEventListener("click", () => { stopPairing(); devicesModal.style.display = "none"; });
devicesModal.addEventListener("click", (e) => { if (e.target === devicesModal) { stopPairing(); devicesModal.style.display = "none"; } });

