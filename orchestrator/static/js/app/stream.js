// Chati web: respuesta del chat en streaming, reintentar, compartir y descargar.
async function streamChatInto(bubble, endpoint, text, agentOverride, imageBase64, signal) {
  const body = { message: text, agent: agentOverride || null, session_id: getSessionId(), verify: verifyToggle.checked };
  if (MODES[currentMode].isText && profileSelect.value) body.model_profile = profileSelect.value;
  if (imageBase64) body.image_base64 = imageBase64;
  if (currentMode === "image" && modelSelect.value) body.image_model = modelSelect.value;
  if (currentMode === "video" && modelSelect.value) body.video_model = modelSelect.value;

  const resp = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    bubble.className = "bubble error";
    bubble.textContent = "Error de conexion (" + resp.status + ")";
    return;
  }

  let textNode = null;
  let liveText = "";
  let finalData = null;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      let evt;
      try { evt = JSON.parse(line); } catch (e) { continue; }
      if (evt.type === "status") {

        const wrap = bubble.querySelector(".typing-wrap");
        if (wrap) {
          let st = bubble.querySelector(".typing-status");
          if (!st) {
            st = document.createElement("div");
            st.className = "typing-status";
            wrap.after(st);
          }
          st.textContent = evt.text;
        }
      } else if (evt.type === "start") {
        setSessionId(evt.session_id);
        const tagWrap = bubble.parentElement.querySelector(".tag");
        if (tagWrap) tagWrap.textContent = evt.agent_used;
        if (["image", "video"].includes(evt.agent_used)) {
          cancelBtn.style.display = "inline-block";
          currentAbortIsMedia = true;
        }
      } else if (evt.type === "chunk") {
        if (!textNode) {
          bubble.innerHTML = "";
          textNode = document.createElement("div");
          bubble.appendChild(textNode);
        }
        liveText += evt.text;
        renderMarkdownInto(textNode, liveText, { highlight: false });
        log.scrollTop = log.scrollHeight;
      } else if (evt.type === "done") {
        finalData = evt;
      }
    }
  }

  if (!finalData && currentAbortIsMedia && getSessionId()) {
    reportClientError("Conexion cerrada sin resultado durante una generacion (se recupera)", "", "");
    await waitForResult(bubble, getSessionId(), text);
    return;
  }

  if (!textNode) {
    bubble.innerHTML = "";
    textNode = document.createElement("div");
    bubble.appendChild(textNode);
  }

  if (finalData) {
    setSessionId(finalData.session_id);
    refreshPlan();
    refreshModelStatus();
    const shown = (!liveText || finalData.corrected) ? finalData.response : liveText;
    renderMarkdownInto(textNode, shown, { highlight: true });
    if (finalData.verifier_gated) bubble.classList.add("gated");
    if (finalData.verifier_reason) {
      const reasonNode = document.createElement("div");
      reasonNode.style.fontSize = "12px";
      reasonNode.style.color = "var(--warn)";
      reasonNode.style.marginTop = "6px";
      reasonNode.textContent = "Verificador: " + finalData.verifier_reason;
      bubble.appendChild(reasonNode);
    }
    if (finalData.file_url) {
      appendMediaWithActions(bubble, finalData.file_url, finalData.file_path);
    } else if (isRetryable(finalData.response)) {
      appendRetry(bubble);
    }

    if (finalData.agent_task_id) openAgentView(finalData.agent_task_id, Date.now());
    if (finalData.agent_choice) renderAgentChoice(finalData.agent_choice.task, finalData.agent_choice.reason);
  }
}

function renderResult(bubble, data) {
  setSessionId(data.session_id);
  refreshPlan();
  bubble.innerHTML = "";
  const tagWrap = bubble.parentElement.querySelector(".tag");
  if (tagWrap) tagWrap.textContent = data.agent_used;

  if (data.verifier_gated) bubble.classList.add("gated");

  const textNode = document.createElement("div");
  renderMarkdownInto(textNode, data.response, { highlight: true });
  bubble.appendChild(textNode);

  if (data.verifier_reason) {
    const reasonNode = document.createElement("div");
    reasonNode.style.fontSize = "12px";
    reasonNode.style.color = "var(--warn)";
    reasonNode.style.marginTop = "6px";
    reasonNode.textContent = "Verificador: " + data.verifier_reason;
    bubble.appendChild(reasonNode);
  }

  if (data.file_url) {
    appendMediaWithActions(bubble, data.file_url, data.file_path);
  } else if (isRetryable(data.response)) {
    appendRetry(bubble);
  }
}

async function waitForResult(bubble, sid, text) {
  bubble.className = "bubble";
  bubble.textContent = "generando...";
  const stopTyping = startTypingIndicator(bubble);
  const until = Date.now() + 40 * 60 * 1000;
  try {
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, 4000));
      let messages;
      try { messages = await (await fetch(`/sessions/${sid}`)).json(); } catch (e) { continue; }
      if (!Array.isArray(messages)) continue;
      let i = messages.length - 1;
      while (i >= 0 && !(messages[i].role === "user" && messages[i].content === text)) i--;
      const answer = i >= 0 ? messages.slice(i + 1).find((m) => m.role === "assistant") : null;
      if (!answer) continue;
      stopTyping();
      bubble.innerHTML = "";
      const textNode = document.createElement("div");
      renderMarkdownInto(textNode, answer.content, { highlight: true });
      bubble.appendChild(textNode);
      if (answer.media && /^[0-9a-f]{32}\.(png|jpg|webp|mp4)$/.test(answer.media)) {
        appendMediaWithActions(bubble, "/media/" + answer.media, answer.media);
      } else if (isRetryable(answer.content)) {
        appendRetry(bubble);
      }
      refreshPlan();
      return;
    }
    bubble.textContent = "No ha llegado el resultado. Mira la conversación en un rato.";
    appendRetry(bubble);
  } finally {
    stopTyping();
  }
}

const RETRYABLE = /^(Se ha cancelado la generación|No ha terminado a tiempo|No se ha podido terminar)/;

function isRetryable(text) {
  return RETRYABLE.test((text || "").trim());
}

function appendRetry(bubble) {
  const ctx = bubble._retry;
  if (!ctx || bubble.querySelector(".retry-actions")) return;
  const row = document.createElement("div");
  row.className = "media-actions retry-actions";
  const btn = document.createElement("button");
  btn.textContent = "↻ Reintentar";
  btn.title = `Volver a pedir "${ctx.text}"`;
  btn.addEventListener("click", () => {
    if (sendBtn.disabled) return;
    send(ctx);
  });
  row.appendChild(btn);
  bubble.appendChild(row);
}

function mediaFileName(fileUrl) {
  return fileUrl.split("?")[0].split("/").pop() || "chati";
}

function downloadButton(fileUrl) {

  const b = document.createElement("button");
  b.textContent = "⬇ Descargar";
  b.title = "Guardar el archivo";
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const blob = await (await fetch(fileUrl)).blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = mediaFileName(fileUrl);
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      alert("No se pudo descargar: " + (err.message || err));
    } finally {
      b.disabled = false;
    }
  });
  return b;
}

function shareButton(fileUrl) {

  if (!navigator.share || !navigator.canShare) return null;
  const b = document.createElement("button");
  b.textContent = "↗ Compartir";
  b.title = "Enviar o guardar en Fotos";
  b.addEventListener("click", async () => {
    try {
      const blob = await (await fetch(fileUrl)).blob();
      const file = new File([blob], mediaFileName(fileUrl), { type: blob.type });
      if (!navigator.canShare({ files: [file] })) throw new Error("este navegador no puede compartir archivos");
      await navigator.share({ files: [file] });
    } catch (err) {
      if (err && err.name !== "AbortError") alert("No se pudo compartir: " + (err.message || err));
    }
  });
  return b;
}

function appendMediaWithActions(bubble, fileUrl) {
  const actionsRow = document.createElement("div");
  actionsRow.className = "media-actions";
  actionsRow.appendChild(downloadButton(fileUrl));
  const share = shareButton(fileUrl);
  if (share) actionsRow.appendChild(share);

  if (fileUrl.endsWith(".mp4")) {
    const vid = document.createElement("video");
    vid.src = fileUrl;
    vid.controls = true;
    vid.autoplay = true;
    vid.loop = true;
    bubble.append(vid, actionsRow);
    return;
  }

  const img = document.createElement("img");
  img.className = "attach";
  img.src = fileUrl;
  bubble.append(img, actionsRow);
}

