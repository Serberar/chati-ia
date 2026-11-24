// Chati web: avisos, preguntas y textos dentro de la propia página.
function silenced(error) {
  // No afecta a quien usa Chati, pero queda a la vista al depurar.
  console.debug("Ignorado:", error);
}

function notify(text) {
  const box = document.createElement("div");
  box.className = "notice";
  box.setAttribute("role", "status");
  box.textContent = text;
  box.addEventListener("click", () => box.remove());
  let stack = document.getElementById("noticeStack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "noticeStack";
    document.body.appendChild(stack);
  }
  stack.appendChild(box);
  setTimeout(() => box.remove(), Math.min(15000, 4000 + text.length * 50));
}

function openDialog(text, input) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "ask";
    const form = document.createElement("form");
    form.method = "dialog";
    const message = document.createElement("p");
    message.textContent = text;
    const row = document.createElement("div");
    row.className = "ask-actions";
    for (const [value, label] of [["no", "Cancelar"], ["yes", "Aceptar"]]) {
      const btn = document.createElement("button");
      btn.value = value;
      btn.textContent = label;
      if (value === "no") btn.formNoValidate = true;
      row.appendChild(btn);
    }
    form.append(message, ...(input ? [input] : []), row);
    dialog.appendChild(form);
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve(dialog.returnValue === "yes");
    });
    document.body.appendChild(dialog);
    dialog.showModal();
    (input || row.lastElementChild).focus();
  });
}

function askConfirm(text) {
  return openDialog(text);
}

async function askText(text) {
  const input = document.createElement("input");
  input.autocomplete = "off";
  return (await openDialog(text, input)) ? input.value : null;
}
