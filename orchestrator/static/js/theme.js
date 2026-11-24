function reportClientError(message, source, stack) {
  try {
    const body = JSON.stringify({
      message: String(message || "").slice(0, 2000),
      source: String(source || "").slice(0, 300),
      stack: String(stack || "").slice(0, 4000),
      page: (location.pathname + " · " + navigator.userAgent).slice(0, 300),
    });
    fetch("/client-log", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true })
      .catch(() => {});
  } catch (e) { console.debug(e); }
}
window.addEventListener("error", (e) => {
  reportClientError(e.message, `${e.filename || ""}:${e.lineno || ""}:${e.colno || ""}`, e.error && e.error.stack);
});
window.addEventListener("unhandledrejection", (e) => {
  const r = e.reason || {};
  reportClientError("Promesa sin capturar: " + (r.message || r), "", r.stack);
});

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("themeToggle").innerHTML = theme === "light" ? "&#9788;" : "&#9789;";
}
function initTheme() {
  const saved = localStorage.getItem("ia_theme") || "dark";
  applyTheme(saved);
}
document.getElementById("themeToggle").addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "light" ? "dark" : "light";
  localStorage.setItem("ia_theme", next);
  applyTheme(next);
});
initTheme();

function setSidebarHidden(hidden) {
  document.body.classList.toggle("sidebar-hidden", hidden);
  try { localStorage.setItem("ia_sidebar_hidden", hidden ? "1" : "0"); } catch (e) { console.debug(e); }
}

const mobileQuery = window.matchMedia("(max-width: 760px)");
function setMobileMenu(open) {
  document.body.classList.toggle("mobile-menu-open", open);
}
const mobileBackdrop = document.createElement("div");
mobileBackdrop.id = "mobileBackdrop";
document.body.appendChild(mobileBackdrop);
mobileBackdrop.addEventListener("click", () => setMobileMenu(false));
document.getElementById("sidebar").addEventListener("click", (e) => {
  if (!mobileQuery.matches) return;
  const pickedConversation = e.target.closest(".conv-row") && !e.target.closest(".conv-rename, .conv-del, input");
  if (pickedConversation || e.target.closest("#newChatBtn, #optionsBtn, #appsBtn")) setMobileMenu(false);
});
mobileQuery.addEventListener("change", () => setMobileMenu(false));

document.getElementById("sidebarHideBtn").addEventListener("click", () => {
  if (mobileQuery.matches) setMobileMenu(false); else setSidebarHidden(true);
});
document.getElementById("sidebarShowBtn").addEventListener("click", () => {
  if (mobileQuery.matches) setMobileMenu(true); else setSidebarHidden(false);
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
    e.preventDefault();
    setSidebarHidden(!document.body.classList.contains("sidebar-hidden"));
  }
});
try { if (localStorage.getItem("ia_sidebar_hidden") === "1") document.body.classList.add("sidebar-hidden"); } catch (e) { console.debug(e); }
