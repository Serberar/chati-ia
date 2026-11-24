"""Respuestas del chat: subidas, adjuntar medios y mensajes de error de generacion."""
from fastapi import UploadFile

from agents.comfyui_client import GenerationCancelled
from api.schemas import ChatResponse
from chat import memory
from infra.core import log
from media import content_guard, media_store

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_DOC_BYTES = 100 * 1024 * 1024
MAX_SPEAK_CHARS = 8000


def read_upload(upload: UploadFile, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"El archivo es demasiado grande (maximo {limit // (1024 * 1024)} MB).")
    return data


def with_bytes(resp: ChatResponse, data: bytes, ext: str, session: dict) -> ChatResponse:
    name = media_store.save(data, ext, session["dek"])
    resp.file_path = name
    resp.file_url = media_store.url_for(name)
    return resp


def generation_error_message(action: str, exc: Exception) -> str:
    if isinstance(exc, content_guard.BlockedContent):
        log.info("Peticion rechazada por el filtro de contenido")
        return str(exc)
    if isinstance(exc, GenerationCancelled):
        log.warning("Generacion cancelada (%s): %s", action, exc)
    else:
        log.error("Fallo %s: %s", action, exc, exc_info=exc)
    if isinstance(exc, GenerationCancelled):
        return "Se ha cancelado la generación. Puedes reintentarlo con el botón."
    if "no termino" in str(exc):
        return ("No ha terminado a tiempo: el equipo estaba demasiado ocupado. "
                "Puedes reintentarlo con el botón.")
    return f"No se ha podido terminar ({action}): {exc}"


def remember(session_id: str, auth_session: dict, role: str, content: str, **extra) -> None:
    """Guarda un mensaje cifrado con las claves de la sesion de quien esta conectado."""
    memory.add_message(session_id, role, content, dek=auth_session["dek"],
                       key_generation=auth_session["key_generation"], user_id=auth_session["user_id"], **extra)


def assistant_reply(text: str, agent: str, session_id: str, auth_session: dict,
                     media: str | None = None) -> ChatResponse:
    remember(session_id, auth_session, "assistant", text, agent=agent, media=media)
    resp = ChatResponse(agent_used=agent, response=text, verifier_gated=False, session_id=session_id)
    if media:
        resp.file_path, resp.file_url = media, media_store.url_for(media)
    return resp
