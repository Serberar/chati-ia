import json
import re

from media import content_guard

IMAGE_SIZES = {"cuadrado": (1024, 1024), "vertical": (832, 1216), "horizontal": (1216, 832)}

IMAGE_PROMPT = """Eres quien escribe las descripciones para un generador de imagenes con IA
(FLUX/SDXL), que solo entiende ingles. El usuario lo pide con palabras
sencillas en español; tu lo conviertes en una buena descripcion.

Peticion del usuario: "{request}"

Devuelve SOLO un JSON con:
- "prompt": la descripcion en ingles, una o dos frases. Primero QUE se ve
  (lo que pidio, sin cambiarlo: si pide "un perro", no lo conviertas en "un
  golden retriever con bufanda"; si da detalles, respetalos todos), despues
  como se ve: tipo de imagen (si no dice nada, foto realista; si pide dibujo,
  acuarela, dibujos animados, logo... ese estilo), luz, encuadre y calidad
  ("natural light", "sharp focus", "highly detailed"). Si pide texto escrito
  en la imagen, ponlo entre comillas tal cual.
  No copies para quien o para que es ("para mi sobrino", "fondo de pantalla
  del movil"): usalo solo como pista (para un niño: dibujo amable y colorido;
  para el movil: formato vertical).
- "formato": "vertical" (movil, retrato, poster, fondo de pantalla del movil,
  una persona de cuerpo entero), "horizontal" (paisaje, panoramica, fondo de
  escritorio, portada, banner) o "cuadrado" (lo demas, o si no esta claro).

Ejemplos:
"un perro en la nieve" -> {{"prompt": "A realistic photo of a dog standing in fresh snow, soft winter daylight, snowflakes in the air, shallow depth of field, natural colors, sharp focus, highly detailed.", "formato": "cuadrado"}}
"un fondo de pantalla para el movil de una playa al atardecer" -> {{"prompt": "A realistic photo of a tropical beach at sunset, golden sky reflected on calm waves, palm trees silhouetted against the horizon, warm natural light, high detail.", "formato": "vertical"}}
"dibujame un gato astronauta para mi hija" -> {{"prompt": "A cute colorful cartoon illustration of a cat astronaut floating in space among stars and planets, friendly expression, clean lines, bright cheerful colors, children's book style.", "formato": "cuadrado"}}

Antes de responder, revisa el "prompt": no puede decir para quien es ni para
que se usa (nada de "for my nephew", "for my daughter", "phone wallpaper",
"desktop background"): solo lo que se VE en la imagen."""

VIDEO_PROMPT = """Eres quien escribe las descripciones para un generador de video con IA
(LTX-Video), que solo entiende ingles y funciona mejor con una descripcion
detallada de lo que se ve y de como se mueve. El usuario lo pide con
palabras sencillas en español.

Peticion del usuario: "{request}"

Devuelve SOLO un JSON con:
- "prompt": la descripcion en ingles, tres o cuatro frases en presente. Que
  se ve (lo que pidio, sin cambiarlo), que movimiento hay de principio a fin (acciones concretas,
  lentas y naturales), como se mueve la camara (fija, travelling lento,
  acercamiento suave...) y la luz y el ambiente. Si no pide otra cosa, que
  parezca grabado de verdad. No metas en el prompt la duracion ni el formato.
- "segundos": cuanto debe durar si lo dice ("de 8 segundos", "medio minuto"
  = 30), como numero; null si no lo dice.
- "formato": "vertical" (movil, retrato, una persona de cuerpo entero),
  "horizontal" (lo normal, paisajes, cine) o "cuadrado". Si no esta claro,
  "horizontal".

Ejemplo:
"olas rompiendo en una playa, 8 segundos" -> {{"prompt": "Gentle ocean waves roll onto a sandy beach and break into white foam that spreads across the shore before slowly receding. The camera stays still at a low angle near the waterline. Warm late afternoon sunlight reflects on the wet sand and the water surface, with a clear sky above. Realistic footage with natural motion.", "segundos": 8, "formato": "horizontal"}}"""

_PURPOSE = [
    (re.compile(r"\b(?:phone |mobile |smartphone |desktop |computer )?wallpaper\b(?:\s+(?:featuring|with|of|showing))?",
                re.IGNORECASE), "image of"),
    (re.compile(r",?\s*\bfor (?:my|his|her|your|a|the) (?:little |young )?"
                r"(?:nephew|niece|son|daughter|mother|father|mom|dad|wife|husband|friend|kid|child|children|"
                r"brother|sister|grandson|granddaughter|boy|girl)\b", re.IGNORECASE), ""),
]


def _clean(prompt: str) -> str:
    for pattern, replacement in _PURPOSE:
        prompt = pattern.sub(replacement, prompt)
    return re.sub(r"\s{2,}", " ", prompt).strip()


def _ask(ollama, model: str, content: str) -> dict:
    raw = ollama.chat(model, [{"role": "user", "content": content}], temperature=0.2, think=False)
    try:
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {}


def image_prompt(ollama, model: str, request: str) -> tuple[str, tuple[int, int]]:
    content_guard.check(request)
    data = _ask(ollama, model, IMAGE_PROMPT.format(request=request))
    prompt = _clean(str(data.get("prompt") or "")) or request
    return prompt, IMAGE_SIZES.get(str(data.get("formato", "")).strip().lower(), IMAGE_SIZES["cuadrado"])


VIDEO_SIZES = {"horizontal": (768, 512), "vertical": (512, 768), "cuadrado": (640, 640)}


def video_plan(ollama, model: str, request: str) -> tuple[str, float | None, tuple[int, int]]:
    content_guard.check(request)
    data = _ask(ollama, model, VIDEO_PROMPT.format(request=request))
    try:
        seconds = float(data["segundos"]) if data.get("segundos") not in (None, "") else None
    except (TypeError, ValueError):
        seconds = None
    if not re.search(r"segund|minut|\d\s*s\b", request, re.IGNORECASE):
        seconds = None
    size = VIDEO_SIZES.get(str(data.get("formato", "")).strip().lower(), VIDEO_SIZES["horizontal"])
    return str(data.get("prompt") or "").strip() or request, seconds, size


def video_prompt(ollama, model: str, request: str) -> str:
    return video_plan(ollama, model, request)[0]
