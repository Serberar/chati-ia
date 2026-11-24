// Los scripts de static/js/app/ son clasicos (no modulos): comparten el ambito global y se cargan en el orden
// de index.html. Lo que se ejecuta al cargar solo puede usar lo declarado en scripts anteriores.
// Chati web: utilidades comunes, estado de sesion en localStorage, interceptor de fetch (401) y sendJSON.
try { localStorage.removeItem("ia_session_token"); } catch (e) { silenced(e); }
function isLoggedIn() {
  try { return localStorage.getItem("ia_logged_in") === "1"; } catch (e) { return false; }
}
function setLoggedIn(role) {
  try {
    localStorage.setItem("ia_logged_in", "1");
    localStorage.setItem("ia_session_role", role || "user");
  } catch (e) { silenced(e); }
}
function clearLoggedIn() {
  try {
    localStorage.removeItem("ia_logged_in");
    localStorage.removeItem("ia_session_role");

    localStorage.removeItem("ia_session_id");
    localStorage.removeItem("ia_code_project");
  } catch (e) { silenced(e); }
}
function getSessionRole() {
  try { return localStorage.getItem("ia_session_role") || "user"; } catch (e) { return "user"; }
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function webUrl(value) {
  const url = String(value || "").trim();
  return /^https?:\/\//i.test(url) ? url : "#";
}

const _originalFetch = window.fetch;
window.fetch = function (input, init) {
  return _originalFetch(input, init).then((resp) => {
    if (resp.status === 401) {
      clearLoggedIn();
      showLoginScreen("Tu sesion ha caducado. Inicia sesion de nuevo.");
    }
    return resp;
  });
};

// POST/PUT con cuerpo JSON. Las rutas de login pasan _originalFetch para no saltar el aviso de sesion caducada.
function sendJSON(url, body, method = "POST", send = fetch) {
  return send(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

