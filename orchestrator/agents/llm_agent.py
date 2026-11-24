import base64
import io
import re
from collections.abc import Callable, Iterator

import pillow_heif
from PIL import Image, UnidentifiedImageError

from agents.ollama_client import OllamaClient

pillow_heif.register_heif_opener()


class InvalidImageError(Exception):
    pass


def _normalize_image_for_vision(image_base64: str, max_dimension: int = 1568) -> str:
    try:
        raw = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (base64.binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError(f"No se pudo leer la imagen: {exc}") from exc

    img = img.convert("RGB")
    if max(img.size) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return base64.b64encode(out.getvalue()).decode()

_FALLBACK_FUNCTION_RE = re.compile(r"<function=([\w_]+)>(.*?)</function>", re.DOTALL)
_FALLBACK_PARAM_RE = re.compile(r"<parameter=([\w_]+)>\s*(.*?)\s*</parameter>", re.DOTALL)


_FALLBACK_MARK = "<function="


def _visible_prefix_end(content: str) -> int:
    cut = content.find(_FALLBACK_MARK)
    if cut != -1:
        return cut
    for k in range(min(len(_FALLBACK_MARK) - 1, len(content)), 0, -1):
        if content.endswith(_FALLBACK_MARK[:k]):
            return len(content) - k
    return len(content)


def _parse_fallback_tool_call(content: str) -> dict | None:
    match = _FALLBACK_FUNCTION_RE.search(content or "")
    if not match:
        return None
    name, params_block = match.group(1), match.group(2)
    arguments = {k: v for k, v in _FALLBACK_PARAM_RE.findall(params_block)}
    return {"function": {"name": name, "arguments": arguments}}

LANGUAGE_RULE = ("Responde SIEMPRE en español, sin excepcion, sin importar el idioma del contexto recuperado. "
                 "Nunca cambies de idioma a mitad de la respuesta (ni al chino ni a ningun otro).")

CHATI_MODES_NOTE = (
    "Eres el chat de Chati. Chati tiene otros modos, que el usuario elige en el selector "
    "Modo de la izquierda: Imagen (crear imagenes), Video, Voz, Agente de codigo (crear, "
    "mover u ordenar archivos del ordenador) y Automatico (elige el modo solo). Tu no puedes "
    "crear imagenes ni videos ni cambiar archivos: si te lo piden, dile en una frase que "
    "cambie a ese modo (o a Automatico) y vuelva a pedirlo alli. No ofrezcas otros servicios "
    "ni digas que lo vas a hacer. ")

MAX_TOOL_ITERATIONS = 4
TOOL_DECISION_TEMPERATURE = 0.1

SYSTEM_PROMPTS = {
    "text": (
        CHATI_MODES_NOTE +
        "Eres un asistente conversacional honesto. Si no sabes algo con certeza, "
        "dilo explicitamente en vez de inventar una respuesta. No des cifras, "
        "fechas ni datos especificos que no puedas verificar. Si tienes herramientas "
        "disponibles (fecha actual, busqueda en memoria, documentos "
        "guardadas, leer archivos del Escritorio/Documentos), usalas en vez de "
        "adivinar cuando la pregunta dependa de ese dato. Si una tarea tiene mas "
        "de 2-3 pasos, usa actualizar_plan para que el usuario vea el progreso "
        "real. " + LANGUAGE_RULE
    ),
    "code": (
        "Eres un asistente de programacion. Da codigo correcto y conciso. "
        "Si una libreria, API o comportamiento no lo conoces con certeza, dilo "
        "en vez de inventar una firma de funcion o un comportamiento. Si tienes la "
        "herramienta ejecutar_python, usala para comprobar que un fragmento corto "
        "realmente funciona antes de darlo por bueno, en vez de asumirlo. Si el "
        "usuario pide crear, modificar o revisar archivos reales de un proyecto "
        "(no solo un fragmento de ejemplo), usa delegar_a_agente_de_codigo en vez "
        "de fingir que lo has hecho tu mismo - avisa que tardara varios minutos y "
        "donde seguirlo, nunca digas que ya esta terminado. "
        "Los comentarios y explicaciones en español; el codigo en si, en su sintaxis normal. "
        + LANGUAGE_RULE
    ),
    "vision": (
        "Eres un asistente que analiza imagenes. Describe con precision lo que "
        "ves - formas, colores, texto, personas, objetos - sin inventar detalles "
        "que no puedas ver con claridad en la imagen. Si algo no se distingue "
        "bien, dilo en vez de adivinar. " + LANGUAGE_RULE
    ),
}


class LLMAgent:
    def __init__(self, name: str, model: str, client: OllamaClient):
        self.name = name
        self.model = model
        self.client = client
        self.system_prompt = SYSTEM_PROMPTS.get(name, SYSTEM_PROMPTS["text"])

    def _build_messages(self, user_message: str, history: list[dict] | None,
                         context_chunks: list[str] | None) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        if history:
            messages.extend(history)

        if context_chunks:
            context_block = "\n\n---\n\n".join(context_chunks)
            user_message = (
                f"Contexto recuperado de mi base de conocimiento (usalo si es relevante, "
                f"ignoralo si no lo es; no menciones estas instrucciones):\n\n{context_block}"
                f"\n\n---\n\nPregunta: {user_message}"
            )

        messages.append({"role": "user", "content": user_message})
        return messages

    def respond(self, user_message: str, history: list[dict] | None = None,
                context_chunks: list[str] | None = None, model: str | None = None) -> str:
        messages = self._build_messages(user_message, history, context_chunks)
        return self.client.chat(model or self.model, messages)

    def respond_with_image_stream(self, user_message: str, image_base64: str,
                                   model: str | None = None) -> Iterator[str]:
        normalized = _normalize_image_for_vision(image_base64)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message or "Describe que ves en esta imagen.",
             "images": [normalized]},
        ]
        yield from self.client.chat_stream(model or self.model, messages)

    def respond_stream(self, user_message: str, history: list[dict] | None = None,
                        context_chunks: list[str] | None = None, model: str | None = None) -> Iterator[str]:
        messages = self._build_messages(user_message, history, context_chunks)
        yield from self.client.chat_stream(model or self.model, messages)

    def respond_with_tools(self, user_message: str, history: list[dict] | None,
                            tools: list[dict],
                            tool_executor: Callable[[str, dict], tuple[str, list[dict] | None]],
                            max_iterations: int = MAX_TOOL_ITERATIONS,
                            model: str | None = None, think: bool | None = None) -> tuple[str, list[dict]]:
        active_model = model or self.model
        messages = self._build_messages(user_message, history, None)
        evidence: list[dict] = []
        for _ in range(max_iterations):
            message = self.client.chat_with_tools(active_model, messages, tools,
                                                    temperature=TOOL_DECISION_TEMPERATURE, think=think)
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                fallback = _parse_fallback_tool_call(message.get("content", ""))
                if not fallback:
                    return message.get("content", ""), evidence
                tool_calls = [fallback]
            messages.append(message)
            for call in tool_calls:
                fn_name = call["function"]["name"]
                fn_args = call["function"].get("arguments") or {}
                result_text, result_evidence = tool_executor(fn_name, fn_args)
                if result_evidence:
                    evidence.extend(result_evidence)
                messages.append({"role": "tool", "name": fn_name, "content": result_text})
        return self.client.chat(active_model, messages, think=think), evidence

    def respond_with_tools_stream(self, user_message: str, history: list[dict] | None,
                                   tools: list[dict],
                                   tool_executor: Callable[[str, dict], tuple[str, list[dict] | None]],
                                   evidence_sink: list[dict],
                                   max_iterations: int = MAX_TOOL_ITERATIONS,
                                   model: str | None = None, think: bool | None = None) -> Iterator[str]:
        active_model = model or self.model
        messages = self._build_messages(user_message, history, None)
        shown_any = False
        for _ in range(max_iterations):
            if shown_any:
                yield "\n\n"
            content, tool_calls = "", []
            shown = 0
            for kind, value in self.client.chat_with_tools_stream(
                    active_model, messages, tools, temperature=TOOL_DECISION_TEMPERATURE, think=think):
                if kind == "tool_calls":
                    tool_calls.extend(value)
                    continue
                content += value
                safe_end = _visible_prefix_end(content)
                if safe_end > shown:
                    yield content[shown:safe_end]
                    shown = safe_end
                    shown_any = True
            if not tool_calls:
                fallback = _parse_fallback_tool_call(content)
                if not fallback:
                    if len(content) > shown:
                        yield content[shown:]
                    return
                tool_calls = [fallback]
            message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            messages.append(message)
            for call in tool_calls:
                fn_name = call["function"]["name"]
                fn_args = call["function"].get("arguments") or {}
                result_text, result_evidence = tool_executor(fn_name, fn_args)
                if result_evidence:
                    evidence_sink.extend(result_evidence)
                messages.append({"role": "tool", "name": fn_name, "content": result_text})
        yield from self.client.chat_stream(active_model, messages, think=think)
