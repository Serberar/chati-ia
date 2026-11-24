// Chati web: lista de conversaciones y cargar sus mensajes.
const newChatBtn = document.getElementById("newChatBtn");
const convList = document.getElementById("convList");

function formatRelativeTime(iso) {
  if (!iso) return "";

  let normalized = iso.includes("T") ? iso : iso.replace(" ", "T");
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(normalized)) normalized += "Z";
  const then = new Date(normalized);
  if (isNaN(then)) return iso;
  const diffMin = Math.round((Date.now() - then.getTime()) / 60000);
  if (diffMin < 1) return "ahora mismo";
  if (diffMin < 60) return `hace ${diffMin} min`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `hace ${diffH} h`;
  const diffD = Math.round(diffH / 24);
  if (diffD < 7) return `hace ${diffD} d`;
  return then.toLocaleDateString();
}

async function loadConversations() {
  if (getSessionRole() === "guest") return;
  let sessions;
  try {
    const resp = await fetch("/sessions");
    sessions = await resp.json();
  } catch (err) { return; }

  convList.innerHTML = "";
  const clearAll = document.getElementById("clearAllConvBtn");
  clearAll.style.display = sessions.length ? "" : "none";
  clearAll.dataset.count = sessions.length;
  if (!sessions.length) {
    convList.innerHTML = '<div id="convEmpty">Sin conversaciones todavia. Escribe algo para empezar una.</div>';
    return;
  }
  const currentSid = getSessionId();
  sessions.forEach((s) => {
    const row = document.createElement("div");
    row.className = "conv-row" + (s.session_id === currentSid ? " current" : "");
    const defaultTitle = `Conversacion · ${s.messages} mensaje${s.messages === 1 ? "" : "s"}`;
    const titleEl = document.createElement("div");
    titleEl.className = "conv-title";
    titleEl.textContent = s.title || defaultTitle;
    const metaEl = document.createElement("div");
    metaEl.className = "conv-meta";
    metaEl.textContent = formatRelativeTime(s.last_used);
    const renameBtn = document.createElement("button");
    renameBtn.className = "conv-rename";
    renameBtn.title = "Renombrar";
    renameBtn.textContent = "✎";
    const delBtn = document.createElement("button");
    delBtn.className = "conv-del";
    delBtn.title = "Borrar conversacion";
    delBtn.textContent = "×";
    row.appendChild(titleEl);
    row.appendChild(metaEl);
    row.appendChild(renameBtn);
    row.appendChild(delBtn);

    row.addEventListener("click", (e) => {
      if (e.target.closest(".conv-del") || e.target.closest(".conv-rename")) return;
      loadConversationIntoLog(s.session_id);
    });

    renameBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const input = document.createElement("input");
      input.type = "text";
      input.value = s.title || "";
      input.placeholder = defaultTitle;
      input.maxLength = 80;
      input.className = "conv-rename-input";
      row.replaceChild(input, titleEl);
      input.focus();
      input.select();

      const finishRename = async (save) => {
        const newTitle = input.value.trim();
        if (save && newTitle && newTitle !== s.title) {
          const form = new FormData();
          form.append("title", newTitle);
          await fetch(`/sessions/${s.session_id}/title`, { method: "PUT", body: form });
        }
        await loadConversations();
      };
      input.addEventListener("keydown", (ke) => {
        if (ke.key === "Enter") finishRename(true);
        if (ke.key === "Escape") finishRename(false);
      });
      input.addEventListener("blur", () => finishRename(true));
    });

    delBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!(await askDeleteConversation(s.session_id))) return;
      await fetch(`/sessions/${s.session_id}`, { method: "DELETE" });
      if (s.session_id === currentSid) {
        localStorage.removeItem("ia_session_id");
        startNewConversation(false);
      }
      await loadConversations();
    });
    convList.appendChild(row);
  });
}

const clearAllConvBtn = document.getElementById("clearAllConvBtn");
clearAllConvBtn.addEventListener("click", async () => {
  const n = Number(clearAllConvBtn.dataset.count || 0);
  const ok = await askConfirm(
    `¿Borrar ${n === 1 ? "la conversacion" : `las ${n} conversaciones`}?\n\n` +
    "Se borran tambien sus fotos, ediciones y documentos adjuntos. " +
    "Lo guardado en \"Mis documentos\" no se toca.\n\nNo se puede deshacer.");
  if (!ok) return;
  clearAllConvBtn.disabled = true;
  try {
    const resp = await fetch("/sessions", { method: "DELETE" });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      notify(data.detail || "No se pudieron borrar las conversaciones.");
      return;
    }
    localStorage.removeItem("ia_session_id");
    startNewConversation(false);
    await loadConversations();
  } finally {
    clearAllConvBtn.disabled = false;
  }
});

async function askDeleteConversation(sessionId) {
  let docs = [];
  try {
    const resp = await fetch(`/sessions/${sessionId}/docs`);
    if (resp.ok) docs = await resp.json();
  } catch (e) { silenced(e); }
  const modal = document.getElementById("deleteConvModal");
  const keepBtn = document.getElementById("deleteConvKeep");
  const list = document.getElementById("deleteConvDocs");
  list.innerHTML = "";
  if (docs.length) {
    document.getElementById("deleteConvText").textContent =
      `Esta conversacion tiene ${docs.length === 1 ? "un documento adjunto" : docs.length + " documentos adjuntos"}. ` +
      (docs.length === 1
        ? "Puedes guardarlo en Mis documentos para que Chati lo siga teniendo en cuenta en cualquier conversacion, o borrarlo junto con ella."
        : "Puedes guardarlos en Mis documentos para que Chati los siga teniendo en cuenta en cualquier conversacion, o borrarlos junto con ella.");
    for (const d of docs) {
      const li = document.createElement("li");
      li.textContent = d.name;
      list.appendChild(li);
    }
  } else {
    document.getElementById("deleteConvText").textContent = "¿Borrar toda esta conversacion? No se puede deshacer.";
  }
  keepBtn.style.display = docs.length ? "inline-block" : "none";
  keepBtn.textContent = docs.length === 1 ? "Guardar documento y borrar" : "Guardar documentos y borrar";
  document.getElementById("deleteConvAll").textContent = docs.length ? "Borrar todo" : "Borrar";
  modal.style.display = "block";

  const choice = await new Promise((resolve) => {
    const done = (value) => {
      modal.style.display = "none";
      ["deleteConvCancel", "deleteConvAll", "deleteConvKeep"].forEach((id) => { document.getElementById(id).onclick = null; });
      modal.onclick = null;
      resolve(value);
    };
    document.getElementById("deleteConvCancel").onclick = () => done("cancel");
    document.getElementById("deleteConvAll").onclick = () => done("all");
    keepBtn.onclick = () => done("keep");
    modal.onclick = (e) => { if (e.target === modal) done("cancel"); };
  });
  if (choice === "cancel") return false;
  if (choice === "keep") {
    for (const d of docs) {
      const resp = await fetch(`/sessions/${sessionId}/docs/${encodeURIComponent(d.name)}/keep`, { method: "POST" });
      if (!resp.ok) {
        notify(`No se pudo guardar "${d.name}" en Mis documentos - no se borra la conversacion.`);
        return false;
      }
    }
  }
  return true;
}

function startNewConversation(clearStorage = true) {
  if (clearStorage) localStorage.removeItem("ia_session_id");
  log.innerHTML = "";
  log.appendChild(emptyState);
  emptyState.style.display = "block";
  planPanel.style.display = "none";
  document.querySelectorAll(".conv-row").forEach(r => r.classList.remove("current"));
  refreshDocChips();
}
newChatBtn.addEventListener("click", () => startNewConversation());

["profileModal", "adminModal", "knowledgeModal", "metricsModal", "modelUpdatesModal", "memoryModal"]
  .forEach((id) => {
    const modal = document.getElementById(id);
    const header = modal.querySelector(".modal-header");
    const back = document.createElement("button");
    back.className = "modal-back";
    back.textContent = "←";
    back.title = "Volver a Opciones";
    back.addEventListener("click", () => {
      modal.querySelector(".modal-close").click();
      document.getElementById("optionsModal").style.display = "block";
    });
    header.insertBefore(back, header.firstChild);
  });

const ATTACHED_DOC_PREFIX = "📄 Documento adjuntado: ";

function addLoadedMessage(role, content, agent, messageId, sessionId, media, createdAt) {
  if (agent === "adjunto" && content.startsWith(ATTACHED_DOC_PREFIX)) {
    addDocCard(content.slice(ATTACHED_DOC_PREFIX.length));
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const roleEl = document.createElement("div");
  roleEl.className = "role";
  roleEl.textContent = role === "user" ? "Tu" : ("Chati" + (agent ? ` (${agent})` : ""));
  stampMessage(wrap, roleEl, messageDate(createdAt));

  const actions = document.createElement("span");
  actions.className = "msg-actions";
  const editBtn = document.createElement("button");
  editBtn.textContent = "✎";
  editBtn.title = "Editar";
  const delBtn = document.createElement("button");
  delBtn.textContent = "🗑";
  delBtn.title = "Borrar mensaje";
  actions.appendChild(editBtn);
  actions.appendChild(delBtn);
  roleEl.appendChild(actions);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "assistant") {
    renderMarkdownInto(bubble, content, { highlight: true });
  } else {
    bubble.textContent = content;
  }

  if (media && /^[0-9a-f]{32}\.(png|jpg|webp|mp4)$/.test(media)) {
    appendMediaWithActions(bubble, "/media/" + media, media);
  }

  wrap.appendChild(roleEl);
  wrap.appendChild(bubble);
  log.appendChild(wrap);

  editBtn.addEventListener("click", () => {
    const textarea = document.createElement("textarea");
    textarea.value = content;
    textarea.style.cssText = "width:100%; min-height:60px; background:var(--panel-3); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:8px; font-family:inherit; font-size:13.5px; resize:vertical;";
    const saveRow = document.createElement("div");
    saveRow.style.cssText = "margin-top:6px; display:flex; gap:6px;";
    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Guardar";
    saveBtn.style.cssText = "font-size:12px; padding:4px 10px; background:var(--accent); color:white; border:none; border-radius:6px; cursor:pointer;";
    const cancelEditBtn = document.createElement("button");
    cancelEditBtn.textContent = "Cancelar";
    cancelEditBtn.style.cssText = "font-size:12px; padding:4px 10px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); border-radius:6px; cursor:pointer;";
    saveRow.appendChild(saveBtn);
    saveRow.appendChild(cancelEditBtn);
    bubble.innerHTML = "";
    bubble.appendChild(textarea);
    bubble.appendChild(saveRow);
    textarea.focus();

    cancelEditBtn.addEventListener("click", () => loadConversationIntoLog(sessionId));
    saveBtn.addEventListener("click", async () => {
      const form = new FormData();
      form.append("content", textarea.value);
      await fetch(`/sessions/${sessionId}/messages/${messageId}`, { method: "PUT", body: form });
      await loadConversationIntoLog(sessionId);
    });
  });

  delBtn.addEventListener("click", async () => {
    if (!await askConfirm("¿Borrar este mensaje?")) return;
    await fetch(`/sessions/${sessionId}/messages/${messageId}`, { method: "DELETE" });
    wrap.remove();
  });

  return bubble;
}

async function loadConversationIntoLog(sessionId) {
  let messages;
  try {
    const resp = await fetch(`/sessions/${sessionId}`);

    if (!resp.ok) { startNewConversation(); return; }
    messages = await resp.json();
  } catch (err) { return; }

  setSessionId(sessionId);
  localStorage.setItem("ia_session_id", sessionId);
  refreshDocChips();
  log.innerHTML = "";
  messages.forEach(m => addLoadedMessage(m.role, m.content, m.agent, m.id, sessionId, m.media, m.created_at));
  log.scrollTop = log.scrollHeight;
  planPanel.style.display = "none";
  document.querySelectorAll(".conv-row").forEach(r => r.classList.remove("current"));
  document.querySelectorAll(".conv-row").forEach(r => {
    if (r.querySelector(".conv-title") && r.contains(document.activeElement)) return;
  });
  await loadConversations();
}

