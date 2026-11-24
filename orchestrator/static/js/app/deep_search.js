// Chati web: busqueda profunda.
const deepModal = document.getElementById("deepModal");
let deepData = { history: [], status: { running: false } };
let deepPoll = null;
let deepShownId = null;
let deepUnseen = false;

async function loadDeep() {
  const resp = await fetch("/deep");
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || resp.status);
  deepData = data;
  renderDeepHistory();
  renderDeepStatus();
}

function openDeepModal() {
  deepUnseen = false;
  deepModal.style.display = "block";
  document.getElementById("deepRunText").textContent = "Cargando…";
  loadDeep().then(() => {
    const st = deepData.status || {};
    if (!st.running && !deepShownId && deepData.history.length) showDeepResult(deepData.history[0].id);
    if (st.running) followDeep();
  }).catch((err) => { document.getElementById("deepRunText").textContent = "Error: " + err.message; });
}
document.getElementById("closeDeepBtn").addEventListener("click", () => { deepModal.style.display = "none"; updateJobsChip(); });

function renderDeepHistory() {
  const sel = document.getElementById("deepHistory");
  sel.innerHTML = '<option value="">Búsquedas anteriores…</option>';
  for (const h of deepData.history) {
    const opt = document.createElement("option");
    opt.value = h.id;
    const when = new Date(h.fecha * 1000).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });
    opt.textContent = `${h.consulta.split("\n")[0].slice(0, 60)} · ${when}`;
    sel.appendChild(opt);
  }
  sel.value = deepShownId || "";
}
document.getElementById("deepHistory").addEventListener("change", (e) => { if (e.target.value) showDeepResult(e.target.value); });

function renderDeepStatus() {
  const st = deepData.status || {};
  const text = document.getElementById("deepRunText");
  const bar = document.getElementById("deepRunBar");
  document.getElementById("deepSearchBtn").style.display = st.running ? "none" : "inline-block";
  document.getElementById("deepCancelBtn").style.display = st.running ? "inline-block" : "none";
  document.getElementById("deepRefineBtn").disabled = !!st.running;
  bar.style.display = st.running && st.total ? "block" : "none";
  if (st.running) {
    const secs = Math.floor(Date.now() / 1000 - st.started);
    const mins = secs >= 60 ? `${Math.floor(secs / 60)} min ${secs % 60}s` : `${secs}s`;
    text.textContent = `${st.text} (${mins}) · puedes cerrar esta ventana, sigue buscando`;
    bar.firstElementChild.style.width = st.total ? `${Math.round(100 * st.done / st.total)}%` : "0";
  } else if (st.error) {
    text.textContent = st.error;
  } else {
    text.textContent = "Entiende lo que pides, elige dónde buscar, lee cada página y te lo resume (tarda unos minutos).";
  }
  updateJobsChip();
}

function deepChips(label, values) {
  const wrap = document.createElement("div");
  wrap.style.marginTop = "8px";
  const l = document.createElement("div");
  l.className = "lbl";
  l.textContent = label;
  const chips = document.createElement("div");
  chips.className = "deep-chips";
  for (const v of values) {
    const c = document.createElement("span");
    c.textContent = v;
    chips.appendChild(c);
  }
  wrap.append(l, chips);
  return wrap;
}

function deepItemRow(it, why) {
  const row = document.createElement("div");
  row.className = "deep-item" + (why ? " top" : "");
  const score = document.createElement("div");
  score.className = "deep-score" + (it.encaje < 8 ? " mid" : "");
  score.textContent = it.encaje;
  score.title = "Lo bien que cumple lo pedido (0-10)";
  const t = document.createElement("div");
  t.className = "t";
  t.textContent = it.titulo;
  const a = document.createElement("a");
  a.href = webUrl(it.url);
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = `Ver en ${it.fuente} ↗`;
  const d = document.createElement("div");
  d.className = "d";
  for (const [k, v] of Object.entries(it.datos || {})) {
    const span = document.createElement("span");
    const b = document.createElement("b");
    b.textContent = k + ": ";
    span.append(b, document.createTextNode(v));
    d.appendChild(span);
  }
  const n = document.createElement("div");
  n.className = "n";
  n.textContent = [why || it.nota, it.tambien_en && it.tambien_en.length ? "También en " + it.tambien_en.join(", ") : ""]
    .filter(Boolean).join(" · ");
  row.append(score, t, a, d, n);
  return row;
}

function showDeepResult(id) {
  const h = deepData.history.find((x) => x.id === id);
  const box = document.getElementById("deepResults");
  box.innerHTML = "";
  deepShownId = id;
  renderDeepHistory();
  document.getElementById("deepRefineRow").style.display = h ? "flex" : "none";
  if (!h) return;
  const u = document.createElement("div");
  u.className = "deep-understood";
  u.innerHTML = '<div class="lbl">Lo que he entendido</div>';
  u.appendChild(document.createTextNode(h.entendido));
  if (h.criterios.length) u.appendChild(deepChips("Criterios", h.criterios));
  if (h.que_es && h.que_es.si.length) u.appendChild(deepChips("Solo si es", h.que_es.si));
  if (h.que_es && h.que_es.no.length) u.appendChild(deepChips("Descarto si es", h.que_es.no));
  if (h.webs.length) u.appendChild(deepChips("Dónde he buscado, además de todo internet", h.webs));
  const meta = document.createElement("div");
  meta.className = "lbl";
  meta.style.marginTop = "8px";
  meta.textContent = `${h.paginas} páginas revisadas`;
  u.appendChild(meta);
  box.appendChild(u);
  for (const w of h.avisos || []) {
    const div = document.createElement("div");
    div.className = "jobs-warn";
    div.textContent = "⚠ " + w;
    box.appendChild(div);
  }
  if (h.tipo === "informe") {
    const rep = document.createElement("div");
    rep.className = "deep-report";
    renderMarkdownInto(rep, h.informe || "No se encontró información útil.", { highlight: false });
    box.appendChild(rep);
    if (h.fuentes.length) {
      const src = document.createElement("div");
      src.className = "deep-sources";
      h.fuentes.forEach((f, i) => {
        const a = document.createElement("a");
        a.href = webUrl(f.url);
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = `[${i + 1}] ${f.titulo} — ${f.fuente}`;
        src.appendChild(a);
      });
      box.appendChild(src);
    }
    return;
  }
  if (h.resumen) {
    const sum = document.createElement("div");
    sum.className = "deep-summary";
    sum.textContent = h.resumen;
    box.appendChild(sum);
  }
  if (h.destacados.length) {
    const t = document.createElement("div");
    t.className = "shop-section";
    t.textContent = "Destacados";
    box.appendChild(t);
    for (const dst of h.destacados) {
      const it = h.resultados.find((x) => x.url === dst.url && x.titulo === dst.titulo) || h.resultados.find((x) => x.url === dst.url);
      if (it) box.appendChild(deepItemRow(it, dst.por_que));
    }
  }
  if (h.resultados.length) {
    const t = document.createElement("div");
    t.className = "shop-section";
    t.textContent = `Todos (${h.resultados.length}), de más a menos encaje`;
    box.appendChild(t);
    for (const it of h.resultados) box.appendChild(deepItemRow(it));
  } else {
    box.insertAdjacentHTML("beforeend", '<p class="personas-intro">No se encontró nada que cumpla lo pedido. Prueba a afinar o a pedirlo de otra forma.</p>');
  }
}

async function startDeep(body) {
  try {
    await agentPost("/deep/search", body);
  } catch (err) {
    document.getElementById("deepRunText").textContent = err.message;
    return;
  }
  deepData.status = { running: true, text: "Empezando…", started: Date.now() / 1000, done: 0, total: 0 };
  renderDeepStatus();
  followDeep();
}
document.getElementById("deepSearchBtn").addEventListener("click", () => {
  const consulta = document.getElementById("deepQuery").value.trim();
  if (!consulta) { document.getElementById("deepQuery").focus(); return; }
  startDeep({ consulta });
});
document.getElementById("deepRefineBtn").addEventListener("click", () => {
  const input = document.getElementById("deepRefine");
  const extra = input.value.trim();
  if (!extra || !deepShownId) { input.focus(); return; }
  input.value = "";
  startDeep({ consulta: extra, afinar_de: deepShownId });
});
document.getElementById("deepRefine").addEventListener("keydown", (e) => { if (e.key === "Enter") document.getElementById("deepRefineBtn").click(); });
document.getElementById("deepCancelBtn").addEventListener("click", () => agentPost("/deep/cancel").catch(silenced));

function followDeep() {
  if (deepPoll) return;
  deepPoll = setInterval(async () => {
    let st;
    try { st = await (await fetch("/deep/status")).json(); } catch (e) { return; }
    deepData.status = st;
    if (st.running) { renderDeepStatus(); return; }
    clearInterval(deepPoll);
    deepPoll = null;
    await loadDeep().catch(silenced);
    if (st.last_id && !st.error) {
      showDeepResult(st.last_id);
      if (deepModal.style.display !== "block") deepUnseen = true;
    }
    updateJobsChip();
  }, 2000);
}

