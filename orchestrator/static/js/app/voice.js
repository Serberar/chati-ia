// Chati web: grabar y enviar notas de voz.
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

async function toggleRecording() {
  if (!isRecording) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
      mediaRecorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        sendVoice(new Blob(audioChunks, { type: "audio/webm" }));
      };
      mediaRecorder.start();
      isRecording = true;
      micBtn.textContent = "Detener y enviar";
      micBtn.classList.add("recording");
    } catch (err) {
      alert("No se pudo acceder al microfono: " + err);
    }
  } else {
    mediaRecorder.stop();
    isRecording = false;
    micBtn.textContent = "Grabar";
    micBtn.classList.remove("recording");
  }
}

async function sendVoice(blob) {
  hideEmptyState();
  addMessage("user").textContent = "(mensaje de voz)";
  const bubble = addMessage("assistant", "voz");
  const stopTyping = startTypingIndicator(bubble);

  const form = new FormData();
  form.append("audio", blob, "recording.webm");
  const sid = getSessionId();
  if (sid) form.append("session_id", sid);

  try {
    const resp = await fetch("/voice_chat", { method: "POST", body: form });
    const data = await resp.json();
    setSessionId(data.session_id);

    const userMsgs = document.querySelectorAll(".msg.user .bubble");
    if (userMsgs.length) userMsgs[userMsgs.length - 1].textContent = data.transcript || "(no se entendio)";

    bubble.innerHTML = "";
    const tagWrap = bubble.parentElement.querySelector(".tag");
    if (tagWrap && data.agent_used) tagWrap.textContent = data.agent_used;
    if (data.verifier_gated) bubble.classList.add("gated");

    const textNode = document.createElement("div");
    textNode.textContent = data.response;
    bubble.appendChild(textNode);

    if (data.file_url) {
      const audio = document.createElement("audio");
      audio.src = data.file_url;
      audio.controls = true;
      audio.autoplay = true;
      bubble.appendChild(audio);
    }
  } catch (err) {
    bubble.className = "bubble error";
    bubble.textContent = "Error de conexion: " + err;
    reportClientError("Error de conexion (voz): " + err, "", err && err.stack);
  } finally {
    stopTyping();
  }
}

micBtn.addEventListener("click", toggleRecording);

function startTypingIndicator(bubble) {

  const startedAt = Date.now();
  bubble.innerHTML =
    '<div class="typing-wrap">' +
    '<span class="typing-dots"><span></span><span></span><span></span></span>' +
    '<span class="typing-elapsed"></span>' +
    '</div>';
  const tick = () => {
    const wrap = bubble.querySelector(".typing-wrap");
    if (!wrap) return false;
    const secs = Math.floor((Date.now() - startedAt) / 1000);
    const elapsedEl = wrap.querySelector(".typing-elapsed");
    if (elapsedEl) elapsedEl.textContent = secs >= 2 ? `${secs}s` : "";
    let hintEl = bubble.querySelector(".typing-hint");
    if (secs >= 20 && !hintEl) {
      hintEl = document.createElement("span");
      hintEl.className = "typing-hint";
      hintEl.textContent = "Algunos perfiles/modelos tardan bastante en CPU - sigue en marcha.";
      bubble.appendChild(hintEl);
    }
    return true;
  };
  tick();
  const interval = setInterval(() => { if (!tick()) clearInterval(interval); }, 1000);
  return () => clearInterval(interval);
}

