import json
import re

from agents.ollama_client import OllamaClient

VALID_AGENTS = {"text", "code", "image", "video", "opencode"}

_EXPLICIT_AGENT = re.compile(r"^\s*((usa|utiliza|usar|con)\s+(un|el)\s+agente\b|agente\s*:)", re.IGNORECASE)

_SMALL_TALK = re.compile(
    r"^\s*[¡¿]*\s*(hola+|holi|buenas|buenos dias|buenas tardes|buenas noches|hey|ey|"
    r"que tal|como estas|como va|gracias|muchas gracias|mil gracias|vale|ok|okay|"
    r"perfecto|genial|estupendo|de acuerdo|entendido|adios|hasta luego|hasta mañana|chao|"
    r"buen trabajo|muy bien)(\s+(chati|amigo|tio))?[\s!¡?¿.,:)]*$",
    re.IGNORECASE)

_QUESTION_START = re.compile(
    r"^\s*¿?\s*((en|a|de|con|desde|hasta|para|por|sobre|y)\s+)?"
    r"(c[oó]mo|qu[eé]|cu[aá]l(es)?|cu[aá]nt[oa]s?|d[oó]nde|cu[aá]ndo|qui[eé]n(es)?|por qu[eé]"
    r"|para qu[eé]|sabes|conoces|existe|hay|es|son)\b", re.IGNORECASE)
_POLITE_ORDER = re.compile(
    r"\b(puedes|podr[ií]as|quieres|me (haces|creas|ordenas|mueves|renombras|borras|pones|abres))\b",
    re.IGNORECASE)


def _is_plain_question(query: str) -> bool:
    q = query.strip()
    return bool(_QUESTION_START.match(q)) and not _POLITE_ORDER.search(q)


ROUTE_PROMPT = """Analiza la peticion del usuario y responde EXACTAMENTE con
este formato JSON, sin nada mas alrededor:

{{"agent": "<text|code|image|video|agente>", "factual": <true|false>}}

- agent:
  - text: conversacion, preguntas, razonamiento, explicaciones, traduccion
  - code: programar, depurar, explicar codigo, escribir un fragmento de ejemplo
  - image: generar o crear una imagen, foto, ilustracion, dibujo
  - video: generar o crear un video o clip
  - agente: HACER algo real en el ordenador del usuario - crear, modificar,
    mover, renombrar, borrar u ordenar archivos o carpetas, ejecutar
    programas o comandos, cambiar el codigo de un proyecto que tiene en disco.
    Solo si pide que se haga de verdad (una orden: "renombra", "ordena",
    "crea"...). Si PREGUNTA como se hace ("¿como renombro...?", "¿como puedo
    ordenar...?"), es text: quiere la explicacion, no que se haga.
  - code tambien si pregunta que hace un fragmento de codigo o por que falla.
- factual: true si responder correctamente requiere datos verificables
  (fechas, cifras, nombres propios, eventos concretos que podrian ser
  incorrectos). false si es conversacion, opinion, creatividad o codigo.

Peticion del usuario: "{query}"
"""


ASSESS_PROMPT = """Un agente con un modelo de lenguaje PEQUEÑO va a hacer esta tarea en
el ordenador Windows del usuario. Valora si la tarea es demasiado dificil
para el y responde EXACTAMENTE con este JSON, sin nada mas alrededor:

{{"dificultad": "<simple|compleja>", "motivo": "<una frase corta en español>"}}

- simple: una o pocas operaciones con archivos o carpetas (crear, leer,
  copiar, mover, renombrar, borrar, listar, ordenar por tipo o fecha),
  buscar un archivo, un script corto y evidente, un comando concreto.
- compleja: programar o modificar el codigo de un proyecto, cambios
  coordinados en varios archivos, depurar un fallo, analizar o resumir mucho
  contenido, instalar o configurar programas, automatizaciones con logica,
  tareas programadas o que se repiten solas (cada noche, cada semana...),
  o cualquier tarea de muchos pasos que dependan unos de otros.

Tarea: "{task}"
"""

SAME_TASK_PROMPT = """En una conversacion, el usuario le encargo una tarea a un agente que
trabaja con sus archivos. El agente ya ha terminado. Ahora el usuario escribe un
mensaje nuevo. ¿Sigue con lo MISMO (corregir, cambiar, ampliar, preguntar por lo
hecho, seguir con ese proyecto o esos archivos) o es un encargo DISTINTO que no
tiene nada que ver? Ante la duda, es lo mismo. Responde EXACTAMENTE con este
JSON, sin nada mas alrededor:

{{"misma": "<si|no>"}}

Tarea anterior: "{previous}"
Mensaje nuevo: "{message}"
"""


_COMPLEX_HINTS = [
    (re.compile(r"\bcada (noche|d[ií]a|semana|mes|hora|ma[ñn]ana)\b|\btodas las (noches|semanas|ma[ñn]anas)\b"
                r"|\bprogramad[ao]s?\b|\bautom[aá]tic", re.IGNORECASE),
     "Es una tarea que se repite sola: hay que programarla y comprobar que funciona."),
    (re.compile(r"\binstal(a|ar)\b|\bconfigur(a|ar)\b", re.IGNORECASE),
     "Instalar o configurar programas requiere varios pasos y comprobaciones."),
    (re.compile(r"\bproyecto\b|\bc[oó]digo\b|\bendpoint|\btests?\b|\bbase de datos\b|\brefactori|\bdepur", re.IGNORECASE),
     "Implica trabajar sobre codigo o un proyecto, con cambios que dependen unos de otros."),
    (re.compile(r"\bno (me )?(funciona|arranca|abre|carga|va|hace nada|se (abre|ve|ejecuta))|\barregl|\bcorrig"
                r"|\breparar?\b|\bsoluciona|\bfall(a|o)\b|\berror", re.IGNORECASE),
     "Hay que encontrar por que falla y arreglarlo: el modelo rapido no sabe depurar."),
]


def complex_hint(text: str) -> str | None:
    return next((why for pattern, why in _COMPLEX_HINTS if pattern.search(text)), None)


class Router:

    def __init__(self, client: OllamaClient, routing_model: str):
        self.client = client
        self.routing_model = routing_model

    def classify(self, query: str) -> dict:
        if _EXPLICIT_AGENT.match(query):
            return {"agent": "opencode", "factual": False}
        if _SMALL_TALK.match(query):
            return {"agent": "text", "factual": False}
        raw = self.client.chat(
            self.routing_model,
            [{"role": "user", "content": ROUTE_PROMPT.format(query=query)}],
            temperature=0.0,
        )
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            data = json.loads(raw[start:end])
            agent = str(data.get("agent", "text")).strip().lower()
            factual = bool(data.get("factual", False))
        except (ValueError, json.JSONDecodeError):
            agent, factual = "text", False

        if agent == "agente":
            agent = "text" if _is_plain_question(query) else "opencode"
        if agent not in VALID_AGENTS:
            agent = "text"
        return {"agent": agent, "factual": factual}

    def assess_agent_task(self, task: str) -> dict:
        raw = self.client.chat(
            self.routing_model,
            [{"role": "user", "content": ASSESS_PROMPT.format(task=task)}],
            temperature=0.0,
        )
        try:
            data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
            complex_ = str(data.get("dificultad", "simple")).strip().lower() == "compleja"
            reason = str(data.get("motivo", "")).strip()
        except (ValueError, json.JSONDecodeError):
            complex_, reason = False, ""
        if not complex_:
            hint = complex_hint(task)
            if hint:
                complex_, reason = True, hint
        return {"complex": complex_, "reason": reason}

    def same_task(self, previous: str, message: str) -> bool:
        raw = self.client.chat(
            self.routing_model,
            [{"role": "user", "content": SAME_TASK_PROMPT.format(previous=previous, message=message)}],
            temperature=0.0,
        )
        try:
            data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        except ValueError:
            return True
        return str(data.get("misma", "si")).strip().lower() != "no"
