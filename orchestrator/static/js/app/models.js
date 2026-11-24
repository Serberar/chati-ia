// Chati web: metricas, estado y actualizaciones de modelos, modelos de imagen y video.
const metricsBtn = document.getElementById("optMetricsBtn");
const metricsModal = document.getElementById("metricsModal");
const closeMetricsBtn = document.getElementById("closeMetricsBtn");
const metricsBox = document.getElementById("metricsBox");

metricsBtn.addEventListener("click", async () => {
  optionsModal.style.display = "none";
  metricsModal.style.display = "block";
  await loadMetrics();
});
closeMetricsBtn.addEventListener("click", () => { metricsModal.style.display = "none"; });
metricsModal.addEventListener("click", (e) => { if (e.target === metricsModal) metricsModal.style.display = "none"; });

async function loadMetrics() {
  metricsBox.innerHTML = '<span class="spinner"></span> cargando...';
  const resp = await fetch("/metrics/summary");
  const data = await resp.json();

  if (!data.total_requests) {
    metricsBox.innerHTML = '<div style="color:var(--muted);">Todavia no hay peticiones registradas.</div>';
    return;
  }

  let html = `<div style="margin-bottom:12px; color:var(--muted);">${data.window} · ${data.total_requests} peticiones · ${data.errors} errores · ${data.verifier_gated} bloqueadas por el verificador</div>`;
  html += '<table style="width:100%; border-collapse:collapse;">';
  html += '<tr style="text-align:left; color:var(--muted); font-size:11px;"><th style="padding:6px 0;">Agente</th><th>Peticiones</th><th>Latencia media</th><th>Errores</th><th>Bloqueadas</th></tr>';
  for (const [agent, s] of Object.entries(data.by_agent)) {
    html += `<tr style="border-top:1px solid var(--border);">
      <td style="padding:6px 0;">${esc(agent)}</td>
      <td>${s.count}</td>
      <td>${(s.avg_latency_ms / 1000).toFixed(1)}s</td>
      <td>${s.errors}</td>
      <td>${s.gated}</td>
    </tr>`;
  }
  html += '</table>';
  metricsBox.innerHTML = html;
}

const modelUpdatesBtn = document.getElementById("optModelUpdatesBtn");
const modelUpdatesModal = document.getElementById("modelUpdatesModal");
const closeModelUpdatesBtn = document.getElementById("closeModelUpdatesBtn");
const checkModelUpdatesBtn = document.getElementById("checkModelUpdatesBtn");
const modelUpdatesBox = document.getElementById("modelUpdatesBox");
const modelStatusBox = document.getElementById("modelStatusBox");
const imageModelsBox = document.getElementById("imageModelsBox");
const videoModelsBox = document.getElementById("videoModelsBox");

modelUpdatesBtn.addEventListener("click", async () => {
  optionsModal.style.display = "none";
  modelUpdatesModal.style.display = "block";
  await loadModelUpdates(false);
  await loadModelStatusBox();
  await loadImageVideoModelsBox();
});
closeModelUpdatesBtn.addEventListener("click", () => { modelUpdatesModal.style.display = "none"; });
modelUpdatesModal.addEventListener("click", (e) => { if (e.target === modelUpdatesModal) modelUpdatesModal.style.display = "none"; });
checkModelUpdatesBtn.addEventListener("click", () => loadModelUpdates(true));

async function loadModelStatusBox() {
  modelStatusBox.textContent = "Cargando estado...";
  try {
    const resp = await fetch("/models/status");
    const data = await resp.json();
    const models = data.models || [];
    modelStatusBox.innerHTML = models.length
      ? "Cargados ahora mismo: " + models.map(m => `<strong style="color:var(--text);">${esc(m.name)}</strong>`).join(", ")
      : "Ningun modelo cargado en memoria ahora mismo.";
  } catch (err) {
    modelStatusBox.textContent = "No se pudo consultar el estado de Ollama.";
  }
}

function _modelStatusLabel(u) {
  return u.local_only
    ? `<span style="color:var(--muted);">variante local (uso interno, sin version en el registro)</span>`
    : u.error
      ? `<span style="color:var(--muted);">no se pudo comprobar (${esc(u.error)})</span>`
      : u.update_available
        ? `<span style="color:var(--accent, #4caf50);">actualizacion disponible</span>`
        : `<span style="color:var(--muted);">al dia</span>`;
}

function _modelRowHtml(u, roleText) {
  const updateBtn = u.update_available
    ? `<button data-model="${esc(u.model)}" class="updateModelBtn" style="font-size:12px; padding:4px 10px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); border-radius:6px; cursor:pointer;">Actualizar</button>`
    : "";
  const deleteBtn = !roleText
    ? `<button data-model="${esc(u.model)}" class="deleteModelBtn" style="font-size:12px; padding:4px 10px; background:var(--panel-2); color:var(--error, #e05252); border:1px solid var(--border); border-radius:6px; cursor:pointer;">Borrar</button>`
    : "";
  const role = roleText
    ? `<div style="font-size:11.5px; color:var(--accent); margin-top:2px;">${esc(roleText)}</div>`
    : "";
  return `<div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-top:1px solid var(--border);">
    <div><strong>${esc(u.model)}</strong>${role}<div style="margin-top:2px;">${_modelStatusLabel(u)}</div></div>
    <div style="display:flex; gap:6px; flex-shrink:0;">${updateBtn}${deleteBtn}</div>
  </div>`;
}

async function loadModelUpdates(force) {
  modelUpdatesBox.innerHTML = '<span class="spinner"></span> comprobando...';
  const [updatesResp, rolesResp] = await Promise.all([
    fetch(`/models/updates${force ? "?force=true" : ""}`),
    fetch("/models/roles"),
  ]);
  const data = await updatesResp.json();
  const roles = await rolesResp.json().catch(() => ({}));

  if (!data.updates || !data.updates.length) {
    modelUpdatesBox.innerHTML = '<div style="color:var(--muted);">No se encontraron modelos instalados de la biblioteca oficial de Ollama.</div>';
    return;
  }

  const inUse = data.updates.filter((u) => roles[u.model]);
  const unused = data.updates.filter((u) => !roles[u.model]);

  let html = `<div style="font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:0.04em; padding:4px 0;">En uso (${inUse.length})</div>`;
  html += inUse.map((u) => _modelRowHtml(u, roles[u.model])).join("");
  if (unused.length) {
    html += `<div style="font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:0.04em; padding:14px 0 4px;">Sin usar - candidatos a borrar (${unused.length})</div>`;
    html += unused.map((u) => _modelRowHtml(u, null)).join("");
  }
  modelUpdatesBox.innerHTML = html;

  modelUpdatesBox.querySelectorAll(".updateModelBtn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const model = btn.dataset.model;
      if (!await askConfirm(`Se va a descargar la ultima version de ${model}. Puede tardar varios minutos y ocupar varios GB. ¿Continuar?`)) return;
      btn.disabled = true;
      btn.textContent = "Descargando...";
      const resp = await fetch("/models/update", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `model=${encodeURIComponent(model)}`,
      });
      const data = await resp.json();
      notify(data.message || data.detail || "Descarga iniciada.");
    });
  });

  modelUpdatesBox.querySelectorAll(".deleteModelBtn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const model = btn.dataset.model;
      if (!await askConfirm(`Se va a borrar '${model}' de este ordenador para liberar disco. Para volver a usarlo habria que descargarlo de nuevo. ¿Continuar?`)) return;
      btn.disabled = true;
      btn.textContent = "Borrando...";
      try {
        const resp = await fetch(`/models/text/${encodeURIComponent(model)}`, { method: "DELETE" });
        const result = await resp.json();
        if (!resp.ok) {
          notify(result.detail || "No se pudo borrar.");
          btn.disabled = false;
          btn.textContent = "Borrar";
          return;
        }
        await loadModelUpdates(true);
      } catch (err) {
        notify("Error de conexion al borrar.");
        btn.disabled = false;
        btn.textContent = "Borrar";
      }
    });
  });
}

function renderModelArchSection(container, data, kindLabel, endpointKind) {
  const archs = data.architectures || [];
  const models = data.models || [];
  if (!archs.length) {
    container.innerHTML = '<div style="color:var(--muted); padding-top:8px;">Nada soportado todavia.</div>';
    return;
  }
  let html = data.base_folder
    ? `<div style="font-size:12px; color:var(--muted); padding-bottom:10px;">Si quieres añadir modelos nuevos de ${kindLabel}, copia el archivo dentro de <code class="model-arch-folder" style="display:inline;">${esc(data.base_folder)}\\subcarpeta-de-tipo\\nombre-del-modelo</code> (subcarpetas abajo).</div>`
    : "";
  for (const arch of archs) {
    const installedForArch = models.filter((m) => m.architecture === arch.id);
    const installedHtml = installedForArch.length
      ? installedForArch.map((m) => `<div style="display:flex; align-items:center; gap:6px; margin-top:4px;">
          <span>${esc(m.label)}</span>
          <button class="deleteArchModelBtn" data-model-id="${esc(m.id)}" data-label="${esc(m.label)}" style="font-size:10.5px; padding:2px 6px; background:var(--panel-2); color:var(--error, #e05252); border:1px solid var(--border); border-radius:5px; cursor:pointer;">Borrar</button>
        </div>`).join("")
      : `<div style="color:var(--muted); margin-top:4px;">(ninguno instalado)</div>`;
    html += `<div class="model-arch-row">
      <div><strong>${esc(arch.label)}:</strong></div>
      ${installedHtml}
      <div style="display:flex; gap:6px; align-items:center; margin-top:8px;">
        <code class="model-arch-folder">${esc(arch.folder)}</code>
        <button class="copyFolderBtn" data-folder="${esc(arch.folder)}">Copiar</button>
      </div>
    </div>`;
  }
  container.innerHTML = html;

  container.querySelectorAll(".copyFolderBtn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.folder);
        btn.textContent = "Copiado";
        setTimeout(() => { btn.textContent = "Copiar ruta"; }, 1500);
      } catch (err) { silenced(err); }
    });
  });

  container.querySelectorAll(".deleteArchModelBtn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const modelId = btn.dataset.modelId;
      const label = btn.dataset.label;
      if (!await askConfirm(`Se va a borrar el archivo de '${label}' de este ordenador. Para volver a usarlo habria que descargarlo de nuevo. ¿Continuar?`)) return;
      btn.disabled = true;
      btn.textContent = "...";
      try {
        const resp = await fetch(`/models/${endpointKind}/${encodeURIComponent(modelId)}`, { method: "DELETE" });
        const result = await resp.json();
        if (!resp.ok) {
          notify(result.detail || "No se pudo borrar.");
          btn.disabled = false;
          btn.textContent = "Borrar";
          return;
        }
        await loadImageVideoModelsBox();
      } catch (err) {
        notify("Error de conexion al borrar.");
        btn.disabled = false;
        btn.textContent = "Borrar";
      }
    });
  });
}

async function loadImageVideoModelsBox() {
  imageModelsBox.innerHTML = '<span class="spinner"></span> cargando...';
  videoModelsBox.innerHTML = '<span class="spinner"></span> cargando...';
  try {
    const [imgResp, vidResp] = await Promise.all([fetch("/models/image"), fetch("/models/video")]);
    renderModelArchSection(imageModelsBox, await imgResp.json(), "imagen", "image");
    renderModelArchSection(videoModelsBox, await vidResp.json(), "video", "video");
  } catch (err) {
    imageModelsBox.textContent = "No se pudo cargar.";
    videoModelsBox.textContent = "No se pudo cargar.";
  }
}

sendBtn.addEventListener("click", () => send());
// Flecha arriba/abajo recorre los mensajes enviados, como en una terminal, para repetirlos sin reescribir.
let promptHistory = [];
try { promptHistory = JSON.parse(localStorage.getItem("ia_prompt_history") || "[]"); } catch (e) { silenced(e); }
let historyPos = promptHistory.length;
function rememberPrompt(text) {
  if (promptHistory[promptHistory.length - 1] !== text) promptHistory.push(text);
  promptHistory = promptHistory.slice(-50);
  historyPos = promptHistory.length;
  try { localStorage.setItem("ia_prompt_history", JSON.stringify(promptHistory)); } catch (e) { silenced(e); }
}
function recallPrompt(step) {
  const pos = historyPos + step;
  if (pos < 0 || pos > promptHistory.length) return;
  historyPos = pos;
  promptEl.value = promptHistory[pos] || "";
  promptEl.dispatchEvent(new Event("input"));
  promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
}

promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
    return;
  }
  const before = promptEl.value.slice(0, promptEl.selectionStart);
  const after = promptEl.value.slice(promptEl.selectionEnd);
  if (e.key === "ArrowUp" && !before.includes("\n")) { e.preventDefault(); recallPrompt(-1); }
  if (e.key === "ArrowDown" && !after.includes("\n") && historyPos < promptHistory.length) { e.preventDefault(); recallPrompt(1); }
});
promptEl.addEventListener("input", () => {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 200) + "px";
});

initSessionUI().then(() => {
  if (!isLoggedIn()) return;
  restoreModeAndPrepare();
  if (getSessionRole() !== "guest") {
    refreshBackgroundTasks();
    setInterval(refreshBackgroundTasks, 8000);

setInterval(() => { if (bgTasksPanel.classList.contains("show")) refreshBackgroundTasks(); }, 2000);
    announceOtherComputers();
    adoptLauncherPush();
    repairPush();
  }
  showCurrentComputer();
});
refreshPlan();
