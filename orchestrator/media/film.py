import io
from collections.abc import Callable

import av

from chat import prompt_writer

FILM_PROMPT = """Eres guionista de videos cortos hechos con IA (LTX-Video / Wan), que solo
entienden ingles y hacen bien escenas de pocos segundos con una accion clara.
El usuario pide una pequeña pelicula con palabras sencillas en español.

Peticion del usuario: "{request}"

Divide la historia en {min_scenes} a {max_scenes} escenas seguidas. Cada escena
continua desde como acabo la anterior (mismo personaje, misma ropa, mismo
sitio salvo que la historia cambie de lugar). Devuelve SOLO un JSON:
{{"escenas": [{{"prompt": "<3 frases en ingles en presente: que se ve, que
movimiento hay de principio a fin y como se mueve la camara; repite en cada
escena como es el personaje y el sitio, para que no cambien>", "segundos":
<entre 3 y 6>}}, ...]}}
Respeta lo que pide aunque sea atrevido: no lo suavices ni lo censures."""

MIN_SCENES, MAX_SCENES = 3, 6


def plan_scenes(ollama, model: str, request: str) -> list[dict]:
    data = prompt_writer._ask(ollama, model, FILM_PROMPT.format(request=request, min_scenes=MIN_SCENES,
                                                                max_scenes=MAX_SCENES))
    scenes = []
    for scene in (data.get("escenas") or [])[:MAX_SCENES] if isinstance(data.get("escenas"), list) else []:
        if not isinstance(scene, dict) or not str(scene.get("prompt") or "").strip():
            continue
        try:
            seconds = min(max(float(scene.get("segundos") or 4), 2.0), 8.0)
        except (TypeError, ValueError):
            seconds = 4.0
        scenes.append({"prompt": str(scene["prompt"]).strip(), "segundos": seconds})
    return scenes or [{"prompt": request, "segundos": 4.0}]


def last_frame(video: bytes) -> bytes:
    frame = None
    with av.open(io.BytesIO(video)) as container:
        for frame in container.decode(video=0):
            pass
    if frame is None:
        raise ValueError("El video no tiene fotogramas.")
    out = io.BytesIO()
    frame.to_image().save(out, "PNG")
    return out.getvalue()


def transform(video: bytes, change: Callable) -> bytes:
    out = io.BytesIO()
    with av.open(io.BytesIO(video)) as source, av.open(out, "w", format="mp4") as target:
        src = source.streams.video[0]
        stream = target.add_stream("libx264", rate=src.average_rate or 24)
        stream.width, stream.height, stream.pix_fmt = src.width, src.height, "yuv420p"
        for frame in source.decode(video=0):
            img = change(frame.to_ndarray(format="rgb24"))
            for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuv420p")):
                target.mux(packet)
        for packet in stream.encode():
            target.mux(packet)
    return out.getvalue()


FADE_FRAMES = 12


def concat(videos: list[bytes], fps: int = 24, fade: int = FADE_FRAMES) -> bytes:
    from collections import deque

    import numpy as np
    out = io.BytesIO()
    state = {"stream": None}

    def write(img: np.ndarray) -> None:
        if state["stream"] is None:
            stream = target.add_stream("libx264", rate=fps)
            stream.height, stream.width = img.shape[:2]
            stream.pix_fmt = "yuv420p"
            state["stream"] = stream
        stream = state["stream"]
        frame = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(width=stream.width, height=stream.height,
                                                                           format="yuv420p")
        for packet in stream.encode(frame):
            target.mux(packet)

    with av.open(out, "w", format="mp4") as target:
        held: deque = deque()
        for i, video in enumerate(videos):
            last = i == len(videos) - 1
            with av.open(io.BytesIO(video)) as source:
                frames = (f.to_ndarray(format="rgb24") for f in source.decode(video=0))
                fading = list(held)
                held.clear()
                for j, img in enumerate(frames):
                    if j < len(fading):
                        prev = fading[j]
                        if prev.shape != img.shape:
                            prev = np.asarray(av.VideoFrame.from_ndarray(prev, format="rgb24").reformat(
                                width=img.shape[1], height=img.shape[0]).to_ndarray(format="rgb24"))
                        alpha = (j + 1) / (len(fading) + 1)
                        img = (prev * (1 - alpha) + img * alpha).astype(np.uint8)
                    if not last and fade:
                        held.append(img)
                        if len(held) > fade:
                            write(held.popleft())
                    else:
                        write(img)
        for img in held:
            write(img)
        if state["stream"] is None:
            raise ValueError("No hay fotogramas que unir.")
        for packet in state["stream"].encode():
            target.mux(packet)
    return out.getvalue()


def make(scenes: list[dict], text_to_video: Callable[[str, float], bytes],
         image_to_video: Callable[[str, bytes, float], bytes], first_frame: bytes | None = None,
         on_scene: Callable[[int, int], None] | None = None) -> tuple[bytes, list[bytes]]:
    clips: list[bytes] = []
    frame = first_frame
    for i, scene in enumerate(scenes):
        if on_scene:
            on_scene(i + 1, len(scenes))
        clip = (image_to_video(scene["prompt"], frame, scene["segundos"]) if frame is not None
                else text_to_video(scene["prompt"], scene["segundos"]))
        clips.append(clip)
        frame = last_frame(clip)
    return concat(clips), clips


def redo(scenes: list[dict], clips: list[bytes], index: int, text_to_video: Callable[[str, float], bytes],
         image_to_video: Callable[[str, bytes, float], bytes], first_frame: bytes | None = None
         ) -> tuple[bytes, list[bytes]]:
    frame = last_frame(clips[index - 1]) if index > 0 else first_frame
    scene = scenes[index]
    clip = (image_to_video(scene["prompt"], frame, scene["segundos"]) if frame is not None
            else text_to_video(scene["prompt"], scene["segundos"]))
    clips = clips[:index] + [clip] + clips[index + 1:]
    return concat(clips), clips
