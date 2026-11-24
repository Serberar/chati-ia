// Chati web: perfil: avatar, nombre, contrasena y CV.
let currentMe = null;

let avatarUrl = null;

function paintAvatar(el, name) {
  el.innerHTML = "";
  if (avatarUrl) {
    const img = document.createElement("img");
    img.src = avatarUrl;
    img.alt = "";
    el.appendChild(img);
  } else {
    el.textContent = (name[0] || "?").toUpperCase();
  }
}

async function loadAvatar() {
  if (avatarUrl) { URL.revokeObjectURL(avatarUrl); avatarUrl = null; }
  if (currentMe && currentMe.role !== "guest") {
    try {
      const resp = await fetch("/profile/avatar");
      if (resp.ok) avatarUrl = URL.createObjectURL(await resp.blob());
    } catch (e) {  }
  }
  renderWhoami();
  if (profileModal.style.display === "block") fillProfile();
}

function renderWhoami() {
  const me = currentMe || {};
  const shown = me.display_name || me.username || "Invitado";
  document.getElementById("whoamiLabel").textContent = shown;
  paintAvatar(document.getElementById("whoamiAvatar"), shown);
  document.getElementById("whoamiRole").textContent =
    me.role === "admin" ? "Administrador" : me.role === "guest" ? "Modo invitado" : "Usuario";
}

const profileModal = document.getElementById("profileModal");

function showProfileTab(tab) {
  document.querySelectorAll(".profile-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".profile-pane").forEach((p) => { p.style.display = p.dataset.pane === tab ? "block" : "none"; });
}
document.querySelectorAll(".profile-tab").forEach((b) => b.addEventListener("click", () => showProfileTab(b.dataset.tab)));

function setProfileMsg(id, text, kind) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = "profile-msg" + (kind ? " " + kind : "");
}

function fillProfile() {
  const me = currentMe || {};
  const shown = me.display_name || me.username || "";
  paintAvatar(document.getElementById("profileAvatar"), shown);
  document.getElementById("avatarRemoveBtn").style.display = avatarUrl ? "inline" : "none";
  document.getElementById("avatarChangeBtn").textContent = avatarUrl ? "Cambiar foto" : "Subir foto";
  document.getElementById("profileNameLabel").textContent = shown;
  document.getElementById("profileUsernameLabel").textContent = me.username || "";
  document.getElementById("profileDisplayName").value = me.display_name || "";
  document.getElementById("profileQuestionInfo").textContent = me.security_question
    ? `Pregunta actual: "${me.security_question}". Sirve para recuperar el acceso si olvidas la contraseña.`
    : "No tienes pregunta de seguridad. Sin ella, si olvidas la contraseña no hay forma de recuperar la cuenta.";
  ["profileDatosMsg", "profilePasswordMsg", "profileQuestionMsg", "profileAvatarMsg"].forEach((id) => setProfileMsg(id, ""));
}

document.getElementById("profileBtn").addEventListener("click", () => {
  optionsModal.style.display = "none";
  fillProfile();
  showProfileTab("datos");
  profileModal.style.display = "block";
  loadCvStatus();
});
document.getElementById("closeProfileBtn").addEventListener("click", () => { profileModal.style.display = "none"; });
profileModal.addEventListener("click", (e) => { if (e.target === profileModal) profileModal.style.display = "none"; });

async function profilePost(url, body) {
  const resp = await sendJSON(url, body);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || "No se pudo guardar.");
  return data;
}

document.getElementById("saveDisplayNameBtn").addEventListener("click", async () => {
  const display_name = document.getElementById("profileDisplayName").value.trim();
  try {
    await profilePost("/auth/profile", { display_name });
  } catch (err) { setProfileMsg("profileDatosMsg", err.message, "error"); return; }
  currentMe.display_name = display_name || null;
  renderWhoami();
  fillProfile();
  setProfileMsg("profileDatosMsg", "Guardado ✓", "ok");
});

document.getElementById("submitChangePasswordBtn").addEventListener("click", async () => {
  const old_password = document.getElementById("oldPasswordInput").value;
  const new_password = document.getElementById("newPasswordInput").value;
  if (new_password !== document.getElementById("newPassword2Input").value) {
    setProfileMsg("profilePasswordMsg", "Las contraseñas nuevas no coinciden.", "error"); return;
  }
  setProfileMsg("profilePasswordMsg", "Cambiando...");
  let data;
  try {
    data = await profilePost("/auth/change-password", { old_password, new_password });
  } catch (err) { setProfileMsg("profilePasswordMsg", err.message, "error"); return; }
  setLoggedIn(getSessionRole());
  ["oldPasswordInput", "newPasswordInput", "newPassword2Input"].forEach((id) => { document.getElementById(id).value = ""; });
  setProfileMsg("profilePasswordMsg", "Contraseña cambiada ✓", "ok");
});

document.getElementById("saveSecurityQuestionBtn").addEventListener("click", async () => {
  const question = document.getElementById("securityQuestionInput").value.trim();
  const answer = document.getElementById("securityAnswerInput").value.trim();
  const password = document.getElementById("securityPasswordInput").value;
  setProfileMsg("profileQuestionMsg", "Guardando...");
  try {
    await profilePost("/auth/security-question", { question, answer, password });
  } catch (err) { setProfileMsg("profileQuestionMsg", err.message, "error"); return; }
  currentMe.security_question = question;
  ["securityQuestionInput", "securityAnswerInput", "securityPasswordInput"].forEach((id) => { document.getElementById(id).value = ""; });
  fillProfile();
  setProfileMsg("profileQuestionMsg", "Pregunta guardada ✓", "ok");
});

const avatarInput = document.getElementById("avatarInput");
document.getElementById("avatarChangeBtn").addEventListener("click", () => avatarInput.click());
avatarInput.addEventListener("change", async () => {
  const file = avatarInput.files[0];
  avatarInput.value = "";
  if (!file) return;
  setProfileMsg("profileAvatarMsg", "Subiendo...");
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/profile/avatar", { method: "POST", body: form });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    setProfileMsg("profileAvatarMsg", data.detail || "No se pudo subir la foto.", "error");
    return;
  }
  await loadAvatar();
  setProfileMsg("profileAvatarMsg", "Foto guardada ✓", "ok");
});
document.getElementById("avatarRemoveBtn").addEventListener("click", async () => {
  await fetch("/profile/avatar", { method: "DELETE" });
  await loadAvatar();
});

const cvInput = document.getElementById("cvInput");
const cvStatus = document.getElementById("cvStatus");
const cvUploadBtn = document.getElementById("cvUploadBtn");
cvUploadBtn.addEventListener("click", () => cvInput.click());

async function loadCvStatus() {
  if (getSessionRole() === "guest") return;
  try {
    const resp = await fetch("/cv");
    const data = await resp.json();
    cvStatus.textContent = data.has_cv ? data.filename : "Todavia no has subido tu CV";
    cvUploadBtn.textContent = data.has_cv ? "Sustituir" : "Subir CV";
  } catch (err) {  }
}

cvInput.addEventListener("change", async () => {
  if (!cvInput.files[0]) return;
  const form = new FormData();
  form.append("file", cvInput.files[0]);
  cvStatus.textContent = "Subiendo...";
  try {
    await fetch("/cv", { method: "POST", body: form });
    await loadCvStatus();
    if (jobsModal.style.display === "block") loadJobs().catch(() => {});
  } catch (err) {
    cvStatus.textContent = "Error subiendo el CV";
  }
  cvInput.value = "";
});

