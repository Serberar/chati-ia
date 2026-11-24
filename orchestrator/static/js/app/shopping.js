// Chati web: busqueda de compras.
const shopModal = document.getElementById("shopModal");
let shopData = { history: [], status: { running: false } };
let shopPoll = null;
let shopPhotoB64 = null;
let shopShownId = null;
let shopUnseen = false;

function shopMoney(v, cur) {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (cur && cur !== "EUR" ? " " + cur : " €");
}

async function loadShopping() {
  const resp = await fetch("/shopping");
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || resp.status);
  shopData = data;
  renderShopHistory();
  renderShopStatus();
}

function openShopModal() {
  shopUnseen = false;
  shopModal.style.display = "block";
  document.getElementById("shopRunText").textContent = "Cargando…";
  loadShopping().then(() => {
    const st = shopData.status || {};
    if (!st.running && !shopShownId && shopData.history.length) showShopResult(shopData.history[0].id);
    if (st.running) followShopping();
  }).catch((err) => { document.getElementById("shopRunText").textContent = "Error: " + err.message; });
}
document.getElementById("closeShopBtn").addEventListener("click", () => { shopModal.style.display = "none"; updateJobsChip(); });

function renderShopHistory() {
  const sel = document.getElementById("shopHistory");
  sel.innerHTML = '<option value="">Búsquedas anteriores…</option>';
  for (const h of shopData.history) {
    const opt = document.createElement("option");
    opt.value = h.id;
    const when = new Date(h.fecha * 1000).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });
    opt.textContent = `${h.producto} · ${when}`;
    sel.appendChild(opt);
  }
  sel.value = shopShownId || "";
}
document.getElementById("shopHistory").addEventListener("change", (e) => { if (e.target.value) showShopResult(e.target.value); });

function renderShopStatus() {
  const st = shopData.status || {};
  const text = document.getElementById("shopRunText");
  const bar = document.getElementById("shopRunBar");
  document.getElementById("shopSearchBtn").style.display = st.running ? "none" : "inline-block";
  document.getElementById("shopCancelBtn").style.display = st.running ? "inline-block" : "none";
  bar.style.display = st.running && st.total ? "block" : "none";
  if (st.running) {
    const secs = Math.floor(Date.now() / 1000 - st.started);
    const mins = secs >= 60 ? `${Math.floor(secs / 60)} min ${secs % 60}s` : `${secs}s`;
    text.textContent = `${st.text} (${mins}) · puedes cerrar esta ventana, sigue buscando`;
    bar.firstElementChild.style.width = st.total ? `${Math.round(100 * st.done / st.total)}%` : "0";
  } else if (st.error) {
    text.textContent = st.error;
  } else {
    text.textContent = "Busca en todo internet, lee cada tienda y ordena por precio (tarda unos minutos).";
  }
  updateJobsChip();
}

function shopOfferRow(o, cls) {
  const row = document.createElement("div");
  row.className = cls;
  if (o.imagen) {
    const img = document.createElement("img");
    img.src = webUrl(o.imagen);
    img.loading = "lazy";
    img.onerror = () => img.remove();
    row.appendChild(img);
  }
  const info = document.createElement("div");
  info.className = "info";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = o.nombre;
  name.title = o.nombre;
  if (o.sospechoso) name.insertAdjacentHTML("beforeend", '<span class="shop-flag warn" title="Mucho más barato que el resto: comprueba que la tienda es de fiar">PRECIO SOSPECHOSO</span>');
  if (!o.disponible) name.insertAdjacentHTML("beforeend", '<span class="shop-flag off">AGOTADO</span>');
  const meta = document.createElement("div");
  meta.className = "meta";
  const envio = o.coste_envio === 0 ? "envío gratis" : o.coste_envio ? `envío ${shopMoney(o.coste_envio, o.moneda)}`
    : o.envio_espana === "si" ? "envía a España" : o.envio_espana === "no" ? "no envía a España" : "envío: ?";
  const rating = o.valoracion ? `★ ${o.valoracion.toFixed(1)}` + (o.opiniones ? ` (${o.opiniones})` : "") : "";
  meta.textContent = [o.tienda, envio, rating, o.estado !== "nuevo" ? o.estado : ""].filter(Boolean).join(" · ");
  info.append(name, meta);
  const price = document.createElement("div");
  price.className = "shop-price";
  price.textContent = shopMoney(o.precio, o.moneda);
  const link = document.createElement("a");
  link.href = webUrl(o.url);
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "Ver en la tienda ↗";
  row.append(info, price, link);
  return { row, info };
}

function showShopResult(id) {
  const h = shopData.history.find((x) => x.id === id);
  const box = document.getElementById("shopResults");
  box.innerHTML = "";
  shopShownId = id;
  renderShopHistory();
  if (!h) return;
  const head = document.createElement("div");
  head.className = "shop-head";
  const f = h.peticion;
  const rango = f.precio_min !== null || f.precio_max !== null
    ? ` · ${f.precio_min !== null ? shopMoney(f.precio_min) : "0 €"} – ${f.precio_max !== null ? shopMoney(f.precio_max) : "sin límite"}` : "";
  head.textContent = `«${h.producto}»${rango} · ${h.ofertas.length} ofertas de ${h.revisadas} páginas revisadas`
    + (h.descripcion_foto ? ` · en la foto: ${h.descripcion_foto}` : "");
  box.appendChild(head);
  for (const w of h.avisos || []) {
    const div = document.createElement("div");
    div.className = "jobs-warn";
    div.textContent = "⚠ " + w;
    box.appendChild(div);
  }
  if (h.recomendadas.length) {
    const t = document.createElement("div");
    t.className = "shop-section";
    t.textContent = "Recomendadas";
    box.appendChild(t);
    for (const r of h.recomendadas) {
      const o = h.ofertas.find((x) => x.url === r.url);
      if (!o) continue;
      const { row, info } = shopOfferRow(o, "shop-rec");
      const why = document.createElement("div");
      why.className = "why";
      why.textContent = r.por_que;
      info.appendChild(why);
      box.appendChild(row);
    }
  }
  if (h.ofertas.length) {
    const t = document.createElement("div");
    t.className = "shop-section";
    t.textContent = "Todas, de más barata a más cara";
    box.appendChild(t);
    for (const o of h.ofertas) box.appendChild(shopOfferRow(o, "shop-item").row);
  } else {
    box.insertAdjacentHTML("beforeend", '<p class="personas-intro">No se encontró nada que cumpla lo pedido. Prueba a describirlo de otra forma o a quitar filtros.</p>');
  }
}

document.getElementById("shopPhotoBtn").addEventListener("click", () => document.getElementById("shopPhotoInput").click());
document.getElementById("shopPhotoInput").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    shopPhotoB64 = String(reader.result).split(",")[1];
    const img = document.getElementById("shopPhotoPreview");
    img.src = reader.result;
    img.style.display = "inline";
    document.getElementById("shopPhotoClear").style.display = "inline";
  };
  reader.readAsDataURL(file);
  e.target.value = "";
});
document.getElementById("shopPhotoClear").addEventListener("click", () => {
  shopPhotoB64 = null;
  document.getElementById("shopPhotoPreview").style.display = "none";
  document.getElementById("shopPhotoClear").style.display = "none";
});

document.getElementById("shopSearchBtn").addEventListener("click", async () => {
  const body = {
    descripcion: document.getElementById("shopDesc").value.trim(),
    image_base64: shopPhotoB64,
    precio_min: document.getElementById("shopMin").value || null,
    precio_max: document.getElementById("shopMax").value || null,
    solo_espana: document.getElementById("shopSpain").checked,
    valoraciones: document.getElementById("shopRatings").checked,
  };
  try {
    await agentPost("/shopping/search", body);
  } catch (err) {
    document.getElementById("shopRunText").textContent = err.message;
    return;
  }
  shopData.status = { running: true, text: "Empezando…", started: Date.now() / 1000, done: 0, total: 0 };
  renderShopStatus();
  followShopping();
});
document.getElementById("shopCancelBtn").addEventListener("click", () => agentPost("/shopping/cancel").catch(() => {}));

function followShopping() {
  if (shopPoll) return;
  shopPoll = setInterval(async () => {
    let st;
    try { st = await (await fetch("/shopping/status")).json(); } catch (e) { return; }
    shopData.status = st;
    if (st.running) { renderShopStatus(); return; }
    clearInterval(shopPoll);
    shopPoll = null;
    await loadShopping().catch(() => {});
    if (st.last_id && !st.error) {
      showShopResult(st.last_id);
      if (shopModal.style.display !== "block") shopUnseen = true;
    }
    updateJobsChip();
  }, 2000);
}

const jobsModal = document.getElementById("jobsModal");
let jobsData = null;
let jobsPoll = null;
let jobsUnseen = 0;

function updateJobsChip() {
  const running = jobsData && jobsData.status && jobsData.status.running;
  const note = running ? "buscando…" : jobsUnseen ? `${jobsUnseen} ofertas nuevas` : "";
  const shopRunning = shopData.status && shopData.status.running;
  const shopNote = shopRunning ? "comparando precios…" : shopUnseen ? "resultados listos" : "";
  const deepRunning = deepData.status && deepData.status.running;
  const deepNote = deepRunning ? "buscando a fondo…" : deepUnseen ? "búsqueda lista" : "";
  document.getElementById("appDeepDesc").textContent = deepNote ? `🔎 ${deepNote[0].toUpperCase()}${deepNote.slice(1)}`
    : "Pídele lo que quieras encontrar en internet y se lo curra: casas, coches, cursos, información…";
  const all = note || shopNote || deepNote;
  document.getElementById("appsBtn").textContent = "🧩 Mis apps" + (all ? ` · ${all}` : "");
  document.getElementById("appJobsDesc").textContent = note ? `💼 ${note[0].toUpperCase()}${note.slice(1)}`
    : "Busca ofertas según tu CV, las puntúa y te prepara las cartas de presentación.";
  document.getElementById("appShopDesc").textContent = shopNote ? `🛒 ${shopNote[0].toUpperCase()}${shopNote.slice(1)}`
    : "Dile qué buscas (o pásale una foto) y compara precios en todo internet.";
}

