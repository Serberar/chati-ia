// Chati web: panel de administracion de usuarios.
const adminModal = document.getElementById("adminModal");
document.getElementById("adminBtn").addEventListener("click", async () => {
  optionsModal.style.display = "none";
  adminModal.style.display = "block";
  await loadAdminPanel();
});
document.getElementById("closeAdminBtn").addEventListener("click", () => { adminModal.style.display = "none"; });

async function loadAdminPanel() {
  const [usersResp, eventsResp, regKeyResp] = await Promise.all([
    fetch("/auth/users"), fetch("/auth/security-events"), fetch("/auth/registration-key"),
  ]);
  const usersData = await usersResp.json();
  const eventsData = await eventsResp.json();
  const regKeyData = await regKeyResp.json();
  document.getElementById("regKeyDisplay").textContent = regKeyData.registration_key;

  const meResp = await fetch("/auth/me");
  const me = await meResp.json();

  const usersBox = document.getElementById("adminUsersList");
  usersBox.innerHTML = usersData.users.map((u) => `
    <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-top:1px solid var(--border); font-size:13px;">
      <span>${esc(u.username)} <span style="color:var(--muted);">(${esc(u.role)})</span></span>
      ${u.role === "admin" ? "" : `<label title="Agente, leer archivos del ordenador y ejecutar código, con tus permisos de Windows" style="font-size:11.5px; color:var(--muted); display:flex; align-items:center; gap:4px; margin-left:auto; margin-right:8px;">
        <input type="checkbox" class="pcAccessChk" data-username="${esc(u.username)}" ${u.pc_access ? "checked" : ""}> Puede usar el ordenador</label>`}
      ${u.username === me.username ? "" : `<button data-username="${esc(u.username)}" class="deleteUserBtn" style="font-size:11px; padding:3px 8px; background:var(--error); color:white; border:none; border-radius:6px; cursor:pointer;">Eliminar</button>`}
    </div>
  `).join("") || '<div style="color:var(--muted); font-size:12px;">Sin usuarios.</div>';

  usersBox.querySelectorAll(".pcAccessChk").forEach((chk) => {
    chk.addEventListener("change", async () => {
      if (chk.checked && !confirm(`"${chk.dataset.username}" podrá usar el agente, leer tus archivos del Escritorio y Documentos y ejecutar código en este ordenador. ¿Seguro?`)) {
        chk.checked = false;
        return;
      }
      const resp = await sendJSON(`/auth/users/${encodeURIComponent(chk.dataset.username)}/pc_access`,
                                  { allowed: chk.checked }, "PUT");
      if (!resp.ok) { chk.checked = !chk.checked; alert("No se pudo cambiar el permiso."); }
    });
  });

  usersBox.querySelectorAll(".deleteUserBtn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`¿Eliminar la cuenta de "${btn.dataset.username}"? Se borraran tambien todos sus datos (conversaciones, caras, documentos). No se puede deshacer.`)) return;
      await fetch(`/auth/users/${encodeURIComponent(btn.dataset.username)}`, { method: "DELETE" });
      await loadAdminPanel();
    });
  });

  const eventsBox = document.getElementById("adminSecurityEvents");
  eventsBox.innerHTML = eventsData.events.slice().reverse().map((e) => `
    <div style="padding:4px 0; color:var(--muted);">${esc(e.at)} - ${esc(e.event)} (${esc(e.username)})</div>
  `).join("") || '<div style="color:var(--muted);">Sin eventos.</div>';
}

