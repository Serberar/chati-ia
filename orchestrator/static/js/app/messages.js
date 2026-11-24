// Chati web: pintar mensajes y enviar al chat.
function messageDate(createdAt) {
  if (!createdAt) return new Date();
  const d = new Date(String(createdAt).replace(" ", "T") + (String(createdAt).endsWith("Z") ? "" : "Z"));
  return isNaN(d) ? new Date() : d;
}

function dayLabel(d) {
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Hoy";
  if (d.toDateString() === yesterday.toDateString()) return "Ayer";
  return d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function stampMessage(wrap, roleEl, date) {
  const day = date.toDateString();
  const previous = [...log.querySelectorAll(".msg[data-day]")].pop();
  if (!previous || previous.dataset.day !== day) {
    const sep = document.createElement("div");
    sep.className = "day-sep";
    sep.textContent = dayLabel(date);
    log.appendChild(sep);
  }
  wrap.dataset.day = day;
  const time = document.createElement("span");
  time.className = "msg-time";
  time.textContent = date.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  time.title = date.toLocaleString("es-ES");
  roleEl.appendChild(time);
}

function addMessage(role, tag) {
  hideEmptyState();
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const roleEl = document.createElement("div");
  roleEl.className = "role";
  roleEl.textContent = role === "user" ? "Tu" : "Chati";
  stampMessage(wrap, roleEl, new Date());
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (tag) {
    const tagEl = document.createElement("span");
    tagEl.className = "tag";
    tagEl.textContent = tag;
    wrap.appendChild(roleEl);
    wrap.appendChild(tagEl);
  } else {
    wrap.appendChild(roleEl);
  }
  wrap.appendChild(bubble);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

async function send(retry = null) {
  const text = retry ? retry.text : promptEl.value.trim();
  if (!text) return;
  if (!retry) rememberPrompt(text);
  const modeKey = retry ? retry.mode : currentMode;
  const mode = MODES[modeKey];
  if (mode.isAgent) {
    promptEl.value = "";
    promptEl.style.height = "auto";
    await startAgentTask(text);
    return;
  }

  addMessage("user").textContent = text;
  const attachedImageB64 = retry ? retry.b64 : (mode.allowAttach ? visionImageBase64 : null);
  const attachedFile = retry ? retry.file : (mode.allowAttach ? visionImageInput.files[0] : null);
  const preview = retry ? retry.preview : (attachedImageB64 || attachedFile ? attachPreviewImg.src : null);
  if (preview) {
    const img = document.createElement("img");
    img.className = "attach";
    img.src = preview;
    log.lastElementChild.querySelector(".bubble").appendChild(img);
  }
  if (!retry) {
    promptEl.value = "";
    promptEl.style.height = "auto";
    visionImageBase64 = null;
    visionImageInput.value = "";
    attachPreviewRow.classList.remove("show");
  }
  sendBtn.disabled = true;


  currentAbort = new AbortController();
  currentAbortIsMedia = mode.agent === "image" || mode.agent === "video";
  const signal = currentAbort.signal;
  cancelBtn.style.display = "inline-block";

  const bubble = addMessage("assistant", "generando...");
  const stopTyping = startTypingIndicator(bubble);

  bubble._retry = { text, mode: modeKey, b64: attachedImageB64, file: attachedFile, preview };

  try {
    const imgForVision = mode.isText ? attachedImageB64 : null;
    await streamChatInto(bubble, mode.endpoint, text, mode.agent, imgForVision, signal);
  } catch (err) {
    if (err.name === "AbortError") {

      if (bubble.querySelector(".typing-wrap") || !bubble.textContent.trim()) bubble.textContent = "";
      const note = document.createElement("div");
      note.className = "stopped-note";
      note.textContent = "(detenido)";
      bubble.appendChild(note);
      if (currentAbortIsMedia) appendRetry(bubble);
    } else if (currentAbortIsMedia && getSessionId()) {

      reportClientError("Conexion cortada durante una generacion (se recupera): " + err, "modo " + modeKey, "");
      await waitForResult(bubble, getSessionId(), text);
    } else {
      bubble.className = "bubble error";
      bubble.textContent = "Error de conexion: " + err;
      reportClientError("Error de conexion al enviar: " + err, "modo " + modeKey, err && err.stack);
      appendRetry(bubble);
    }
  } finally {
    stopTyping();
    currentAbort = null;
    sendBtn.disabled = false;
    cancelBtn.style.display = "none";
    refreshBackgroundTasks();
  }
}

let currentAbort = null;
let currentAbortIsMedia = false;
cancelBtn.addEventListener("click", async () => {
  cancelBtn.disabled = true;
  cancelBtn.textContent = "Deteniendo…";

  if (currentAbortIsMedia) {
    try { await fetch("/cancel", { method: "POST" }); } catch (err) { silenced(err); }
  }
  if (currentAbort) currentAbort.abort();
  cancelBtn.disabled = false;
  cancelBtn.textContent = "■ Detener";
});

