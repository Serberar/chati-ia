// Chati web: modos, conversacion actual, plan, markdown, adjuntos, documentos y selector de modelos.
const MODES = {
  chat: { desc: "Automático: Chati elige cómo responder", endpoint: "/chat/stream", showTopbar: true, allowAttach: true, isText: true, credits: ["ollama", "comfyui"] },
  texto: { desc: "Solo conversación", endpoint: "/chat/stream", agent: "text", showTopbar: true, allowAttach: true, isText: true, credits: ["ollama"] },
  image: { desc: "Crear imágenes", endpoint: "/chat/stream", agent: "image", showTopbar: true, modelsEndpoint: "/models/image", credits: ["comfyui"] },
  video: { desc: "Crear vídeos", endpoint: "/chat/stream", agent: "video", showTopbar: true, modelsEndpoint: "/models/video", credits: ["comfyui"] },
  agente: { desc: "Tareas con tus archivos", isAgent: true, allowAttach: true, credits: ["opencode", "ollama"] },
  codigo: { desc: "Programar en tus proyectos", isAgent: true, isCode: true, allowAttach: true, credits: ["opencode", "ollama"] },
  voice: { desc: "Habla y te responde con voz", isVoice: true, credits: ["whisper", "ollama", "piper"] },
};

const CREDIT_LINKS = {
  ollama: ["Ollama", "https://ollama.com"],
  comfyui: ["ComfyUI", "https://www.comfy.org"],
  opencode: ["OpenCode", "https://opencode.ai"],
  whisper: ["faster-whisper", "https://github.com/SYSTRAN/faster-whisper"],
  piper: ["Piper", "https://github.com/rhasspy/piper"],
};

function creditsHtml(keys) {
  const links = keys.map((k) => `<a href="${CREDIT_LINKS[k][1]}" target="_blank" rel="noopener">${CREDIT_LINKS[k][0]}</a>`);
  const list = links.length > 1 ? links.slice(0, -1).join(", ") + " y " + links[links.length - 1] : links[0];
  return `Funciona con ${list}`;
}

let currentMode = "chat";

function getSessionId() {
  return localStorage.getItem("ia_session_id") || null;
}
function setSessionId(sid) {
  if (sid) {
    const isNew = sid !== localStorage.getItem("ia_session_id");
    localStorage.setItem("ia_session_id", sid);
    if (isNew) loadConversations();
  }
}

const planPanel = document.getElementById("planPanel");
const ESTADO_ICONO = { pendiente: "", en_progreso: "●", hecho: "✓" };

async function refreshPlan() {
  const sid = getSessionId();
  if (!sid) return;
  let data;
  try {
    const resp = await fetch(`/plan/${sid}`);
    data = await resp.json();
  } catch (e) { return; }

  const pasos = data.pasos || [];
  if (!pasos.length) { planPanel.style.display = "none"; return; }

  planPanel.innerHTML = '<div class="plan-title">Plan de la tarea</div>' + pasos.map((p) => `
    <div class="plan-step ${esc(p.estado)}">
      <span class="dot">${ESTADO_ICONO[p.estado] || ""}</span>
      <span class="texto">${esc(p.texto)}</span>
    </div>
  `).join("");
  planPanel.style.display = "block";
}

marked.setOptions({ breaks: true, gfm: true });

function safeHtml(html) {
  return DOMPurify.sanitize(html, { FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select"],
                                    FORBID_ATTR: ["style"] });
}

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.getAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

function renderMarkdownInto(container, text, { highlight } = { highlight: true }) {
  container.innerHTML = safeHtml(marked.parse(text || ""));
  container.classList.add("markdown");
  if (!highlight) return;
  container.querySelectorAll("pre code").forEach((block) => {
    hljs.highlightElement(block);
    const pre = block.parentElement;
    const btn = document.createElement("button");
    btn.className = "copy-code-btn";
    btn.textContent = "Copiar";
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(block.textContent).then(() => {
        btn.textContent = "Copiado";
        setTimeout(() => { btn.textContent = "Copiar"; }, 1200);
      });
    });
    pre.appendChild(btn);
  });
}

const log = document.getElementById("log");
const emptyState = document.getElementById("emptyState");
const promptEl = document.getElementById("prompt");
const sendBtn = document.getElementById("send");
const cancelBtn = document.getElementById("cancelBtn");
const modeDesc = document.getElementById("modeDesc");
const micBtn = document.getElementById("micBtn");
const topbar = document.getElementById("topbar");
const profileSelectLabel = document.getElementById("profileSelectLabel");
const profileSelect = document.getElementById("profileSelect");
const verifyToggleLabel = document.getElementById("verifyToggleLabel");
const modelStatusText = document.getElementById("modelStatusText");
const attachBtn = document.getElementById("attachBtn");
const visionImageInput = document.getElementById("visionImageInput");
const attachPreviewRow = document.getElementById("attachPreviewRow");
const attachPreviewImg = document.getElementById("attachPreviewImg");
const removeAttachBtn = document.getElementById("removeAttachBtn");
const verifyToggle = document.getElementById("verifyToggle");

function hideEmptyState() { if (emptyState) emptyState.style.display = "none"; }

verifyToggle.checked = localStorage.getItem("ia_verify") === "on";
verifyToggle.addEventListener("change", () => {
  localStorage.setItem("ia_verify", verifyToggle.checked ? "on" : "off");
});

async function loadProfiles() {
  try {
    const resp = await fetch("/models/profiles");
    const data = await resp.json();
    profileSelect.innerHTML = "";
    (data.profiles || []).forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.label;
      profileSelect.appendChild(opt);
    });
    const saved = localStorage.getItem("ia_model_profile");
    profileSelect.value = (saved && data.profiles.some(p => p.id === saved)) ? saved : (data.default || "");
  } catch (err) {  }
}
profileSelect.addEventListener("change", () => {
  localStorage.setItem("ia_model_profile", profileSelect.value);
});

async function refreshModelStatus() {
  try {
    const resp = await fetch("/models/status");
    const data = await resp.json();
    const names = (data.models || []).map(m => m.name);
    modelStatusText.textContent = names.length ? names.join(", ") : "sin modelos cargados";
  } catch (err) {
    modelStatusText.textContent = "sin datos";
  }
}

let visionImageBase64 = null;

const attachMenu = document.getElementById("attachMenu");
const docInput = document.getElementById("docInput");

attachBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  if (MODES[currentMode].isAgent) { document.getElementById("agentFilesInput").click(); return; }

  const inChat = !!MODES[currentMode].isText;
  document.getElementById("attachDocItem").style.display = inChat ? "flex" : "none";
  document.getElementById("attachImageHint").textContent = "Comentarla o describirla";
  attachMenu.classList.toggle("show");
});
document.addEventListener("click", (e) => { if (!attachMenu.contains(e.target)) attachMenu.classList.remove("show"); });
document.getElementById("attachImageItem").addEventListener("click", () => {
  attachMenu.classList.remove("show");
  visionImageInput.click();
});
document.getElementById("attachDocItem").addEventListener("click", () => {
  attachMenu.classList.remove("show");
  docInput.click();
});

const convDocsWrap = document.getElementById("convDocsWrap");
const convDocsPanel = document.getElementById("convDocsPanel");
const convDocsList = document.getElementById("convDocsList");
document.getElementById("convDocsBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  convDocsPanel.classList.toggle("show");
});
document.addEventListener("click", (e) => { if (!convDocsWrap.contains(e.target)) convDocsPanel.classList.remove("show"); });

function addDocCard(name, { uploading = false, error = null } = {}) {
  hideEmptyState();
  const wrap = document.createElement("div");
  wrap.className = "msg user doc";
  const card = document.createElement("div");
  card.className = "doc-card" + (error ? " error" : "");
  const ic = document.createElement("span");
  ic.className = "ic";
  ic.textContent = "📄";
  const text = document.createElement("div");
  const nameEl = document.createElement("div");
  nameEl.className = "name";
  nameEl.textContent = name;
  const sub = document.createElement("div");
  sub.className = "sub";
  sub.textContent = uploading ? "Subiendo..." : error ? error : "Documento adjuntado";
  text.append(nameEl, sub);
  card.append(ic, text);
  wrap.appendChild(card);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return { wrap, sub, card };
}

async function refreshDocChips() {
  convDocsList.innerHTML = "";
  convDocsWrap.classList.remove("show");
  const sid = getSessionId();
  if (!sid) return;
  let docs = [];
  try {
    const resp = await fetch(`/sessions/${sid}/docs`);
    if (resp.ok) docs = await resp.json();
  } catch (e) { return; }
  document.getElementById("convDocsCount").textContent = `${docs.length}`;
  convDocsWrap.classList.toggle("show", docs.length > 0);
  if (!docs.length) convDocsPanel.classList.remove("show");
  for (const d of docs) {
    const row = document.createElement("div");
    row.className = "cdp-row";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = "📄 " + d.name;
    name.title = d.name;
    const keep = document.createElement("button");
    keep.textContent = "Guardar";
    keep.title = "Guardar tambien en Mis documentos, para usarlo en cualquier conversacion";
    keep.addEventListener("click", async (e) => {
      e.stopPropagation();
      keep.disabled = true;
      const resp = await fetch(`/sessions/${sid}/docs/${encodeURIComponent(d.name)}/keep`, { method: "POST" });
      if (!resp.ok) { keep.disabled = false; alert("No se pudo guardar en Mis documentos."); return; }
      const ok = document.createElement("span");
      ok.className = "kept";
      ok.textContent = "en Mis documentos ✓";
      keep.replaceWith(ok);
    });
    const rm = document.createElement("button");
    rm.className = "rm";
    rm.textContent = "Quitar";
    rm.title = "Chati deja de tenerlo en cuenta en esta conversacion";
    rm.addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`/sessions/${sid}/docs/${encodeURIComponent(d.name)}`, { method: "DELETE" });
      refreshDocChips();
    });
    row.append(name, keep, rm);
    convDocsList.appendChild(row);
  }
}

docInput.addEventListener("change", async () => {
  const files = [...docInput.files];
  docInput.value = "";
  for (const file of files) {
    const card = addDocCard(file.name, { uploading: true });
    const form = new FormData();
    form.append("file", file);
    if (getSessionId()) form.append("session_id", getSessionId());
    let data = {};
    let ok = false;
    try {
      const resp = await fetch("/sessions/docs", { method: "POST", body: form });
      data = await resp.json();
      ok = resp.ok;
    } catch (e) { data = { detail: "error de conexion" }; }
    if (ok) {
      setSessionId(data.session_id);
      localStorage.setItem("ia_session_id", data.session_id);
      card.sub.textContent = "Documento adjuntado";
    } else {
      card.card.classList.add("error");
      card.sub.textContent = data.detail || "No se pudo adjuntar";
    }
  }
  await refreshDocChips();
  promptEl.focus();
});
visionImageInput.addEventListener("change", () => {
  const file = visionImageInput.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    visionImageBase64 = reader.result.split(",")[1];
    attachPreviewImg.src = reader.result;
    attachPreviewRow.classList.add("show");
  };
  reader.readAsDataURL(file);
  document.getElementById("attachLabel").textContent = "imagen adjunta";
});
removeAttachBtn.addEventListener("click", () => {
  visionImageBase64 = null;
  visionImageInput.value = "";
  attachPreviewRow.classList.remove("show");
});

if (isLoggedIn()) {
  refreshDocChips();
  loadCvStatus();
  loadProfiles();
  refreshModelStatus();
}
setInterval(() => { if (isLoggedIn()) refreshModelStatus(); }, 20000);

const modeSelect = document.getElementById("modeSelect");
const modelSelectLabel = document.getElementById("modelSelectLabel");
const modelSelect = document.getElementById("modelSelect");
const modelsCache = {};

async function loadModelsFor(mode) {
  const m = MODES[mode];
  if (!m || !m.modelsEndpoint) {
    return;
  }
  if (!modelsCache[mode]) {
    try {
      const resp = await fetch(m.modelsEndpoint);
      const data = await resp.json();
      modelsCache[mode] = data.models || [];
    } catch (err) {
      modelsCache[mode] = [];
    }
  }
  modelSelect.innerHTML = "";
  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = "Automatico";
  modelSelect.appendChild(autoOpt);
  for (const model of modelsCache[mode]) {
    const opt = document.createElement("option");
    opt.value = model.id;
    opt.textContent = `${model.architecture_label} - ${model.label}`;
    modelSelect.appendChild(opt);
  }
  if (modelsCache[mode].length === 0) {
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.disabled = true;
    noneOpt.textContent = "No hay modelos instalados";
    modelSelect.appendChild(noneOpt);
  }
}

function setModeDesc(m) {

  if (m.showTopbar) modelSelect.after(modeDesc);
  else document.getElementById("inputFooter").prepend(modeDesc);
  modeDesc.textContent = m.desc;
  if (m.credits) {
    const credit = document.createElement("span");
    credit.className = "mode-credit";
    credit.innerHTML = " · " + creditsHtml(m.credits);
    modeDesc.appendChild(credit);
  }
}

function updateTopbarForMode(m) {
  const showModelPicker = !!m.modelsEndpoint;
  profileSelectLabel.style.display = showModelPicker ? "none" : "inline";
  profileSelect.style.display = showModelPicker ? "none" : "inline-block";
  verifyToggleLabel.style.display = showModelPicker ? "none" : "inline-flex";
  modelSelectLabel.style.display = showModelPicker ? "inline" : "none";
  modelSelect.style.display = showModelPicker ? "inline-block" : "none";
}

let isAdminUser = false;

modeSelect.addEventListener("change", () => requestModeChange(modeSelect.value));

const agentPowerToggle = document.getElementById("agentPowerToggle");
try { agentPowerToggle.checked = localStorage.getItem("ia_agent_potente") === "on"; } catch (e) {  }
agentPowerToggle.addEventListener("change", () => {
  try { localStorage.setItem("ia_agent_potente", agentPowerToggle.checked ? "on" : "off"); } catch (e) {  }
  if (currentMode === "agente") prepareModelsForMode();
});

function applyMode(mode) {
  modeSelect.value = mode;
  currentMode = mode;
  const m = MODES[currentMode];
  const plainAgent = !!m.isAgent && !m.isCode;
  document.getElementById("agentPowerLabel").classList.toggle("show", plainAgent);
  agentShortcutsRow.classList.toggle("show", plainAgent);

  document.getElementById("agentAttachRow").style.display = m.isAgent ? "" : "none";
  document.getElementById("codeBar").classList.toggle("show", !!m.isCode);
  if (plainAgent) loadAgentShortcuts();
  setModeDesc(m);
  promptEl.style.display = m.isVoice ? "none" : "block";
  sendBtn.style.display = m.isVoice ? "none" : "block";
  micBtn.style.display = m.isVoice ? "block" : "none";
  attachBtn.style.display = m.allowAttach ? "flex" : "none";
  topbar.classList.toggle("show", !!m.showTopbar);
  updateTopbarForMode(m);
  if (!m.allowAttach) {
    visionImageBase64 = null;
    visionImageInput.value = "";
    attachPreviewRow.classList.remove("show");
  }
  loadModelsFor(currentMode);
  if (plainAgent) showAgentTaskList();

  if (m.isCode) setTimeout(initCodeMode, 0);
  if (currentMode === "video") showVideoTips();
  try { localStorage.setItem("ia_mode", currentMode); } catch (e) {  }
  prepareModelsForMode();
}

function showVideoTips() {
  if (log.querySelector(".video-tips")) return;
  const bubble = addMessage("assistant", "vídeo");
  bubble.classList.add("video-tips");
  bubble.style.fontSize = "13px";
  bubble.innerHTML = "🎬 <b>Cómo pedir vídeos</b><br>" +
    "· Di cuánto dura: «un perro en la playa, 8 segundos». Si no lo dices, 4 s. Más segundos, más espera (los largos se hacen por tramos).<br>" +
    "· ¿Te gusta? «hazlo de 10 segundos» lo repite igual pero más largo.<br>" +
    "· Con una foto (adjunta o ya en la conversación): «haz un vídeo de esto» la anima tal cual; " +
    "«haznos paseando por la playa» crea la escena con vuestras caras y la anima.<br>" +
    "· Para uno nuevo sin la foto: «un vídeo nuevo de…» o «desde cero».<br>" +
    "· «Una película de…» la hace por escenas seguidas (3-6) y te enseña el guion. Tarda bastante más. " +
    "Si una escena no te gusta: «rehaz la escena 2» (o «rehaz la escena 2 pero de noche»).<br>" +
    "· «Esta noche:» y un vídeo por línea: los hace de madrugada y te avisa al móvil.";
}

function modeLabel(mode) {
  const opt = modeSelect.querySelector(`option[value="${mode}"]`);
  return opt ? opt.textContent : mode;
}

function choiceModal(title, lines, buttons) {
  const modal = document.getElementById("pendingWorkModal");
  document.getElementById("pendingWorkTitle").textContent = title;
  const list = document.getElementById("pendingWorkList");
  list.innerHTML = "";
  for (const line of lines) {
    const li = document.createElement("div");
    li.className = line.warn ? "pw-line warn" : "pw-line";
    li.textContent = line.text;
    list.appendChild(li);
  }
  const box = document.getElementById("pendingWorkButtons");
  box.innerHTML = "";
  modal.style.display = "block";
  return new Promise((resolve) => {
    const done = (value) => { modal.style.display = "none"; modal.onclick = null; resolve(value); };
    for (const [value, label, cls] of buttons) {
      const btn = document.createElement("button");
      btn.className = "dc-btn " + (cls || "");
      btn.textContent = label;
      btn.onclick = () => done(value);
      box.appendChild(btn);
    }
    modal.onclick = (e) => { if (e.target === modal) done("cancel"); };
  });
}

