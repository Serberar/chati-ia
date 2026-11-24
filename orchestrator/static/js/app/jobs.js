// Chati web: busqueda de empleo.
const appsModal = document.getElementById("appsModal");
document.getElementById("appsBtn").addEventListener("click", () => { appsModal.style.display = "block"; });
document.getElementById("closeAppsBtn").addEventListener("click", () => { appsModal.style.display = "none"; });
appsModal.addEventListener("click", (e) => { if (e.target === appsModal) appsModal.style.display = "none"; });
document.querySelector('[data-app="jobs"]').addEventListener("click", () => {
  appsModal.style.display = "none";
  openJobsModal();
});
document.querySelector('[data-app="shopping"]').addEventListener("click", () => {
  appsModal.style.display = "none";
  openShopModal();
});
document.querySelector('[data-app="deep"]').addEventListener("click", () => {
  appsModal.style.display = "none";
  openDeepModal();
});

async function loadJobs() {
  const resp = await fetch("/jobs");
  jobsData = await resp.json();
  if (!resp.ok) throw new Error(jobsData.detail || resp.status);
  renderJobs();
}

function showJobsTab(tab) {
  document.querySelectorAll("[data-jobs-tab]").forEach((x) => x.classList.toggle("active", x.dataset.jobsTab === tab));
  document.querySelectorAll("[data-jobs-pane]").forEach((pane) => {
    pane.style.display = pane.dataset.jobsPane === tab ? "block" : "none";
  });
}

function openJobsModal() {
  jobsUnseen = 0;
  jobsModal.style.display = "block";
  document.getElementById("jobsRunText").textContent = "Cargando…";
  loadCvStatus();
  loadJobs().then(() => { showJobsTab(jobsData.has_cv ? "ofertas" : "cv"); })
    .catch((err) => { document.getElementById("jobsRunText").textContent = "Error: " + err.message; });
}
document.getElementById("closeJobsBtn").addEventListener("click", () => {
  jobsModal.style.display = "none";
  updateJobsChip();
});

document.querySelectorAll("[data-jobs-tab]").forEach((b) => b.addEventListener("click", () => showJobsTab(b.dataset.jobsTab)));

function renderJobsStatus() {
  const st = jobsData.status || {};
  const text = document.getElementById("jobsRunText");
  const bar = document.getElementById("jobsRunBar");
  const searchBtn = document.getElementById("jobsSearchBtn");
  const cancelBtn = document.getElementById("jobsCancelBtn");
  searchBtn.style.display = st.running ? "none" : "inline-block";
  cancelBtn.style.display = st.running ? "inline-block" : "none";
  bar.style.display = st.running && st.total ? "block" : "none";
  if (st.running) {
    const secs = Math.floor(Date.now() / 1000 - st.started);
    const mins = secs >= 60 ? `${Math.floor(secs / 60)} min ${secs % 60}s` : `${secs}s`;
    text.textContent = `${st.text} (${mins}) · puedes cerrar esta ventana, sigue buscando`;
    bar.firstElementChild.style.width = st.total ? `${Math.round(100 * st.done / st.total)}%` : "0";
  } else if (st.error) {
    text.textContent = st.error;
  } else if (!jobsData.has_cv) {
    text.textContent = "Primero sube tu CV en la pestaña «Mi CV».";
  } else {
    text.textContent = "Busca en las webs que tengas activadas y puntúa cada oferta según tu CV (tarda unos minutos).";
  }
  searchBtn.disabled = !jobsData.has_cv;
  updateJobsChip();
}

function jobCard(o) {
  const card = document.createElement("div");
  card.className = "job-card";
  const score = document.createElement("div");
  score.className = "job-score" + (o.puntuacion >= 70 ? " good" : o.puntuacion >= 50 ? " mid" : "");
  score.textContent = o.puntuacion;
  score.title = "Encaje con tu CV (0-100)";
  const title = document.createElement("div");
  title.className = "job-title";
  title.textContent = o.titulo;
  if (o.nueva) {
    const n = document.createElement("span");
    n.className = "new";
    n.textContent = "NUEVA";
    title.appendChild(n);
  }
  const meta = document.createElement("div");
  meta.className = "job-meta";
  meta.textContent = [o.empresa, o.ubicacion, "vía " + o.fuente].filter(Boolean).join(" · ");
  const why = document.createElement("div");
  why.className = "job-why";
  why.textContent = o.motivos;
  const actions = document.createElement("div");
  actions.className = "job-actions";
  const link = document.createElement("a");
  link.href = webUrl(o.url);
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "Ver oferta e inscribirme ↗";
  actions.appendChild(link);
  card.append(score, title, meta, why, actions);
  if (o.carta) {
    const letter = document.createElement("details");
    letter.className = "job-letter";
    const sum = document.createElement("summary");
    sum.textContent = "✉ Carta de presentación preparada (revísala antes de enviarla)";
    const ta = document.createElement("textarea");
    ta.value = o.carta;
    const copy = document.createElement("button");
    copy.className = "dc-btn";
    copy.textContent = "Copiar carta";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(ta.value); } catch (e) { ta.select(); document.execCommand("copy"); }
      copy.textContent = "Copiada ✓";
      setTimeout(() => { copy.textContent = "Copiar carta"; }, 1500);
    });
    letter.append(sum, ta, copy);
    card.appendChild(letter);
  }
  return card;
}

function renderJobs() {
  renderJobsStatus();
  const box = document.getElementById("jobsOffers");
  box.innerHTML = "";
  const res = jobsData.results || {};
  for (const w of res.warnings || []) {
    const div = document.createElement("div");
    div.className = "jobs-warn";
    div.textContent = "⚠ " + w;
    box.appendChild(div);
  }
  if (!res.run_at) {
    box.insertAdjacentHTML("beforeend", '<p class="personas-intro">Todavía no has buscado. Pulsa «Buscar ofertas»: ' +
      "Chati leerá tu CV, buscará en las webs de empleo, puntuará cada oferta y te preparará una carta de " +
      "presentación para las que mejor encajen. Inscribirte lo haces tú desde el enlace de cada oferta.</p>");
  } else {
    const head = document.createElement("div");
    head.className = "jobs-head";
    const when = new Date(res.run_at * 1000).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
    head.textContent = `Última búsqueda: ${when} · ${res.offers.length} ofertas, de más a menos encaje`;
    box.appendChild(head);
    for (const o of res.offers) box.appendChild(jobCard(o));
  }

  const pr = jobsData.prefs;
  document.getElementById("jobsPuestos").value = pr.puestos.join(", ");
  document.getElementById("jobsLugar").value = pr.lugar;
  document.getElementById("jobsPrefsText").value = pr.preferencias;
  document.getElementById("jobsMax").value = pr.max_ofertas;
  document.getElementById("jobsInternet").checked = pr.internet;
  renderJobSites();
}

function renderJobSites() {
  const box = document.getElementById("jobsSites");
  box.innerHTML = "";
  jobsData.prefs.sites.forEach((site, i) => {
    const row = document.createElement("div");
    row.className = "jobs-site";
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.style.width = "auto";
    chk.checked = site.enabled;
    chk.addEventListener("change", () => { site.enabled = chk.checked; });
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = site.name;
    const url = document.createElement("span");
    url.className = "url";
    url.textContent = site.url.includes("{puesto}") ? "búsqueda directa en la web" : "búsqueda con Bing dentro de " + site.url;
    const del = document.createElement("button");
    del.className = "sc-del";
    del.textContent = "Quitar";
    del.addEventListener("click", () => { jobsData.prefs.sites.splice(i, 1); renderJobSites(); });
    row.append(chk, name, url, del);
    box.appendChild(row);
  });
}

document.getElementById("jobsAddSiteBtn").addEventListener("click", () => {
  const input = document.getElementById("jobsNewSite");
  const url = input.value.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  if (!url) return;
  jobsData.prefs.sites.push({ name: url.replace(/^www\./, ""), url, enabled: true });
  input.value = "";
  renderJobSites();
  setProfileMsg("jobsWebsMsg", "Pulsa Guardar para quedártela.");
});

async function saveJobPrefs(msgId) {
  const pr = jobsData.prefs;
  pr.puestos = document.getElementById("jobsPuestos").value.split(",").map((x) => x.trim()).filter(Boolean);
  pr.lugar = document.getElementById("jobsLugar").value.trim();
  pr.preferencias = document.getElementById("jobsPrefsText").value.trim();
  pr.max_ofertas = parseInt(document.getElementById("jobsMax").value, 10) || 12;
  pr.internet = document.getElementById("jobsInternet").checked;
  const resp = await sendJSON("/jobs/prefs", { prefs: pr }, "PUT");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) { setProfileMsg(msgId, data.detail || "No se pudo guardar.", "error"); return false; }
  jobsData.prefs = data;
  renderJobSites();
  setProfileMsg(msgId, "Guardado ✓", "ok");
  return true;
}
document.getElementById("jobsSaveBuscoBtn").addEventListener("click", () => saveJobPrefs("jobsBuscoMsg"));
document.getElementById("jobsSaveWebsBtn").addEventListener("click", () => saveJobPrefs("jobsWebsMsg"));

document.getElementById("jobsSearchBtn").addEventListener("click", async () => {
  const btn = document.getElementById("jobsSearchBtn");
  btn.disabled = true;
  try {
    await agentPost("/jobs/search");
  } catch (err) {
    document.getElementById("jobsRunText").textContent = err.message;
    btn.disabled = false;
    return;
  }
  jobsData.status = { running: true, text: "Empezando…", started: Date.now() / 1000, done: 0, total: 0 };
  renderJobsStatus();
  followJobs();
});
document.getElementById("jobsCancelBtn").addEventListener("click", () => agentPost("/jobs/cancel").catch(silenced));

function followJobs() {
  if (jobsPoll) return;
  jobsPoll = setInterval(async () => {
    let st;
    try { st = await (await fetch("/jobs/status")).json(); } catch (e) { return; }
    jobsData.status = st;
    if (st.running) { if (jobsModal.style.display === "block") renderJobsStatus(); else updateJobsChip(); return; }
    clearInterval(jobsPoll);
    jobsPoll = null;
    await loadJobs().catch(silenced);
    if (jobsModal.style.display !== "block") {
      jobsUnseen = ((jobsData.results || {}).offers || []).filter((o) => o.nueva).length;
      updateJobsChip();
    }
  }, 2000);
}

