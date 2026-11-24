"""Progreso de la generacion en curso, por peticion, y modelo que escribe las descripciones."""
import contextvars

from infra.core import CONFIG

progress: contextvars.ContextVar = contextvars.ContextVar("photo_progress", default=None)


def writer_model() -> str:
    return CONFIG["router"]["model"]


def report(text: str) -> None:
    callback = progress.get()
    if callback:
        callback(text)
