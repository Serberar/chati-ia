// Chati web: lista de tareas del agente, modo codigo y menu de atajos.
const OPENCODE_CREDIT_HTML = 'Agente: <a href="https://opencode.ai" target="_blank" rel="noopener">powered by OpenCode</a>' +
  ' · modelos con <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a>';
const AGENT_POLL_MS = 2500;
const AGENT_TOOL_LABELS = {
  read: "Leyendo", write: "Creando archivo", edit: "Editando", patch: "Editando",
  bash: "Ejecutando", glob: "Buscando archivos", grep: "Buscando texto", list: "Mirando carpeta",
  webfetch: "Consultando web", websearch: "Buscando en internet", task: "Subtarea",
};
const AGENT_PERMISSION_LABELS = {
  edit: "modificar archivos", write: "crear archivos", bash: "ejecutar un comando",
  external_directory: "acceder a una carpeta fuera de su carpeta de trabajo",
  webfetch: "acceder a internet", websearch: "buscar en internet", read: "leer archivos",
};
const AGENT_STATUS_ICON = { completed: "✓", error: "✕", running: "●", pending: "○" };
const runningTool = (steps) => [...steps].reverse().find((s) => s.kind === "tool" && s.status === "running");
const agentViews = {};

function agentTimeAgo(ms) {
  if (!ms) return "";
  const mins = Math.round((Date.now() - ms) / 60000);
  if (mins < 1) return "ahora";
  if (mins < 60) return `hace ${mins} min`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`;
}

async function agentPost(url, body) {
  const resp = await sendJSON(url, body || {});
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
  return data;
}

async function showAgentTaskList() {
  let tasks;
  try {
    const resp = await fetch("/agent/tasks");
    if (!resp.ok) return;
    tasks = await resp.json();
  } catch (e) { return; }
  if (!tasks.length || currentMode !== "agente") return;
  const bubble = addMessage("assistant", "agente");
  const title = document.createElement("div");
  title.className = "agent-tasks-title";
  title.textContent = "Tareas recientes del agente - pulsa una para ver su estado:";
  const clear = document.createElement("button");
  clear.className = "agent-tasks-clear";
  clear.textContent = "🗑 Borrar historial";
  clear.title = "Borra las tareas terminadas (las que estén en marcha se quedan)";
  clear.addEventListener("click", async () => {
    if (!await askConfirm("¿Borrar el historial de tareas del agente?\n\nSe borran las conversaciones de las tareas terminadas; " +
                 "los archivos que cambiaron se quedan como están. Las tareas en marcha no se tocan.")) return;
    clear.disabled = true;
    try {
      const r = await agentPost("/agent/tasks/clear");
      bubble.textContent = r.en_marcha
        ? `Historial borrado (${r.borradas}). Quedan ${r.en_marcha} en marcha o esperando tu respuesta.`
        : `Historial borrado (${r.borradas} tareas).`;
    } catch (err) {
      notify("No se pudo borrar: " + (err.message || err));
      clear.disabled = false;
    }
  });
  title.appendChild(clear);
  const list = document.createElement("div");
  list.className = "agent-tasks";
  for (const t of tasks.slice(0, 6)) {
    const btn = document.createElement("button");
    const icon = document.createElement("span");
    icon.textContent = t.status === "idle" ? "✓" : "●";
    icon.style.color = t.status === "idle" ? "var(--muted)" : "var(--accent)";
    const name = document.createElement("span");
    name.textContent = t.title || t.session_id;
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = t.status === "idle" ? agentTimeAgo(t.updated) : "en marcha";
    btn.append(icon, name, when);
    btn.addEventListener("click", () => openAgentView(t.session_id));
    list.appendChild(btn);
  }
  bubble.append(title, list);
}

const codeState = { project: null, mode: "plan", fast: false, recent: [] };
try {
  codeState.mode = localStorage.getItem("ia_code_mode") || "plan";
  codeState.fast = localStorage.getItem("ia_code_fast") === "on";
} catch (e) { silenced(e); }
const codeMenu = document.getElementById("codeProjectMenu");

function renderCodeBar() {
  const p = codeState.project;
  document.getElementById("codeProjectName").textContent = p ? p.name : "Abrir un proyecto…";
  document.getElementById("codeProjectBtn").title = p ? p.path : "Elige la carpeta de tu proyecto";
  document.querySelectorAll("[data-code-mode]").forEach((b) => b.classList.toggle("active", b.dataset.codeMode === codeState.mode));
  document.getElementById("codeFast").checked = codeState.fast;
  document.getElementById("codeGitWarn").style.display = p && !p.git ? "inline" : "none";
  document.getElementById("codeAnalyzeBtn").style.display = p ? "inline-block" : "none";
  document.getElementById("codeShortcutsBtn").style.display = p ? "inline-block" : "none";
  document.getElementById("codeAnalyzeBtn").textContent = p && p.agents_md ? "📋 Actualizar AGENTS.md" : "📋 Analizar proyecto";
}

async function initCodeMode() {
  renderCodeBar();
  try {
    const data = await (await fetch("/code/projects")).json();
    codeState.recent = data.projects || [];
  } catch (e) { codeState.recent = []; }
  let last = null;
  try { last = localStorage.getItem("ia_code_project"); } catch (e) { silenced(e); }
  const known = codeState.recent.find((p) => p.path === last && p.exists);
  if (known && !codeState.project) await openCodeProject(known.path, true);
  else if (codeState.project) showCodeWelcome();
  else {
    const bubble = addMessage("assistant", "código");
    bubble.innerHTML = "Abre la carpeta de un proyecto con <b>📁</b> (abajo) y pregúntame lo que quieras sobre él: " +
      "cómo está organizado, cómo mejorar su estructura, o que haga cambios.<br><br>" +
      "<b>🧭 Planificar</b> mira y propone sin tocar nada · <b>🛠 Construir</b> hace los cambios, pidiendo permiso.";
  }
}

async function openCodeProject(path, quiet = false) {
  let info;
  try {
    info = await agentPost("/code/projects", { path });
  } catch (err) {
    if (!quiet) notify(err.message || err);
    return;
  }
  codeState.project = info;
  try { localStorage.setItem("ia_code_project", info.path); } catch (e) { silenced(e); }
  codeState.recent = [info, ...codeState.recent.filter((p) => p.path !== info.path)];
  renderCodeBar();
  codeMenu.classList.remove("show");
  showCodeWelcome();
}

async function showCodeWelcome() {
  const p = codeState.project;
  if (!p || currentMode !== "codigo") return;
  const bubble = addMessage("assistant", "código");
  bubble.classList.add("code-welcome");
  const title = document.createElement("div");
  title.innerHTML = "📁 <b></b>";
  title.querySelector("b").textContent = p.name;
  const path = document.createElement("div");
  path.className = "files";
  path.textContent = p.path;
  const files = document.createElement("div");
  files.className = "files";
  files.textContent = p.entries.join("   ") + (p.total > p.entries.length ? `   … (+${p.total - p.entries.length})` : "");
  const tip = document.createElement("div");
  tip.style.fontSize = "12.5px";
  tip.textContent = p.agents_md
    ? "Tiene AGENTS.md: el agente lo lee en cada conversación."
    : "Consejo: pulsa «📋 Analizar proyecto» para que escriba un AGENTS.md con la estructura y cómo se trabaja en él.";
  bubble.append(title, path, files, tip);
  try {
    const tasks = await (await fetch(`/code/tasks?path=${encodeURIComponent(p.path)}`)).json();
    if (Array.isArray(tasks) && tasks.length) {
      const t = document.createElement("div");
      t.className = "agent-tasks-title";
      t.style.marginTop = "10px";
      t.textContent = "Conversaciones anteriores en este proyecto:";
      const list = document.createElement("div");
      list.className = "agent-tasks";
      for (const task of tasks.slice(0, 6)) {
        const btn = document.createElement("button");
        const name = document.createElement("span");
        name.textContent = task.title || task.session_id;
        const when = document.createElement("span");
        when.className = "when";
        when.textContent = task.status === "idle" ? agentTimeAgo(task.updated) : "en marcha";
        btn.append(name, when);
        btn.addEventListener("click", () => openAgentView(task.session_id, null, codeState.mode));
        list.appendChild(btn);
      }
      bubble.append(t, list);
    }
  } catch (e) { silenced(e); }
}

function renderCodeMenu() {
  codeMenu.innerHTML = "";
  for (const p of codeState.recent.filter((x) => x.exists).slice(0, 8)) {
    const b = document.createElement("button");
    b.className = "item";
    b.textContent = p.name;
    const small = document.createElement("small");
    small.textContent = p.path;
    b.appendChild(small);
    b.addEventListener("click", () => openCodeProject(p.path));
    codeMenu.appendChild(b);
  }
  const pick = document.createElement("button");
  pick.className = "item";
  pick.textContent = "📂 Abrir otra carpeta…";
  pick.addEventListener("click", async () => {
    codeMenu.classList.remove("show");
    pick.disabled = true;
    try {
      const data = await agentPost("/code/pick_folder");
      if (data.path) await openCodeProject(data.path);
    } catch (err) { notify(err.message || err); }
  });
  codeMenu.appendChild(pick);
  const row = document.createElement("div");
  row.className = "path-row";
  const input = document.createElement("input");
  input.placeholder = "o escribe la ruta: C:\\Users\\...\\mi-proyecto";
  const go = document.createElement("button");
  go.textContent = "Abrir";
  const openTyped = () => { if (input.value.trim()) openCodeProject(input.value.trim()); };
  go.addEventListener("click", openTyped);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") openTyped(); });
  row.append(input, go);
  codeMenu.appendChild(row);
}

document.getElementById("codeProjectBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  if (codeMenu.classList.toggle("show")) renderCodeMenu();
});
codeMenu.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => codeMenu.classList.remove("show"));
document.querySelectorAll("[data-code-mode]").forEach((b) => b.addEventListener("click", () => {
  codeState.mode = b.dataset.codeMode;
  try { localStorage.setItem("ia_code_mode", codeState.mode); } catch (e) { silenced(e); }
  renderCodeBar();
}));
document.getElementById("codeFast").addEventListener("change", (e) => {
  codeState.fast = e.target.checked;
  try { localStorage.setItem("ia_code_fast", codeState.fast ? "on" : "off"); } catch (err) { silenced(err); }
  prepareModelsForMode();
});

(() => {
  const auto = document.getElementById("codeAuto");
  try { auto.checked = localStorage.getItem("ia_code_auto") === "on"; } catch (e) { silenced(e); }
  auto.addEventListener("change", () => {
    try { localStorage.setItem("ia_code_auto", auto.checked ? "on" : "off"); } catch (e) { silenced(e); }
  });
})();
document.getElementById("codeGitInit").addEventListener("click", async () => {
  const p = codeState.project;
  if (!p || !await askConfirm(`¿Activar git en «${p.name}»?\n\nSe crea una carpeta oculta .git en el proyecto. Sirve para que Chati pueda enseñarte y deshacer los cambios del agente. No se sube nada a internet.`)) return;
  try {
    codeState.project = await agentPost("/code/git_init", { path: p.path });
    renderCodeBar();
  } catch (err) { notify(err.message || err); }
});

const CODE_SHORTCUTS = [
  { icon: "🔎", title: "Explícame el proyecto", mode: "plan", desc: "Para qué sirve, cómo está organizado y por dónde empezar",
    text: "Explícame este proyecto: para qué sirve, cómo está organizado (carpetas y archivos importantes), qué " +
      "tecnologías usa, cómo se ejecuta y cómo se prueba, y por qué archivos empezar a leer. Con ejemplos reales del " +
      "proyecto. No cambies nada." },
  { icon: "🧐", title: "Revisa mis cambios", mode: "plan", desc: "Lista de posibles fallos en lo que has cambiado",
    text: "Revisa los cambios sin guardar en git de este proyecto (git status y git diff; si no hay, el último " +
      "commit con git show). Busca fallos de lógica, casos que no se contemplan, errores que rompan algo, problemas " +
      "de seguridad y tests que falten. Dame una lista ordenada de más grave a menos, cada punto con archivo, línea, " +
      "qué pasa y cómo lo arreglarías. Si no ves nada importante, dilo. No cambies nada." },
  { icon: "🧪", title: "Escribe tests", mode: "build", desc: "Tests para lo importante que no tiene",
    text: "Mira qué partes importantes del proyecto no tienen tests y escribe tests para ellas, con el sistema de " +
      "tests que ya use el proyecto (si no tiene ninguno, pytest para Python). Prueba el comportamiento real, casos " +
      "normales y casos límite. No cambies el código que se prueba. Ejecuta los tests y dime cuáles has añadido y " +
      "si pasan; si alguno falla por un fallo real del código, dímelo en vez de cambiar el test." },
  { icon: "📦", title: "¿Dependencias al día?", mode: "plan", desc: "Versiones nuevas y cuáles pueden romper cosas",
    text: "Revisa si las dependencias de este proyecto están al día (usa chati_revisar_actualizaciones). Dime cuáles " +
      "tienen versión nueva, cuáles son cambios de versión mayor que pueden romper cosas y, para las importantes, qué " +
      "cambia (busca sus notas de versión). No actualices nada." },
  { icon: "💾", title: "Haz commit", mode: "build", desc: "Mensaje claro de qué y por qué, sin subir nada",
    text: "Mira git status y git diff y haz un commit con lo cambiado. Mensaje en español: primera línea corta con qué " +
      "cambia, y debajo por qué. Si hay archivos que no deberían ir (contraseñas, .env, temporales, carpetas venv o " +
      "node_modules), no los añadas y avísame. No hagas push." },
  { icon: "🌿", title: "Rama nueva", mode: "build", desc: "Trabajar aparte sin tocar la rama principal",
    text: "Crea una rama nueva de git para el trabajo que vamos a hacer, con un nombre corto en minúsculas y guiones " +
      "que lo describa (si no sabes de qué va, pregúntamelo antes). Usa git switch -c. Si hay cambios sin guardar, " +
      "dímelo antes de cambiar de rama. Al terminar dime en qué rama estamos." },
  { icon: "🚀", title: "Subir y crear PR", mode: "build", desc: "Sube la rama y prepara la pull request en GitHub",
    text: "Prepara una pull request de la rama actual: mira con git log y git diff qué cambia respecto a la rama " +
      "principal y escribe un título corto y una descripción en español (qué cambia, por qué y cómo probarlo). " +
      "Enséñamelos y espera a que te diga que sí. Después haz git push -u origin con la rama y crea la PR con " +
      "gh pr create. Si estás en la rama principal, no hay remoto o no está instalado gh, dímelo y no subas nada." },
];

function renderCodeShortcuts() {
  const menu = document.getElementById("codeShortcutsMenu");
  menu.innerHTML = "";

  const own = agentShortcuts.filter((x) => x.donde === "plan" || x.donde === "build")
    .map((x) => ({ icon: "⭐", title: x.name, mode: x.donde, text: x.task,
                   desc: x.donde === "plan" ? "Tuyo · solo mira y propone" : "Tuyo · hace cambios" }));
  if (compactQuery.matches) {
    menu.appendChild(menuToggle("Rápido (modelo pequeño)", document.getElementById("codeFast")));
    menu.appendChild(menuToggle("🚀 Sin preguntar", document.getElementById("codeAuto")));
    menu.appendChild(menuItem("📋 Analizar proyecto", () => {
      menu.classList.remove("show");
      document.getElementById("codeAnalyzeBtn").click();
    }));
  }
  for (const sc of [...CODE_SHORTCUTS, ...own]) {
    const b = document.createElement("button");
    b.className = "item";
    b.textContent = `${sc.icon} ${sc.title}`;
    const small = document.createElement("small");
    small.textContent = sc.desc;
    b.appendChild(small);
    b.addEventListener("click", () => {
      menu.classList.remove("show");
      startAgentTask(sc.text, { codeMode: sc.mode });
    });
    menu.appendChild(b);
  }
  const add = document.createElement("button");
  add.className = "item";
  add.textContent = "＋ Crear o editar mis atajos";
  add.addEventListener("click", () => {
    menu.classList.remove("show");
    openShortcutsModal({ donde: "build" });
  });
  menu.appendChild(add);
}

document.getElementById("codeShortcutsBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  const menu = document.getElementById("codeShortcutsMenu");
  if (menu.classList.toggle("show")) {
    renderCodeShortcuts();
    if (!agentShortcuts.length) loadAgentShortcuts().then(renderCodeShortcuts);
  }
});
document.getElementById("codeShortcutsMenu").addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => document.getElementById("codeShortcutsMenu").classList.remove("show"));

document.getElementById("codeAnalyzeBtn").addEventListener("click", () => {
  startAgentTask("Analiza este proyecto: para qué sirve, estructura de carpetas, tecnologías, cómo se ejecuta y cómo " +
    "se prueba, y las convenciones del código. Después crea (o actualiza, si ya existe) el archivo AGENTS.md en la raíz " +
    "del proyecto con ese resumen: breve, concreto y útil para quien vaya a programar en él.", { codeMode: "build" });
});

function renderAgentChoice(task, reason, attachments = []) {
  const bubble = addMessage("assistant", "agente");
  const card = document.createElement("div");
  card.className = "agent-choice";
  const title = document.createElement("div");
  title.className = "ac-title";
  title.textContent = "🧠 Esta tarea parece compleja para el modelo rapido";
  const why = document.createElement("div");
  why.className = "ac-why";
  why.textContent = reason ? "Motivo: " + reason : "";
  const rec = document.createElement("div");
  rec.className = "ac-rec";
  rec.textContent = "Te recomiendo el modelo potente: se equivoca menos, pero tarda minutos en vez de segundos y ocupa casi toda la RAM mientras trabaja.";
  const btns = document.createElement("div");
  btns.className = "ac-btns";
  const launch = async (potente) => {
    btns.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const data = await agentPost("/agent/tasks", { task, potente, confirmed: true, attachments });
      btns.innerHTML = "";
      const done = document.createElement("div");
      done.className = "ac-why";
      done.textContent = potente ? "Lanzada con el modelo potente." : "Lanzada con el modelo rapido.";
      btns.appendChild(done);
      openAgentView(data.session_id, Date.now());
    } catch (err) {
      btns.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      notify(String(err.message || err));
    }
  };
  const strong = document.createElement("button");
  strong.className = "primary";
  strong.textContent = "Usar el modelo potente";
  strong.addEventListener("click", () => launch(true));
  const fast = document.createElement("button");
  fast.textContent = "Probar con el rapido";
  fast.addEventListener("click", () => launch(false));
  btns.append(strong, fast);
  card.append(title, why, rec, btns);
  bubble.appendChild(card);
  log.scrollTop = log.scrollHeight;
}

let agentShortcuts = [];
const agentShortcutsRow = document.getElementById("agentShortcutsRow");

async function loadAgentShortcuts() {
  try {
    const resp = await fetch("/agent/shortcuts");
    if (resp.ok) agentShortcuts = await resp.json();
  } catch (e) { silenced(e); }
  renderAgentShortcuts();
}

const compactQuery = window.matchMedia("(max-width: 760px)");
compactQuery.addEventListener("change", () => renderAgentShortcuts());

function popMenu(button, menu) {
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    document.querySelectorAll(".pop-menu.show").forEach((m) => { if (m !== menu) m.classList.remove("show"); });
    menu.classList.toggle("show");
  });
  menu.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => menu.classList.remove("show"));
}

function menuItem(text, onClick) {
  const b = document.createElement("button");
  b.className = "item";
  b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

function menuToggle(text, source) {

  const label = document.createElement("label");
  label.className = "item toggle";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = source.checked;
  box.addEventListener("change", () => {
    source.checked = box.checked;
    source.dispatchEvent(new Event("change"));
  });
  label.append(box, document.createTextNode(" " + text));
  return label;
}

function renderAgentShortcutsCompact() {
  const own = agentShortcuts.filter((x) => (x.donde || "agente") === "agente");
  const button = document.createElement("button");
  button.className = "compact-toggle";
  button.textContent = "⚡ Atajos ▾" + (agentPowerToggle.checked ? " · 🧠" : "");
  const menu = document.createElement("div");
  menu.className = "pop-menu";
  for (const sc of own) {
    menu.appendChild(menuItem("⚡ " + sc.name + (sc.potente ? " 🧠" : ""), () => {
      menu.classList.remove("show");
      startAgentTask(sc.task, { potente: sc.potente });
    }));
  }
  const power = menuToggle("Modelo potente (más lento)", agentPowerToggle);
  power.querySelector("input").addEventListener("change", () => {
    button.textContent = "⚡ Atajos ▾" + (agentPowerToggle.checked ? " · 🧠" : "");
  });
  menu.appendChild(power);
  menu.appendChild(menuItem(own.length ? "⚙ Gestionar atajos" : "+ Crear atajo", () => {
    menu.classList.remove("show");
    openShortcutsModal();
  }));
  popMenu(button, menu);
  agentShortcutsRow.append(button, menu);
}

function renderAgentShortcuts() {
  agentShortcutsRow.innerHTML = "";
  if (compactQuery.matches) { renderAgentShortcutsCompact(); return; }
  for (const sc of agentShortcuts.filter((x) => (x.donde || "agente") === "agente")) {
    const b = document.createElement("button");
    b.textContent = "⚡ " + sc.name + (sc.potente ? " 🧠" : "");
    b.title = sc.task + (sc.potente ? "\n(con el modelo potente)" : "");
    b.addEventListener("click", () => startAgentTask(sc.task, { potente: sc.potente }));
    agentShortcutsRow.appendChild(b);
  }
  const manage = document.createElement("button");
  manage.className = "manage";
  manage.textContent = agentShortcuts.length ? "⚙ Atajos" : "+ Crear atajo";
  manage.addEventListener("click", () => openShortcutsModal());
  agentShortcutsRow.appendChild(manage);
}

