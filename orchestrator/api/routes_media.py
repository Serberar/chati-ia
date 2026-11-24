"""Rutas de medios: servir imagenes y videos guardados, y escalar o repintar una imagen."""
import io
import re
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from api.replies import generation_error_message, read_upload, with_bytes
from api.schemas import ChatResponse
from infra import metrics
from infra.core import image_agent
from media import media_store

router = APIRouter()


def _source_image_bytes(file_path: str | None, image: UploadFile | None, session: dict) -> bytes:
    if file_path:
        data = media_store.load(Path(file_path).name, session["dek"])
        if data is None:
            raise ValueError("Imagen no valida.")
        return data
    if image is not None and image.filename:
        return read_upload(image)
    raise ValueError("Hay que indicar una imagen (subida o ya generada).")
MAX_UPSCALE_PIXELS = 4_200_000


def _check_upscale_size(data: bytes) -> None:
    from PIL import Image, UnidentifiedImageError
    try:
        w, h = Image.open(io.BytesIO(data)).size
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("El archivo no es una imagen valida.") from exc
    if w * h > MAX_UPSCALE_PIXELS:
        raise ValueError(f"La imagen ya es muy grande para escalarla x4 ({w}x{h}); "
                         f"como mucho unos {MAX_UPSCALE_PIXELS // 1_000_000} megapixeles.")


@router.post("/image/upscale", response_model=ChatResponse)
def image_upscale(request: Request, file_path: str | None = Form(None), image: UploadFile | None = File(None)):
    start = time.perf_counter()
    session = request.state.session
    try:
        src_bytes = _source_image_bytes(file_path, image, session)
        _check_upscale_size(src_bytes)
    except ValueError as exc:
        return ChatResponse(agent_used="image_upscale", response=str(exc), verifier_gated=False)

    try:
        with media_store.plain_copy(src_bytes, ".png") as src:
            img_bytes = image_agent.upscale(str(src))
    except Exception as exc:
        metrics.log_since("image_upscale", start, error=str(exc))
        return ChatResponse(agent_used="image_upscale",
                             response=generation_error_message("escalando la imagen", exc),
                             verifier_gated=False)

    metrics.log_since("image_upscale", start)
    return with_bytes(
        ChatResponse(agent_used="image_upscale", response="Imagen escalada x4.", verifier_gated=False),
        img_bytes, ".png", session,
    )


@router.get("/media/{name}")
def get_media(name: str, request: Request):
    data = media_store.load(name, request.state.session["dek"])
    if data is None:
        return JSONResponse({"detail": "No encontrado."}, status_code=404)
    headers = {"Cache-Control": "private, max-age=3600", "Accept-Ranges": "bytes"}
    size = len(data)
    rng = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("range", ""))
    if rng and (rng.group(1) or rng.group(2)):
        if rng.group(1):
            first = int(rng.group(1))
            last = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
        else:
            first, last = max(0, size - int(rng.group(2))), size - 1
        if first >= size or first > last:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {first}-{last}/{size}"
        return Response(data[first:last + 1], status_code=206, media_type=media_store.media_type(name),
                        headers=headers)
    return Response(data, media_type=media_store.media_type(name), headers=headers)
