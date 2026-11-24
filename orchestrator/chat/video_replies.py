"""Respuestas de video en el chat: repetir un video, peliculas por escenas y avisos."""
import re
import time

from accounts import push
from agents import video_agent as video_agent_module
from api.replies import assistant_reply, generation_error_message, remember, with_bytes
from api.schemas import ChatResponse
from chat import gen_options, prompt_writer
from infra.core import ollama, video_agent
from media import content_guard, film, media_store, video_pipeline

last_videos: dict[str, dict] = {}
_SECONDS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:s\b|seg\b|segundos?\b)|(medio)\s+minuto|(un|1)\s+minuto", re.IGNORECASE)
_SAME_VIDEO = re.compile(r"\b(?:hazlo|haz(?:me)?lo|repite(?:lo)?|mismo|misma|igual|ese|este|alarga(?:lo)?|"
                         r"m[aá]s\s+largo|m[aá]s\s+corto|ahora)\b", re.IGNORECASE)


def video_again(session_id: str, message: str) -> float | None:
    if session_id not in last_videos or len(message) > 120 or not _SAME_VIDEO.search(message):
        return None
    found = _SECONDS.search(message)
    if not found:
        return None
    if found.group(2):
        return 30.0
    if found.group(3):
        return 60.0
    return float(found.group(1).replace(",", "."))


FILM = re.compile(r"\bpel[ií]cula\b|\bcortometraje\b|\bun corto\b|\bvarias escenas\b|\bpor escenas\b", re.IGNORECASE)
_FILM_REDO = re.compile(r"\b(?:rehaz|repite|vuelve a hacer|cambia|mejora)\b[^.\d]*?\bescena\s+(\d+)\b[\s,.:;]*(.*)",
                        re.IGNORECASE | re.DOTALL)
_last_films: dict[str, dict] = {}


def film_redo(session_id: str, message: str) -> tuple[int, str] | None:
    match = _FILM_REDO.search(message)
    last = _last_films.get(session_id)
    if not match or not last or not 1 <= int(match.group(1)) <= len(last["scenes"]):
        return None
    return int(match.group(1)) - 1, match.group(2).strip()


def film_reply(message: str, session_id: str, auth_session: dict,
                video_model: str | None = None, redo: tuple[int, str] | None = None) -> ChatResponse:
    started = time.time()
    seed = video_agent_module.new_seed()
    last = _last_films.get(session_id) if redo else None
    if last:
        video_model = last["model"]

    def image_to_video(prompt: str, frame: bytes, seconds: float) -> bytes:
        width, height = video_pipeline.video_size_like(frame)
        with media_store.plain_copy(frame, ".png") as frame_path:
            return video_agent.generate_from_image(prompt, str(frame_path), width=width, height=height,
                                                   seconds=seconds, seed=seed, model_id=video_model)

    def text_to_video(prompt: str, seconds: float) -> bytes:
        return video_agent.generate(prompt, seconds=seconds, seed=seed, model_id=video_model)

    try:
        content_guard.check(message)
        if last:
            index, change = redo
            scenes = [dict(s) for s in last["scenes"]]
            if change:
                scenes[index]["prompt"] = prompt_writer.video_prompt(
                    ollama, gen_options.writer_model(), f"{scenes[index]['prompt']}\nCambio pedido: {change}")
            gen_options.report(f"Rehaciendo la escena {index + 1}…")
            movie, clips = film.redo(scenes, last["clips"], index, text_to_video, image_to_video)
        else:
            scenes = film.plan_scenes(ollama, gen_options.writer_model(), message)
            movie, clips = film.make(scenes, text_to_video, image_to_video,
                                     on_scene=lambda n, total: gen_options.report(f"Escena {n} de {total}…"))
    except Exception as exc:
        return assistant_reply(generation_error_message("generando la pelicula", exc), "video", session_id,
                                auth_session)
    _last_films[session_id] = {"scenes": scenes, "clips": clips, "model": video_model}
    total = sum(s["segundos"] for s in scenes)
    guion = "\n".join(f"{i}. {s['prompt']}" for i, s in enumerate(scenes, 1))
    head = (f"Escena {redo[0] + 1} rehecha; las demás siguen igual." if last
            else f"Película de {len(scenes)} escenas (~{total:g} s).")
    resp = with_bytes(ChatResponse(agent_used="video", verifier_gated=False, session_id=session_id,
                                    response=f"{head} Guion:\n{guion}\n\nSi una escena no te gusta, pide "
                                             "\"rehaz la escena 2\" (o \"rehaz la escena 2 pero de noche\")."),
                       movie, ".mp4", auth_session)
    remember(session_id, auth_session, "assistant", resp.response, agent="video", media=resp.file_path)
    notify_if_long(auth_session, started, f"Tu película de {len(scenes)} escenas está lista.")
    return resp
VIDEO_NOTIFY_SECONDS = 180


def notify_if_long(auth_session: dict, started: float, text: str) -> None:
    user = auth_session.get("user_id")
    if time.time() - started >= VIDEO_NOTIFY_SECONDS and user and push.has_devices(user):
        push.notify(user, "🎬 Vídeo listo", text, tag="chati-video")


