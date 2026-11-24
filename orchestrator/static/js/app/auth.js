// Chati web: pantallas de login, registro y recuperar contrasena; arranque de la sesion.
const loginScreen = document.getElementById("loginScreen");
const loginSubtitle = document.getElementById("loginSubtitle");
const loginFormBox = document.getElementById("loginFormBox");
const registerFormBox = document.getElementById("registerFormBox");
const forgotFormBox = document.getElementById("forgotFormBox");

function showLoginScreen(message) {
  loginScreen.style.display = "flex";
  loginFormBox.classList.remove("hidden");
  registerFormBox.classList.add("hidden");
  forgotFormBox.classList.add("hidden");
  if (message) loginSubtitle.textContent = message;
}
function hideLoginScreen() {
  loginScreen.style.display = "none";
}

function enterSubmits(inputIds, buttonId) {
  inputIds.forEach((inputId) => {
    document.getElementById(inputId).addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      document.getElementById(buttonId).click();
    });
  });
}
enterSubmits(["loginUsername", "loginPassword"], "loginSubmitBtn");
enterSubmits(["regUsername", "regPassword", "regKey", "regQuestion", "regAnswer"], "registerSubmitBtn");
enterSubmits(["forgotUsername"], "forgotLoadQuestionBtn");
enterSubmits(["forgotAnswer", "forgotNewPassword"], "forgotSubmitBtn");

document.getElementById("loginSubmitBtn").addEventListener("click", async () => {
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  const errEl = document.getElementById("loginError");
  errEl.textContent = "";
  try {
    const remember = document.getElementById("loginRemember").checked;
    const resp = await sendJSON("/auth/login", { username, password, remember }, "POST", _originalFetch);
    const data = await resp.json();
    if (!resp.ok) { errEl.textContent = data.detail || "No se pudo iniciar sesion."; return; }
    setLoggedIn(data.role);
    hideLoginScreen();
    location.reload();
  } catch (e) { errEl.textContent = "No se pudo contactar con el servidor."; }
});

document.getElementById("guestBtn").addEventListener("click", async () => {
  const resp = await _originalFetch("/auth/guest", { method: "POST" });
  const data = await resp.json();
  setLoggedIn(data.role);
  hideLoginScreen();
  location.reload();
});

document.getElementById("showRegisterBtn").addEventListener("click", () => {
  loginFormBox.classList.add("hidden");
  registerFormBox.classList.remove("hidden");
});
document.getElementById("backToLoginFromRegisterBtn").addEventListener("click", () => {
  registerFormBox.classList.add("hidden");
  loginFormBox.classList.remove("hidden");
});

document.getElementById("registerSubmitBtn").addEventListener("click", async () => {
  const body = {
    username: document.getElementById("regUsername").value.trim(),
    password: document.getElementById("regPassword").value,
    registration_key: document.getElementById("regKey").value.trim(),
    security_question: document.getElementById("regQuestion").value.trim() || null,
    security_answer: document.getElementById("regAnswer").value.trim() || null,
  };
  const errEl = document.getElementById("registerError");
  errEl.textContent = "";
  const resp = await sendJSON("/auth/register", body, "POST", _originalFetch);
  const data = await resp.json();
  if (!resp.ok) { errEl.textContent = data.detail || "No se pudo crear la cuenta."; return; }
  setLoggedIn(data.role);
  hideLoginScreen();
  location.reload();
});

document.getElementById("showForgotBtn").addEventListener("click", () => {
  loginFormBox.classList.add("hidden");
  forgotFormBox.classList.remove("hidden");
});
document.getElementById("backToLoginFromForgotBtn").addEventListener("click", () => {
  forgotFormBox.classList.add("hidden");
  loginFormBox.classList.remove("hidden");
});

document.getElementById("forgotLoadQuestionBtn").addEventListener("click", async () => {
  const username = document.getElementById("forgotUsername").value.trim();
  const errEl = document.getElementById("forgotError");
  errEl.textContent = "";
  const resp = await _originalFetch(`/auth/security-question/${encodeURIComponent(username)}`);
  const data = await resp.json();
  if (!resp.ok) { errEl.textContent = data.detail || "No se encontro la pregunta."; return; }
  document.getElementById("forgotQuestionText").textContent = data.security_question;
  document.getElementById("forgotAnswer").classList.remove("hidden");
  document.getElementById("forgotNewPassword").classList.remove("hidden");
  document.getElementById("forgotSubmitBtn").classList.remove("hidden");
  document.getElementById("forgotWarning").textContent =
    "Aviso: si respondes bien, entraras con una cuenta limpia. Tus conversaciones e imagenes cifradas con la contraseña anterior quedaran inaccesibles para siempre (no hay forma de recuperarlas).";
});

document.getElementById("forgotSubmitBtn").addEventListener("click", async () => {
  const body = {
    username: document.getElementById("forgotUsername").value.trim(),
    security_answer: document.getElementById("forgotAnswer").value,
    new_password: document.getElementById("forgotNewPassword").value,
  };
  const errEl = document.getElementById("forgotError");
  errEl.textContent = "";
  const resp = await sendJSON("/auth/reset-password", body, "POST", _originalFetch);
  const data = await resp.json();
  if (!resp.ok) { errEl.textContent = data.detail || "No se pudo restablecer."; return; }
  notify("Contraseña restablecida. Inicia sesion con la nueva contraseña.");
  forgotFormBox.classList.add("hidden");
  loginFormBox.classList.remove("hidden");
});

if (!isLoggedIn()) {
  showLoginScreen();
}

function addPasswordToggles() {
  document.querySelectorAll('input[type="password"]:not([data-pw-eye])').forEach((input) => {
    input.dataset.pwEye = "1";
    const wrap = document.createElement("span");
    wrap.className = "pw-wrap";

    const margin = getComputedStyle(input).marginBottom;
    wrap.style.marginBottom = margin;
    input.style.marginBottom = "0";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const eye = document.createElement("button");
    eye.type = "button";
    eye.className = "pw-eye";
    eye.tabIndex = -1;
    const sync = () => {
      const shown = input.type === "text";
      eye.textContent = shown ? "🙈" : "👁";
      eye.title = shown ? "Ocultar contraseña" : "Mostrar contraseña";
    };
    eye.addEventListener("click", () => {
      input.type = input.type === "password" ? "text" : "password";
      sync();
      input.focus();
    });
    sync();
    wrap.appendChild(eye);
  });
}
addPasswordToggles();

function setupOpenInBrowser() {
  const btn = document.getElementById("openInBrowserBtn");
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.open_in_browser) return;
  btn.style.display = "block";
  btn.onclick = () => api.open_in_browser();
}
window.addEventListener("pywebviewready", setupOpenInBrowser);
setupOpenInBrowser();

async function initSessionUI() {
  if (!isLoggedIn()) return;
  const resp = await fetch("/auth/me");
  if (!resp.ok) { clearLoggedIn(); showLoginScreen(); return; }
  const me = await resp.json();
  setLoggedIn(me.role);

  currentMe = me;
  document.getElementById("appVersion").textContent = me.version;
  loadAvatar();
  isAdminUser = me.role === "admin";
  if (me.role === "admin") document.getElementById("adminBtn").style.display = "";
  if (me.role === "admin") document.getElementById("optErrorsBtn").style.display = "";
  if (me.role === "admin") setupAppUpdates();
  if (me.role === "admin" && ["127.0.0.1", "localhost"].includes(location.hostname)) setupAutostart();

  if (me.role !== "admin") document.getElementById("optMetricsBtn").style.display = "none";

  if (me.role === "admin" && ["127.0.0.1", "localhost"].includes(location.hostname)) {

    const link = document.getElementById("optCodeAgentLink");
    link.style.display = "";
    link.addEventListener("click", async () => {
      try {
        const r = await fetch("/agent/web-login");
        if (!r.ok) return;
        const cred = await r.json();
        await navigator.clipboard.writeText(cred.password);
        notify(`OpenCode pide usuario y contraseña.
Usuario: ${cred.user}
La contraseña ya está copiada: pégala con Ctrl+V.`);
      } catch (e) { silenced(e); }
    });
  }
  if (!me.pc_access) {

    for (const value of ["agente", "codigo"]) {
      const opt = document.querySelector(`#modeSelect option[value="${value}"]`);
      if (opt) opt.remove();
    }
    if (currentMode === "agente" || currentMode === "codigo") {
      document.getElementById("modeSelect").value = "chat";
      document.getElementById("modeSelect").dispatchEvent(new Event("change"));
    }
  }
  if (me.role === "guest") {
    document.getElementById("optMemoryBtn").style.display = "none";
    document.getElementById("knowledgeBtn").style.display = "none";
    document.getElementById("profileBtn").style.display = "none";
    document.getElementById("newChatBtn").style.display = "none";
    document.getElementById("convSectionLabel").style.display = "none";
    document.getElementById("convList").innerHTML = '<div id="convEmpty">Modo invitado: sin historial guardado.</div>';
  } else {
    await loadConversations();
  }
}

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST" });
  clearLoggedIn();
  location.reload();
});

