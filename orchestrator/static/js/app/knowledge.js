// Chati web: documentos de conocimiento, opciones y memoria.
const knowledgeBtn = document.getElementById("knowledgeBtn");
const knowledgeModal = document.getElementById("knowledgeModal");
const closeKnowledgeBtn = document.getElementById("closeKnowledgeBtn");
const knowledgeFileInput = document.getElementById("knowledgeFileInput");
const knowledgeListBox = document.getElementById("knowledgeListBox");

knowledgeBtn.addEventListener("click", async () => {
  optionsModal.style.display = "none";
  knowledgeModal.style.display = "block";
  await loadKnowledgeList();
});
closeKnowledgeBtn.addEventListener("click", () => { knowledgeModal.style.display = "none"; });
knowledgeModal.addEventListener("click", (e) => { if (e.target === knowledgeModal) knowledgeModal.style.display = "none"; });

async function loadKnowledgeList() {
  const resp = await fetch("/knowledge");
  const docs = await resp.json();
  knowledgeListBox.innerHTML = "";
  if (!docs.length) {
    knowledgeListBox.innerHTML = '<div style="color:var(--muted); font-size:12px;">No hay documentos todavia.</div>';
    return;
  }
  docs.forEach(d => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border); font-size:13px;";
    row.innerHTML = `<div>${esc(d.filename)} <span style="color:var(--muted); font-size:11px;">(${esc(d.chunks)} fragmentos)</span></div>`;
    const delBtn = document.createElement("button");
    delBtn.textContent = "Borrar";
    delBtn.style.cssText = "font-size:12px; padding:4px 10px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); border-radius:6px; cursor:pointer;";
    delBtn.addEventListener("click", async () => {
      await fetch(`/knowledge/${encodeURIComponent(d.filename)}`, { method: "DELETE" });
      await loadKnowledgeList();
    });
    row.appendChild(delBtn);
    knowledgeListBox.appendChild(row);
  });
}

knowledgeFileInput.addEventListener("change", async () => {
  if (!knowledgeFileInput.files[0]) return;
  const form = new FormData();
  form.append("file", knowledgeFileInput.files[0]);
  knowledgeListBox.innerHTML = '<div style="color:var(--muted); font-size:12px;"><span class="spinner"></span> procesando documento...</div>';
  try {
    await fetch("/knowledge", { method: "POST", body: form });
  } catch (err) {  }
  knowledgeFileInput.value = "";
  await loadKnowledgeList();
});

const optionsBtn = document.getElementById("optionsBtn");
const optionsModal = document.getElementById("optionsModal");
const closeOptionsBtn = document.getElementById("closeOptionsBtn");

optionsBtn.addEventListener("click", () => { optionsModal.style.display = "block"; });
closeOptionsBtn.addEventListener("click", () => { optionsModal.style.display = "none"; });
optionsModal.addEventListener("click", (e) => { if (e.target === optionsModal) optionsModal.style.display = "none"; });

const optMemoryBtn = document.getElementById("optMemoryBtn");
const memoryModal = document.getElementById("memoryModal");
const closeMemoryBtn = document.getElementById("closeMemoryBtn");
const memoryListBox = document.getElementById("memoryListBox");
const memoryNoteInput = document.getElementById("memoryNoteInput");
const addMemoryNoteBtn = document.getElementById("addMemoryNoteBtn");

const MEMORY_TYPE_LABEL = { note: "Nota tuya", conversation: "De una conversacion" };

optMemoryBtn.addEventListener("click", async () => {
  optionsModal.style.display = "none";
  memoryModal.style.display = "block";
  await loadMemoryEntries();
});
closeMemoryBtn.addEventListener("click", () => { memoryModal.style.display = "none"; });
memoryModal.addEventListener("click", (e) => { if (e.target === memoryModal) memoryModal.style.display = "none"; });

async function loadMemoryEntries() {
  memoryListBox.innerHTML = '<span class="spinner"></span> cargando...';
  const resp = await fetch("/memory/entries");
  const entries = await resp.json();

  if (!entries.length) {
    memoryListBox.innerHTML = '<div style="color:var(--muted); font-size:12px;">Todavia no hay nada guardado en la memoria a largo plazo.</div>';
    return;
  }

  memoryListBox.innerHTML = "";
  entries.forEach((entry) => {
    const row = document.createElement("div");
    row.style.cssText = "padding:10px 0; border-top:1px solid var(--border);";

    const label = document.createElement("div");
    label.style.cssText = "font-size:10.5px; color:var(--muted); text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;";
    label.textContent = MEMORY_TYPE_LABEL[entry.type] || entry.type;
    row.appendChild(label);

    const textEl = document.createElement("div");
    textEl.style.cssText = "font-size:13px; white-space:pre-wrap; margin-bottom:6px;";
    textEl.textContent = entry.text;
    row.appendChild(textEl);

    if (entry.type === "note") {
      const btnRow = document.createElement("div");
      btnRow.style.cssText = "display:flex; gap:6px;";

      const editBtn = document.createElement("button");
      editBtn.textContent = "Editar";
      editBtn.style.cssText = "font-size:11.5px; padding:3px 9px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); border-radius:6px; cursor:pointer;";
      editBtn.addEventListener("click", () => {
        const textarea = document.createElement("textarea");
        textarea.value = entry.text;
        textarea.rows = 2;
        textarea.style.cssText = "width:100%; background:var(--panel-3); color:var(--text); border:1px solid var(--accent); border-radius:6px; padding:8px; font-family:inherit; resize:vertical; box-sizing:border-box; margin-bottom:6px;";
        row.replaceChild(textarea, textEl);
        textarea.focus();
        editBtn.textContent = "Guardar";
        editBtn.addEventListener("click", async () => {
          const form = new FormData();
          form.append("text", textarea.value.trim());
          await fetch(`/memory/entries/${encodeURIComponent(entry.id)}`, { method: "PUT", body: form });
          await loadMemoryEntries();
        }, { once: true });
      }, { once: true });

      const delBtn = document.createElement("button");
      delBtn.textContent = "Borrar";
      delBtn.style.cssText = editBtn.style.cssText;
      delBtn.addEventListener("click", async () => {
        if (!confirm("¿Borrar esta nota de la memoria?")) return;
        await fetch(`/memory/entries/${encodeURIComponent(entry.id)}`, { method: "DELETE" });
        await loadMemoryEntries();
      });

      btnRow.appendChild(editBtn);
      btnRow.appendChild(delBtn);
      row.appendChild(btnRow);
    }

    memoryListBox.appendChild(row);
  });
}

addMemoryNoteBtn.addEventListener("click", async () => {
  const text = memoryNoteInput.value.trim();
  if (!text) return;
  addMemoryNoteBtn.disabled = true;
  try {
    const form = new FormData();
    form.append("text", text);
    await fetch("/memory/entries", { method: "POST", body: form });
    memoryNoteInput.value = "";
    await loadMemoryEntries();
  } finally {
    addMemoryNoteBtn.disabled = false;
  }
});

