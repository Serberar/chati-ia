// Chati web: atajos del agente y vista en vivo de una tarea.
const shortcutsModal = document.getElementById("shortcutsModal");
const shortcutsList = document.getElementById("shortcutsList");

function shortcutRow(sc) {
  const row = document.createElement("div");
  row.className = "sc-row";
  const name = document.createElement("input");
  name.placeholder = "Nombre del atajo (p.ej. Ordenar Descargas)";
  name.maxLength = 40;
  name.value = sc.name || "";
  name.className = "sc-name";
  const task = document.createElement("textarea");
  task.placeholder = "Que tiene que hacer el agente";
  task.value = sc.task || "";
  task.className = "sc-task";
  const foot = document.createElement("div");
  foot.className = "sc-foot";
  const lbl = document.createElement("label");
  const chk = document.createElement("input");
  chk.type = "checkbox";
  chk.className = "sc-potente";
  chk.checked = !!sc.potente;
  chk.style.width = "auto";
  lbl.append(chk, document.createTextNode("Usar el modelo potente"));
  const where = document.createElement("select");
  where.className = "sc-donde";
  where.title = "Dónde sale el atajo";
  for (const [value, text] of [["agente", "Modo Agente"], ["plan", "Código · solo mirar y proponer"],
                               ["build", "Código · hacer cambios"]]) {
    where.add(new Option(text, value, false, (sc.donde || "agente") === value));
  }
  const syncWhere = () => { lbl.style.display = where.value === "agente" ? "" : "none"; };
  where.addEventListener("change", syncWhere);
  syncWhere();
  const del = document.createElement("button");
  del.className = "sc-del";
  del.textContent = "Borrar";
  del.addEventListener("click", () => row.remove());
  foot.append(where, lbl, del);
  row.append(name, task, foot);
  return row;
}

function openShortcutsModal(extra) {
  shortcutsList.innerHTML = "";
  for (const sc of agentShortcuts) shortcutsList.appendChild(shortcutRow(sc));
  let focusRow = null;
  if (extra) {
    focusRow = shortcutRow(extra);
    shortcutsList.appendChild(focusRow);
  }
  setProfileMsg("shortcutsMsg", "");
  shortcutsModal.style.display = "block";
  if (focusRow) { focusRow.scrollIntoView({ block: "nearest" }); focusRow.querySelector(".sc-name").focus(); }
}

document.getElementById("addShortcutBtn").addEventListener("click", () => {
  const row = shortcutRow({});
  shortcutsList.appendChild(row);
  row.querySelector(".sc-name").focus();
});
const closeShortcuts = () => { shortcutsModal.style.display = "none"; };
document.getElementById("closeShortcutsBtn").addEventListener("click", closeShortcuts);
document.getElementById("cancelShortcutsBtn").addEventListener("click", closeShortcuts);
document.getElementById("saveShortcutsBtn").addEventListener("click", async () => {
  const list = [...shortcutsList.querySelectorAll(".sc-row")].map((r) => ({
    name: r.querySelector(".sc-name").value.trim(),
    task: r.querySelector(".sc-task").value.trim(),
    potente: r.querySelector(".sc-potente").checked,
    donde: r.querySelector(".sc-donde").value,
  })).filter((sc) => sc.name || sc.task);
  const resp = await sendJSON("/agent/shortcuts", { shortcuts: list }, "PUT");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) { setProfileMsg("shortcutsMsg", data.detail || "No se pudo guardar.", "error"); return; }
  agentShortcuts = data;
  renderAgentShortcuts();
  closeShortcuts();
});

let agentPendingFiles = [];
const agentAttachRow = document.getElementById("agentAttachRow");
const agentFilesInput = document.getElementById("agentFilesInput");

function renderAgentAttachments() {
  agentAttachRow.innerHTML = "";
  agentPendingFiles.forEach((f, i) => {
    const chip = document.createElement("span");
    chip.className = "aa-chip";
    const name = document.createElement("span");
    name.textContent = (f.type.startsWith("image/") ? "🖼️ " : "📄 ") + f.name;
    name.title = f.name;
    const rm = document.createElement("button");
    rm.textContent = "✕";
    rm.title = "Quitar";
    rm.addEventListener("click", () => { agentPendingFiles.splice(i, 1); renderAgentAttachments(); });
    chip.append(name, rm);
    agentAttachRow.appendChild(chip);
  });
}
agentFilesInput.addEventListener("change", () => {
  for (const f of agentFilesInput.files) {
    if (!agentPendingFiles.some((x) => x.name === f.name && x.size === f.size)) agentPendingFiles.push(f);
  }
  agentFilesInput.value = "";
  renderAgentAttachments();
  promptEl.focus();
});

async function uploadAgentAttachments(files) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const resp = await fetch("/agent/attachments", { method: "POST", body: form });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || "No se pudieron subir los adjuntos.");
  return data.files;
}

function resumeAgentView(view, reply) {

  if (view.codeMode === "plan" && reply.mode === "build") {
    view.codeMode = codeState.mode = "build";
    try { localStorage.setItem("ia_code_mode", "build"); } catch (e) {  }
    renderCodeBar();
  }
  view.followEl.style.display = "none";
  log.appendChild(view.row);
  view.row.scrollIntoView({ behavior: "smooth", block: "start" });

  view.stepsAtSend = (JSON.parse(view.lastSteps || "[]")).length + 1;
  view.sentAt = Date.now();
  view.startedAt = Date.now();
  followAgentView(view);
}

function lastFinishedAgentTask() {
  const cards = log.querySelectorAll(".agent-card");
  const view = cards.length ? agentViews[cards[cards.length - 1].dataset.session] : null;
  const d = view && view.data;
  return d && d.status === "idle" && !d.questions.length && !d.permissions.length ? view : null;
}

function lastRunningAgentTask() {
  const cards = log.querySelectorAll(".agent-card");
  const view = cards.length ? agentViews[cards[cards.length - 1].dataset.session] : null;
  const d = view && view.data;
  return d && d.status !== "idle" && !d.error && !d.questions.length && !d.permissions.length ? view : null;
}

async function startAgentTask(text, opts = {}) {
  askNotificationPermission();
  const files = agentPendingFiles;
  agentPendingFiles = [];
  renderAgentAttachments();
  const userBubble = addMessage("user");
  userBubble.textContent = text;
  if (files.length) {
    const list = document.createElement("div");
    list.className = "agent-attach-list";
    list.textContent = "📎 " + files.map((f) => f.name).join(", ");
    userBubble.appendChild(list);
  }

  const running = !files.length && !text.startsWith("/") && lastRunningAgentTask();
  if (running) {
    try {
      await agentPost(`/agent/tasks/${running.sessionId}/message`, { text, code_mode: running.codeMode || null });
      const note = addMessage("assistant", "agente");
      note.style.fontSize = "13px";
      note.textContent = "Se lo paso al agente: lo tendrá en cuenta en su siguiente paso.";
    } catch (err) {
      alert("No se pudo mandar: " + (err.message || err));
    }
    return;
  }
  sendBtn.disabled = true;
  let attachments = [];
  try {
    if (files.length) {
      const hasImages = files.some((f) => f.type.startsWith("image/"));
      prepareSkipped = false;
      showPrepare("loading", "Preparando los adjuntos…",
        hasImages ? "Copiando los archivos y describiendo las imagenes para el agente (unos segundos por imagen)."
                  : "Copiando los archivos para el agente.", "Ocultar");
      try {
        attachments = await uploadAgentAttachments(files);
      } finally {
        prepareOverlay.classList.remove("show");
      }
    }
    const body = { task: text, potente: !!opts.potente || agentPowerToggle.checked, attachments };
    if (MODES[currentMode].isCode) {
      if (!codeState.project) throw new Error("Primero abre un proyecto (📁 abajo a la izquierda).");
      Object.assign(body, { project: codeState.project.path, plan: (opts.codeMode || codeState.mode) === "plan",
                            rapido: codeState.fast, potente: false,
                            autonomo: document.getElementById("codeAuto").checked });
    }
    const previous = lastFinishedAgentTask();
    if (previous) body.continuar = previous.sessionId;
    const data = await agentPost("/agent/tasks", body);
    if (data.continued) {
      if (previous.codeMode) previous.codeMode = opts.codeMode || codeState.mode;
      resumeAgentView(previous, data);
    } else if (data.needs_choice) renderAgentChoice(data.task, data.reason, data.attachments || []);
    else if (data.mensaje) addMessage("assistant", "agente").textContent = data.mensaje;
    else openAgentView(data.session_id, Date.now(), MODES[currentMode].isCode ? (opts.codeMode || codeState.mode) : null);
  } catch (err) {
    const bubble = addMessage("assistant", "agente");
    bubble.className = "bubble error";
    bubble.textContent = String(err.message || err);
  } finally {
    sendBtn.disabled = false;
  }
}

function openAgentView(sessionId, startedAt, codeMode = null) {
  const existing = agentViews[sessionId];
  if (existing && document.body.contains(existing.card)) {
    existing.card.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  const bubble = addMessage("assistant", "agente");
  const card = document.createElement("div");
  card.className = "agent-card";
  card.innerHTML =
    '<div class="agent-head"><span class="agent-status">Conectando con el agente...</span>' +
    '<span class="agent-head-btns"><button class="agent-retry" style="display:none;" ' +
    'title="Corta la respuesta colgada y le pide seguir donde lo dejó">↻ Reintentar</button>' +
    '<button class="agent-stop" style="display:none;">Detener</button></span></div>' +
    '<div class="agent-todos" style="display:none;"></div>' +
    '<div class="agent-steps"></div><div class="agent-asks"></div>' +
    '<div class="agent-changes" style="display:none;"></div>' +

    '<div class="agent-follow" style="display:none;"></div>' +
    `<div class="agent-credit">${OPENCODE_CREDIT_HTML}</div>`;
  card.dataset.session = sessionId;
  bubble.appendChild(card);

  const view = {
    sessionId, card, startedAt: startedAt || null, timer: null, askCards: {}, lastSteps: null,
    openedAt: Date.now(),
    statusEl: card.querySelector(".agent-status"),
    stopBtn: card.querySelector(".agent-stop"),
    retryBtn: card.querySelector(".agent-retry"),
    stepsEl: card.querySelector(".agent-steps"),
    todosEl: card.querySelector(".agent-todos"), todosKey: null,
    asksEl: card.querySelector(".agent-asks"),
    followEl: card.querySelector(".agent-follow"),
    changesEl: card.querySelector(".agent-changes"), changesKey: null,
    saveScEl: null, task: "",
    stepsAtSend: 0, sentAt: null,
    codeMode,
    codeTask: Boolean(codeMode),
    row: bubble.parentElement,
  };
  if (codeMode) {

    const doIt = document.createElement("button");
    doIt.className = "do-it";
    doIt.textContent = "▶ Hacerlo";
    doIt.title = "Sigue en modo Construir: hace lo que ha propuesto (pidiendo permiso para cada cambio)";
    doIt.addEventListener("click", () => sendFollowUp("Adelante: hazlo tal como lo has propuesto.", "build"));
    view.followEl.appendChild(doIt);
    view.doItBtn = doIt;
  }
  {

    const where = codeMode ? "el proyecto" : "la carpeta";
    const undo = document.createElement("button");
    undo.className = "undo-it";
    undo.textContent = "↩ Deshacer";
    undo.title = `Deja ${where} como estaba antes del último encargo`;
    undo.style.display = "none";
    undo.addEventListener("click", async () => {
      if (!confirm(`¿Dejar ${where} como estaba antes del último encargo? Se pierden los cambios del agente desde entonces.`)) return;
      undo.disabled = true;
      try {
        const r = await agentPost(`/agent/tasks/${sessionId}/undo`);
        const note = document.createElement("div");
        note.className = "agent-undo-note";
        const files = r.archivos.length ? r.archivos.join(", ") : "no había cambios en los archivos";
        note.textContent = `↩ Deshecho «${r.encargo}»: ${files}.`;
        view.stepsEl.after(note);
        undo.style.display = r.quedan ? "" : "none";
      } catch (err) {
        alert("No se pudo deshacer: " + (err.message || err));
      } finally {
        undo.disabled = false;
      }
    });
    view.followEl.appendChild(undo);
    view.undoBtn = undo;
  }
  const sendFollowUp = async (text, mode) => {
    addMessage("user").textContent = text;
    view.codeMode = mode;
    try {
      resumeAgentView(view, await agentPost(`/agent/tasks/${sessionId}/message`, { text, code_mode: mode }));
    } catch (err) {
      alert("No se pudo mandar: " + (err.message || err));
    }
  };
  agentViews[sessionId] = view;
  view.retryBtn.addEventListener("click", async () => {
    view.retryBtn.disabled = true;
    try {
      await agentPost(`/agent/tasks/${sessionId}/retry`);
    } catch (err) {
      alert("No se pudo reintentar: " + (err.message || err));
    }
    view.retryBtn.disabled = false;
    followAgentView(view);
  });
  view.stopBtn.addEventListener("click", async () => {
    view.stopBtn.disabled = true;
    try { await agentPost(`/agent/tasks/${sessionId}/abort`); } catch (e) {  }
    followAgentView(view);
  });
  followAgentView(view);
}

async function pollAgentView(view) {
  clearTimeout(view.timer);
  if (!document.body.contains(view.card)) return;
  let data;
  try {
    const resp = await fetch(`/agent/tasks/${view.sessionId}`);
    data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
  } catch (err) {
    view.statusEl.className = "agent-status failed";
    view.statusEl.textContent = "Sin conexion con el agente - reintentando... (" + (err.message || err) + ")";
    view.timer = setTimeout(() => pollAgentView(view), AGENT_POLL_MS * 2);
    return;
  }
  renderAgentView(view, data);
  if (!agentDone(view, data)) view.timer = setTimeout(() => pollAgentView(view), AGENT_POLL_MS);
}

function agentDone(view, data) {
  const settled = data.status === "idle" &&
    (data.steps.length > view.stepsAtSend || data.error || Date.now() - (view.sentAt || view.openedAt) > 20000);

  const chatiWorking = (data.verificacion || "").endsWith("…");
  return settled && !chatiWorking && !data.questions.length && !data.permissions.length;
}

let liveAgentStreams = 0;

function followAgentView(view) {
  clearTimeout(view.timer);
  if (view.es) return;

  if (!window.EventSource || view.liveFailed || liveAgentStreams >= 2) { pollAgentView(view); return; }
  liveAgentStreams++;
  const es = new EventSource(`/agent/tasks/${view.sessionId}/live`);
  view.es = es;
  let closed = false;
  const stop = () => {
    es.close();
    if (!closed) { closed = true; liveAgentStreams--; }
    if (view.es === es) view.es = null;
  };
  es.onmessage = (e) => {
    if (!document.body.contains(view.card)) { stop(); return; }
    const data = JSON.parse(e.data);
    view.lastData = data;
    renderAgentView(view, data);
    if (agentDone(view, data)) { stop(); refreshBackgroundTasks(); }
  };
  const fallback = () => { stop(); view.liveFailed = true; pollAgentView(view); };
  es.addEventListener("end", fallback);
  es.onerror = fallback;

  if (!view.ticker) {
    view.ticker = setInterval(() => {
      if (!document.body.contains(view.card)) { clearInterval(view.ticker); return; }
      if (view.es && view.lastData && view.lastData.status !== "idle") renderAgentView(view, view.lastData);
    }, 1000);
  }
}

let titleBeforeNotice = null;

function noticeAgent(view, data) {
  const state = (data.questions.length || data.permissions.length) ? "ask"
    : (agentDone(view, data) ? "done" : (data.atascada_min ? "stuck" : "busy"));
  const before = view.noticeState;
  view.noticeState = state;
  if (!before || before === state || state === "busy" || !document.hidden) return;
  const what = (data.title || data.task || "Tarea del agente").slice(0, 80);
  const head = state === "ask" ? "✋ Chati necesita tu respuesta"
    : state === "stuck" ? "⚠ El agente parece atascado"
    : (data.error ? "⚠ La tarea se ha parado" : "✓ Tarea terminada");
  const detail = state === "ask" ? "Te pide permiso o te hace una pregunta: " + what
    : state === "stuck" ? `Lleva ${data.atascada_min} min sin avanzar: ${what}`
    : (data.verificacion || what);
  if (titleBeforeNotice === null) titleBeforeNotice = document.title;
  document.title = `${head} · Chati`;
  try {
    if (window.Notification && Notification.permission === "granted" && !pushOn()) {
      const n = new Notification(head, { body: detail, icon: "/static/icon-192.png", tag: "chati-" + view.sessionId });
      n.onclick = () => { window.focus(); n.close(); };
    }
  } catch (e) {  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && titleBeforeNotice !== null) { document.title = titleBeforeNotice; titleBeforeNotice = null; }
});

function askNotificationPermission() {
  try {
    if (window.Notification && Notification.permission === "default") Notification.requestPermission();
  } catch (e) {  }
}

function renderAgentView(view, data) {
  view.data = data;
  noticeAgent(view, data);
  const busy = data.status !== "idle";
  let cls = "agent-status", text;
  if (data.questions.length) { cls += " waiting"; text = "Esperando tu respuesta ↓"; }
  else if (data.permissions.length) { cls += " waiting"; text = "Necesita tu permiso para continuar ↓"; }
  else if (data.status === "retry") { text = "Reintentando: " + (data.retry_message || ""); }
  else if (busy && data.atascada_min) {
    cls += " failed";
    const looping = (data.modelo_ahora || {}).reintentos >= 2;
    text = looping
      ? `⚠ El modelo no llega a contestar y se reintenta una y otra vez (${data.atascada_min} min). Pulsa Reintentar o pídelo con el modelo rápido.`
      : `⚠ Lleva ${data.atascada_min} min sin avanzar: puede estar atascado. Pulsa Reintentar.`;
  }
  else if (busy && data.model_loading) {
    text = "Cargando el modelo del agente… un momento";
  }
  else if (busy && data.modelo_ahora) {
    text = doingText(data.modelo_ahora);
  }
  else if (busy && runningTool(data.steps)) {
    const t = runningTool(data.steps);
    text = `${AGENT_TOOL_LABELS[t.tool] || t.tool}: ${t.detail || t.title}`.replace(/: $/, "");
  }
  else if (busy) {

    if (view.startedAt) {
      const secs = Math.floor((Date.now() - view.startedAt) / 1000);
      const elapsed = secs >= 60 ? `${Math.floor(secs / 60)} min ${secs % 60}s` : `${secs}s`;
      text = `Trabajando... ${elapsed}` + (secs > 40 ? " (el modelo local tarda, es normal)" : "");
    } else {
      text = "Trabajando...";
    }
  }
  else if (data.error) { cls += " failed"; text = "Se detuvo con un error: " + data.error; }

  else if (data.steps.length <= view.stepsAtSend && Date.now() - (view.sentAt || view.openedAt) < 20000) {
    text = "Empezando…";
  }
  else if ((data.verificacion || "").endsWith("…")) { text = data.verificacion; }
  else if ((data.verificacion || "").startsWith("✗")) { cls += " failed"; text = data.verificacion; }
  else if (data.verificacion) { cls += " done"; text = "Terminado. " + data.verificacion; }
  else { cls += " done"; text = "Terminado ✓"; }
  view.statusEl.className = cls;
  view.statusEl.textContent = text;
  if (busy && data.prevision) view.statusEl.textContent += ` · ${data.prevision}`;
  view.stopBtn.style.display = busy ? "inline-block" : "none";
  view.retryBtn.style.display = busy && data.atascada_min ? "inline-block" : "none";
  view.stopBtn.disabled = false;
  renderAgentTodos(view, data.todos || []);
  if (view.undoBtn && !view.undoBtn.disabled) view.undoBtn.style.display = !busy && data.deshacer ? "" : "none";

  const stepsKey = JSON.stringify(data.steps);
  const streaming = data.streaming_text || "";
  if (stepsKey !== view.lastSteps || streaming !== view.lastStreaming) {
    view.lastSteps = stepsKey;
    view.lastStreaming = streaming;
    view.stepsEl.innerHTML = "";
    data.steps.forEach((step, i) => view.stepsEl.appendChild(buildAgentStep(step, view, i)));
    if (streaming) {

      const live = document.createElement("div");
      live.className = "agent-streaming";
      renderMarkdownInto(live, streaming, { highlight: false });
      view.stepsEl.appendChild(live);
    }
  }

  if (data.task) view.task = data.task;
  if (!busy && data.steps.length && view.task && !view.saveScEl) {
    view.saveScEl = document.createElement("button");
    view.saveScEl.className = "agent-save-sc";
    view.saveScEl.textContent = "☆ Guardar como atajo";
    view.saveScEl.title = "Para repetir esta tarea con un clic desde el modo Agente";
    view.saveScEl.addEventListener("click", async () => {
      if (!agentShortcuts.length) await loadAgentShortcuts();
      openShortcutsModal({ name: "", task: view.task, potente: false });
    });
    view.card.querySelector(".agent-credit").before(view.saveScEl);
  }

  renderAgentChanges(view, data, busy);

  const canFollow = !!view.codeMode && !busy && !data.questions.length && !data.permissions.length
    && data.steps.length > view.stepsAtSend;
  if (canFollow && view.followEl.style.display === "none") {
    view.followEl.style.display = "flex";
  } else if (!canFollow) {
    view.followEl.style.display = "none";
  }
  if (view.doItBtn) view.doItBtn.style.display = view.codeMode === "plan" ? "inline-block" : "none";

  const liveIds = new Set([...data.questions.map((q) => q.id), ...data.permissions.map((p) => p.id)]);
  for (const id of Object.keys(view.askCards)) {
    if (!liveIds.has(id)) { view.askCards[id].remove(); delete view.askCards[id]; }
  }
  for (const q of data.questions) {
    if (!view.askCards[q.id]) view.askCards[q.id] = buildQuestionCard(view, q);
  }
  for (const p of data.permissions) {
    if (!view.askCards[p.id]) view.askCards[p.id] = buildPermissionCard(view, p);
  }
  log.scrollTop = log.scrollHeight;
}

function buildAgentTerminal(step, view, idx) {
  const running = step.status === "running" || step.status === "pending";
  if (!step.output && !running) return null;
  const box = document.createElement("details");
  box.className = "agent-term";
  view.termOpen = view.termOpen || {};
  box.open = idx in view.termOpen ? view.termOpen[idx] : running;
  const summary = document.createElement("summary");
  if (running) summary.textContent = "Salida del comando (en directo)";
  else {
    summary.textContent = "Ver salida";
    if (step.exit !== null && step.exit !== undefined && step.exit !== 0) {
      const bad = document.createElement("span");
      bad.className = "exit-bad";
      bad.textContent = ` (terminó con código ${step.exit})`;
      summary.appendChild(bad);
    }
  }
  const pre = document.createElement("pre");
  pre.textContent = step.output || "(sin salida todavía)";
  box.append(summary, pre);
  summary.addEventListener("click", () => { view.termOpen[idx] = !box.open; });

  const key = "term" + idx;
  pre.addEventListener("scroll", () => {
    view[key] = pre.scrollTop + pre.clientHeight < pre.scrollHeight - 8;
  });
  requestAnimationFrame(() => { if (!view[key]) pre.scrollTop = pre.scrollHeight; });
  return box;
}

const TODO_MARKS = { completed: "✅", in_progress: "⏳", cancelled: "✗", pending: "☐" };

function renderAgentTodos(view, todos) {
  const key = JSON.stringify(todos);
  if (key === view.todosKey) return;
  view.todosKey = key;
  const el = view.todosEl;
  el.style.display = todos.length ? "block" : "none";
  el.innerHTML = "";
  if (!todos.length) return;
  const done = todos.filter((t) => t.status === "completed").length;
  const head = document.createElement("div");
  head.className = "todo-head";
  head.textContent = `Plan del agente · ${done} de ${todos.length}`;
  el.appendChild(head);
  todos.forEach((t) => {
    const row = document.createElement("div");
    row.className = "todo " + (t.status || "pending");
    row.textContent = `${TODO_MARKS[t.status] || "☐"} ${t.text}`;
    el.appendChild(row);
  });
}

const AGENT_CHANGE_TOOLS = new Set(["edit", "write", "patch", "bash"]);

function renderAgentChanges(view, data, busy) {
  const el = view.changesEl;
  const ch = data.changes || { files: 0, additions: 0, deletions: 0 };
  const touched = data.steps.some((s) => s.kind === "tool" && AGENT_CHANGE_TOOLS.has(s.tool) && s.status === "completed");
  const show = !busy && data.undoable && (ch.files > 0 || data.reverted || touched);
  const key = JSON.stringify([show, ch, data.reverted]);
  if (key === view.changesKey) return;
  view.changesKey = key;
  el.style.display = show ? "block" : "none";
  el.innerHTML = "";
  if (!show) return;

  const folder = (data.directory || "").split(/[\\/]/).filter(Boolean).pop() || "";
  const where = view.codeMode ? `el proyecto «${folder}»` : "su carpeta de trabajo (Documentos/Chati)";
  const whereShort = view.codeMode ? `el proyecto «${folder}»` : "su carpeta de trabajo";
  const bar = document.createElement("div");
  bar.className = "bar";
  const note = document.createElement("div");
  note.className = "note";
  const button = (label, onClick) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.addEventListener("click", () => onClick(b));
    return b;
  };
  const act = async (b, path, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    b.disabled = true;
    try {
      await agentPost(`/agent/tasks/${view.sessionId}/${path}`);
    } catch (err) {
      alert("No se pudo: " + (err.message || err));
      b.disabled = false;
      return;
    }
    view.changesKey = null;
    followAgentView(view);
  };

  if (data.reverted) {
    const msg = document.createElement("span");
    msg.textContent = "↩ Has deshecho los cambios de esta tarea.";
    bar.append(msg, button("Rehacer", (b) => act(b, "unrevert")));
    note.textContent = "Si continúas la tarea, lo deshecho ya no se podrá recuperar.";
  } else if (ch.files > 0) {
    const msg = document.createElement("span");

    const n = ch.files === 1 ? "1 archivo" : `${Number(ch.files) || 0} archivos`;
    msg.innerHTML = `📝 Ha cambiado <b>${n}</b> en <span class="where"></span> ` +
      `<span class="plus">+${Number(ch.additions) || 0}</span> <span class="minus">−${Number(ch.deletions) || 0}</span>`;
    msg.querySelector(".where").textContent = whereShort;
    const list = document.createElement("div");
    list.className = "diff-list";
    list.style.display = "none";
    const seeBtn = button("Ver cambios", async (b) => {
      if (list.style.display !== "none") { list.style.display = "none"; b.textContent = "Ver cambios"; return; }
      b.disabled = true;
      try {
        const resp = await fetch(`/agent/tasks/${view.sessionId}/changes`);
        const info = await resp.json();
        if (!resp.ok) throw new Error(info.detail || resp.status);
        renderAgentDiffs(list, info);
      } catch (err) {
        alert("No se pudieron cargar los cambios: " + (err.message || err));
        b.disabled = false;
        return;
      }
      b.disabled = false;
      list.style.display = "flex";
      b.textContent = "Ocultar cambios";
    });
    if (view.codeTask) {

      bar.append(msg, seeBtn);
      note.textContent = "Para volver atrás, «↩ Deshacer» deja el proyecto como estaba antes del último encargo.";
      el.append(bar, note, list);
      return;
    }
    bar.append(msg, seeBtn, button("Deshacer", (b) => act(b, "revert",
      `¿Deshacer lo que ha hecho esta tarea en ${where}?\n\n` +
      "Los archivos vuelven a como estaban antes. Podrás rehacerlo mientras no continúes la tarea.")));
    note.textContent = `Solo se puede deshacer lo hecho dentro de ${where}; lo de otras carpetas no.`;
    el.append(bar, note, list);
    return;
  } else {
    note.textContent = `No ha cambiado nada en ${where}: ` +
      "lo que haya hecho en otras carpetas no se puede deshacer desde aquí.";
  }
  el.append(bar, note);
}

function buildPatchPre(patch) {
  const pre = document.createElement("pre");
  for (const line of (patch || "").split("\n")) {
    if (/^(Index:|={5,}|--- |\+\+\+ )/.test(line) || line === "") continue;
    const div = document.createElement("div");
    div.textContent = line.replace(/\r$/, "");
    if (line.startsWith("@@")) div.className = "hunk";
    else if (line.startsWith("+")) div.className = "add";
    else if (line.startsWith("-")) div.className = "del";
    pre.appendChild(div);
  }
  return pre;
}

function renderAgentDiffs(list, info) {
  list.innerHTML = "";
  const turns = info.turns.filter((t) => t.files.length);
  const STATUS = { added: "nuevo", deleted: "borrado", modified: "modificado" };
  for (const turn of turns) {
    if (turns.length > 1) {
      const t = document.createElement("div");
      t.className = "turn";
      t.textContent = "«" + turn.text + "»";
      list.appendChild(t);
    }
    for (const f of turn.files) {
      const box = document.createElement("div");
      const head = document.createElement("div");
      head.className = "file-head";
      head.innerHTML = "";
      head.append(`${f.file} · ${STATUS[f.status] || f.status} `);
      const plus = document.createElement("span");
      plus.className = "plus";
      plus.textContent = `+${f.additions} `;
      const minus = document.createElement("span");
      minus.className = "minus";
      minus.textContent = `−${f.deletions}`;
      head.append(plus, minus);
      box.append(head, buildPatchPre(f.patch));
      list.appendChild(box);
    }
  }
  if (!list.children.length) list.textContent = "No hay cambios que mostrar.";
}

function buildAgentStep(step, view, idx) {
  if (step.kind === "user") {
    const div = document.createElement("div");
    div.className = "agent-user-step";
    div.textContent = step.text;
    return div;
  }
  if (step.kind === "text") {
    const div = document.createElement("div");
    renderMarkdownInto(div, step.text, { highlight: false });
    return div;
  }
  const row = document.createElement("div");
  row.className = "agent-tool" + (step.status === "error" ? " error" : "");
  const ic = document.createElement("span");
  ic.className = "ic";
  ic.textContent = AGENT_STATUS_ICON[step.status] || "•";
  const label = document.createElement("span");
  label.textContent = AGENT_TOOL_LABELS[step.tool] || step.tool;
  row.append(ic, label);
  const detail = step.detail || step.title;
  if (detail) {
    const code = document.createElement("code");
    code.textContent = detail;
    row.appendChild(code);
  }
  if (step.error) {
    const err = document.createElement("span");
    err.textContent = "- " + step.error;
    row.appendChild(err);
  }
  const term = step.tool === "bash" && view ? buildAgentTerminal(step, view, idx) : null;
  if (!term) return row;
  const wrap = document.createElement("div");
  wrap.append(row, term);
  return wrap;
}

function setAskDisabled(box, disabled) {
  box.querySelectorAll("button, input").forEach((el) => { el.disabled = disabled; });
}

function buildQuestionCard(view, request) {
  const box = document.createElement("div");
  box.className = "agent-ask";
  const answers = request.questions.map(() => []);
  const readyToSend = () => answers.every((a) => a.length > 0);

  const submit = async (rejected) => {
    setAskDisabled(box, true);
    try {
      if (rejected) await agentPost(`/agent/questions/${request.id}/reject`);
      else await agentPost(`/agent/questions/${request.id}`, { answers });
    } catch (err) {
      alert("No se pudo enviar la respuesta: " + (err.message || err));
      setAskDisabled(box, false);
      return;
    }
    followAgentView(view);
  };

  request.questions.forEach((q, idx) => {
    const qEl = document.createElement("div");
    qEl.className = "q";
    qEl.textContent = q.question;
    box.appendChild(qEl);
    const opts = document.createElement("div");
    opts.className = "opts";
    for (const opt of q.options || []) {
      const b = document.createElement("button");
      b.textContent = opt.label;
      if (opt.description) b.title = opt.description;
      b.addEventListener("click", () => {
        if (q.multiple) {
          const i = answers[idx].indexOf(opt.label);
          if (i >= 0) answers[idx].splice(i, 1); else answers[idx].push(opt.label);
          b.classList.toggle("primary", i < 0);
          return;
        }
        answers[idx] = [opt.label];
        opts.querySelectorAll("button").forEach((x) => x.classList.remove("primary"));
        b.classList.add("primary");
        if (request.questions.length === 1) submit(false);
      });
      opts.appendChild(b);
    }
    box.appendChild(opts);
    const row = document.createElement("div");
    row.className = "custom-row";
    const input = document.createElement("input");
    input.placeholder = (q.options || []).length ? "...o escribe otra respuesta" : "Escribe tu respuesta";
    input.addEventListener("input", () => { answers[idx] = input.value.trim() ? [input.value.trim()] : []; });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && readyToSend()) submit(false); });
    row.appendChild(input);
    box.appendChild(row);
  });

  const actions = document.createElement("div");
  actions.className = "opts";
  const send = document.createElement("button");
  send.className = "primary";
  send.textContent = "Responder";
  send.addEventListener("click", () => { if (readyToSend()) submit(false); });
  const skip = document.createElement("button");
  skip.className = "danger";
  skip.textContent = "No responder";
  skip.addEventListener("click", () => submit(true));
  actions.append(send, skip);
  box.appendChild(actions);

  view.asksEl.appendChild(box);
  return box;
}

function buildPermissionCard(view, perm) {
  const box = document.createElement("div");
  box.className = "agent-ask";
  const q = document.createElement("div");
  q.className = "q";
  q.textContent = "El agente quiere " + (AGENT_PERMISSION_LABELS[perm.permission] || perm.permission) + ":";
  box.appendChild(q);
  for (const pattern of perm.patterns || []) {
    const code = document.createElement("code");
    code.className = "pattern";
    code.textContent = pattern;
    box.appendChild(code);
  }

  if (Array.isArray(perm.afectados)) {
    const label = document.createElement("div");
    label.className = "q";
    label.textContent = perm.afectados.length
      ? `Afecta a estos archivos (${perm.afectados.length}):`
      : "No coincide con ningún archivo ahora mismo.";
    box.appendChild(label);
    if (perm.afectados.length) {
      const list = document.createElement("code");
      list.className = "pattern";
      list.style.whiteSpace = "pre-wrap";
      list.textContent = perm.afectados.join("\n");
      box.appendChild(list);
    }
  }

  if (perm.diff) {
    const label = document.createElement("div");
    label.className = "q";
    label.textContent = "Cambio propuesto:";
    const wrap = document.createElement("div");
    wrap.className = "diff-list perm-diff";
    wrap.appendChild(buildPatchPre(perm.diff));
    box.append(label, wrap);
  }
  const opts = document.createElement("div");
  opts.className = "opts";
  const choices = [["once", "Permitir", "primary"], ["always", "Permitir siempre", ""], ["reject", "Rechazar", "danger"]];

  if (!view.codeTask && perm.filepath && ["edit", "write", "patch"].includes(perm.permission)) {
    choices.splice(1, 0, ["carpeta", "Permitir todo en esta carpeta", ""]);
  }
  for (const [reply, label, cls] of choices) {
    const b = document.createElement("button");
    b.textContent = label;
    if (cls) b.className = cls;
    if (reply === "always") b.title = "No volvera a preguntar por esto mismo mientras el agente siga arrancado";
    if (reply === "carpeta") b.title = "En esta tarea, los siguientes cambios de archivos en esta carpeta se permiten solos (los datos tuyos siguen protegidos)";
    b.addEventListener("click", async () => {
      setAskDisabled(box, true);
      try {
        await agentPost(`/agent/permissions/${perm.id}`, { reply });
      } catch (err) {
        alert("No se pudo enviar la respuesta: " + (err.message || err));
        setAskDisabled(box, false);
        return;
      }
      followAgentView(view);
    });
    opts.appendChild(b);
  }
  box.appendChild(opts);
  view.asksEl.appendChild(box);
  return box;
}

