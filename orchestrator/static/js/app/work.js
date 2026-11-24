// Chati web: trabajos en segundo plano y preparacion de modelos al cambiar de modo.
async function fetchPendingWork() {
  try {
    const resp = await fetch("/work/pending");
    return resp.ok ? await resp.json() : null;
  } catch (e) { return null; }
}

function describePending(p) {
  const lines = p.agent_tasks.map((t) => ({ text: "🤖 Agente trabajando: " + (t.title || "tarea sin titulo") }));
  if (p.generations_running) lines.push({ text: "🖼️ Generando una imagen o video ahora mismo" });
  if (p.generations_queued) lines.push({ text: `⏳ ${p.generations_queued} generacion(es) en cola` });
  return lines;
}

let modeWaitTicket = 0;

const bgTasksWrap = document.getElementById("bgTasksWrap");
const bgTasksPanel = document.getElementById("bgTasksPanel");
document.getElementById("bgTasksBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  bgTasksPanel.classList.toggle("show");
});
document.addEventListener("click", (e) => { if (!bgTasksWrap.contains(e.target)) bgTasksPanel.classList.remove("show"); });

function bgRow(what, state, stateClass, actions) {
  const row = document.createElement("div");
  row.className = "bgp-row";
  const w = document.createElement("div");
  w.className = "what";
  w.textContent = what;
  const st = document.createElement("div");
  st.className = "state " + (stateClass || "");
  st.textContent = state;
  const acts = document.createElement("div");
  acts.className = "acts";
  for (const [label, cls, fn] of actions) {
    const b = document.createElement("button");
    b.textContent = label;
    if (cls) b.className = cls;
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      b.disabled = true;
      await fn();
      refreshBackgroundTasks();
    });
    acts.appendChild(b);
  }
  row.append(w, st, acts);
  return row;
}

let bgSeen = null;

function noticeBackground(p) {
  const working = new Set(p.agent_tasks.map((t) => t.session_id));
  const waiting = new Set((p.waiting_tasks || []).map((t) => t.session_id));
  const before = bgSeen;
  bgSeen = { working, waiting };
  if (!before || !document.hidden || !window.Notification || Notification.permission !== "granted" || pushOn()) return;
  try {
    for (const t of p.waiting_tasks || []) {
      if (!before.waiting.has(t.session_id)) {
        new Notification("✋ Chati necesita tu respuesta", { body: t.title || "Tarea del agente", tag: "chati-" + t.session_id,
                                                             icon: "/static/icon-192.png" });
      }
    }
    for (const sid of before.working) {
      if (!working.has(sid) && !waiting.has(sid)) {
        new Notification("✓ Tarea del agente terminada", { body: "Abre Chati para ver lo que ha hecho.", tag: "chati-" + sid,
                                                          icon: "/static/icon-192.png" });
      }
    }
  } catch (e) {  }
}

function doingText(now) {
  if (!now) return "";
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - now.desde));
  const clock = secs >= 60 ? `${Math.floor(secs / 60)} min ${String(secs % 60).padStart(2, "0")} s` : `${secs} s`;
  return `${now.texto} · ${clock}`;
}

async function refreshBackgroundTasks() {
  const p = await fetchPendingWork();
  if (!p) return;
  noticeBackground(p);
  const waiting = p.waiting_tasks || [];
  const working = p.agent_tasks.length + p.generations_running + p.generations_queued;
  const total = working + waiting.length;
  bgTasksWrap.classList.toggle("show", total > 0);
  if (!total) { bgTasksPanel.classList.remove("show"); return; }

  const btn = document.getElementById("bgTasksBtn");
  btn.classList.toggle("only-waiting", working === 0);
  const parts = [];
  if (working) parts.push(`${working} en marcha`);
  if (waiting.length) parts.push(`${waiting.length} esperando tu respuesta`);
  document.getElementById("bgTasksLabel").textContent = "Tareas: " + parts.join(" · ");

  const list = document.getElementById("bgTasksList");
  list.innerHTML = "";
  const stopAgent = (sid) => () => fetch(`/work/agent/${sid}/stop`, { method: "POST" });
  const viewAgent = (sid) => () => { bgTasksPanel.classList.remove("show"); openAgentView(sid); };
  for (const t of p.agent_tasks) {
    const state = t.atascada_min ? `⚠ Parece atascada (${t.atascada_min} min)`
      : doingText(t.modelo_ahora) || "Trabajando";
    list.appendChild(bgRow("🤖 " + (t.title || "Tarea del agente"), state, t.atascada_min ? "waiting" : "",
      [["Ver", "", viewAgent(t.session_id)], ["Detener", "stop", stopAgent(t.session_id)]]));
  }
  for (const t of waiting) {
    list.appendChild(bgRow("🤖 " + (t.title || "Tarea del agente"),
      t.reason === "permission" ? "Esperando tu permiso" : "Esperando tu respuesta", "waiting",
      [["Ver", "", viewAgent(t.session_id)], ["Cerrar tarea", "stop", stopAgent(t.session_id)]]));
  }

  const viewConversation = (sid) => () => { bgTasksPanel.classList.remove("show"); loadConversationIntoLog(sid); };
  for (const g of p.generations || []) {
    const actions = [["Detener", "stop", () => fetch(`/work/generation/${encodeURIComponent(g.id)}/stop`, { method: "POST" })]];
    if (g.session_id) actions.unshift(["Ver", "", viewConversation(g.session_id)]);
    const state = g.state !== "running" ? "En cola" : doingText(g.progreso) || "Empezando en ComfyUI";
    list.appendChild(bgRow("🖼️ Imagen o video", state, "", actions));
  }
}

function conflictingWork(p, target) {
  const agentTasks = target === "agente" ? [] : p.agent_tasks;
  const sameComfy = target === "image" || target === "video";
  const running = sameComfy ? 0 : p.generations_running;
  const queued = sameComfy ? 0 : p.generations_queued;
  if (!agentTasks.length && !running && !queued) return null;
  return { ...p, agent_tasks: agentTasks, generations_running: running, generations_queued: queued };
}

async function requestModeChange(target) {
  const previous = currentMode;
  if (target === previous) return;
  const raw = await fetchPendingWork();
  const pending = raw && conflictingWork(raw, target);
  if (!pending) { applyMode(target); return; }
  modeSelect.value = previous;

  const choice = await choiceModal("Hay tareas en marcha", describePending(pending).concat([
    { text: `Cambiar a "${modeLabel(target)}" carga otros modelos. ¿Que hacemos con ellas?` },
  ]), [
    ["cancel", "Cancelar"],
    ["background", "Dejar en segundo plano"],
    ["wait", "Esperar a que terminen"],
    ["stop", "Finalizarlas y cambiar", "danger-solid"],
  ]);

  if (choice === "stop") {
    await fetch("/work/stop", { method: "POST" });
    applyMode(target);
  } else if (choice === "wait") {
    waitThenApply(target);
  } else if (choice === "background") {
    const sure = await choiceModal("⚠️ El ordenador va a ir muy saturado", [
      { text: "Se ejecutaran dos modelos a la vez: lo que esta en marcha y los del modo nuevo.", warn: true },
      { text: "Todo ira bastante mas lento (y puede que tambien el resto del ordenador) hasta que terminen." },
    ], [["cancel", "Volver"], ["yes", "Continuar igualmente", "primary"]]);
    if (sure === "yes") applyMode(target);
  }
}

async function waitThenApply(target) {
  const ticket = ++modeWaitTicket;
  prepareSkipped = false;
  showPrepare("loading", "Esperando a que terminen las tareas en marcha…",
    `En cuanto acaben se cargara el modo "${modeLabel(target)}". Puedes seguir mirando mientras tanto.`,
    "Cancelar el cambio");
  while (ticket === modeWaitTicket) {
    await new Promise((r) => setTimeout(r, 3000));
    if (ticket !== modeWaitTicket || prepareSkipped) return;
    const pending = await fetchPendingWork();
    if (pending && !conflictingWork(pending, target)) {
      prepareOverlay.classList.remove("show");
      applyMode(target);
      return;
    }
  }
}

const prepareOverlay = document.getElementById("prepareOverlay");
let prepareTicket = 0;
let prepareSkipped = false;

function showPrepare(kind, title, sub, skipLabel) {
  document.getElementById("prepSpin").style.display = kind === "loading" ? "block" : "none";
  const icon = document.getElementById("prepIcon");
  icon.style.display = kind === "loading" ? "none" : "block";
  icon.textContent = kind === "ready" ? "✓" : "⚠";
  document.getElementById("prepTitle").textContent = title;
  document.getElementById("prepSub").textContent = sub;
  document.getElementById("prepSkip").textContent = skipLabel || (kind === "loading" ? "Seguir sin esperar" : "Cerrar");
  prepareOverlay.classList.add("show");
}
document.getElementById("prepSkip").addEventListener("click", () => {
  prepareSkipped = true;
  modeWaitTicket++;
  prepareOverlay.classList.remove("show");
});

async function prepareModelsForMode() {
  const ticket = ++prepareTicket;
  prepareSkipped = false;
  prepareOverlay.classList.remove("show");
  const body = { mode: currentMode };
  if (profileSelect.value) body.model_profile = profileSelect.value;
  if (currentMode === "agente") body.potente = agentPowerToggle.checked;
  if (currentMode === "codigo") {
    let fast = false;
    try { fast = localStorage.getItem("ia_code_fast") === "on"; } catch (e) {  }
    body.potente = !fast;
  }
  if (currentMode === "image" && modelSelect.value) body.image_model = modelSelect.value;
  if (currentMode === "video" && modelSelect.value) body.video_model = modelSelect.value;
  try {
    const resp = await sendJSON("/models/prepare", body);
    if (!resp.ok) return;
  } catch (e) { return; }

  const startedAt = Date.now();
  while (ticket === prepareTicket) {
    await new Promise((r) => setTimeout(r, 700));
    if (ticket !== prepareTicket) return;
    let st;
    try { st = await (await fetch("/models/prepare")).json(); } catch (e) { continue; }
    if (st.state === "preparing") {

      if (!prepareSkipped && Date.now() - startedAt > 900) {
        showPrepare("loading", "Cargando " + (st.label || "los modelos") + "…",
          "Por favor, espera. La primera vez puede tardar hasta un par de minutos; despues ya queda listo.");
      }
      continue;
    }
    if (st.state === "error") {
      if (!prepareSkipped) showPrepare("error", "No se pudo preparar " + (st.label || "el modo"), st.detail || "");
      return;
    }
    if (prepareOverlay.classList.contains("show")) {
      showPrepare("ready", "Listo", (st.label ? st.label.charAt(0).toUpperCase() + st.label.slice(1) : "El modelo") + " ya esta cargado.");
      setTimeout(() => { if (ticket === prepareTicket) prepareOverlay.classList.remove("show"); }, 1300);
    }
    return;
  }
}

profileSelect.addEventListener("change", () => { if (["chat", "texto", "voice"].includes(currentMode)) prepareModelsForMode(); });
modelSelect.addEventListener("change", () => { if (["image", "video"].includes(currentMode)) prepareModelsForMode(); });

function restoreModeAndPrepare() {
  let saved = null;
  try { saved = localStorage.getItem("ia_mode"); } catch (e) {  }
  if (saved && MODES[saved] && saved !== currentMode) {
    applyMode(saved);
  } else {
    prepareModelsForMode();
  }
}
setModeDesc(MODES.chat);
topbar.classList.add("show");
updateTopbarForMode(MODES.chat);
attachBtn.style.display = "flex";

