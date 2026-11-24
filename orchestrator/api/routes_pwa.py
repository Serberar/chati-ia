"""Rutas de la aplicacion web: la pagina, iconos, service worker, manifest y los errores que manda el navegador."""
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api import access
from infra import logging_setup
from infra.core import log
from infra.paths import ORCH_DIR

router = APIRouter()


@router.get("/")
def index_page():
    return FileResponse(ORCH_DIR / "static" / "index.html")


@router.get("/apple-touch-icon.png")
@router.get("/apple-touch-icon-precomposed.png")
def apple_touch_icon():
    return FileResponse(ORCH_DIR / "static" / "apple-touch-icon.png", media_type="image/png")


@router.get("/favicon.ico")
def favicon():
    return FileResponse(ORCH_DIR / "static" / "logo.ico", media_type="image/x-icon")


@router.get("/sw.js")
def service_worker():
    return FileResponse(ORCH_DIR / "static" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@router.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({
        "name": "Chati IA", "short_name": "Chati", "start_url": "/", "display": "standalone",
        "background_color": "#14161a", "theme_color": "#14161a",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, media_type="application/manifest+json")


@router.get("/admin/errors", dependencies=[access.admin_only("Solo para administradores.")])
def admin_errors(request: Request):
    path = logging_setup.ERROR_FILE
    if not path.exists():
        return {"entries": []}
    text = path.read_text(encoding="utf-8", errors="replace")[-200_000:]
    entries: list[str] = []
    for line in text.splitlines():
        if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", line) or not entries:
            entries.append(line)
        else:
            entries[-1] += "\n" + line
    return {"entries": entries[::-1][:300]}


class ClientLog(BaseModel):
    message: str = Field("", max_length=2000)
    source: str = Field("", max_length=300)
    stack: str = Field("", max_length=4000)
    page: str = Field("", max_length=300)
_client_log_times: list[float] = []


@router.post("/client-log")
def client_log(body: ClientLog, request: Request):
    now = time.time()
    while _client_log_times and _client_log_times[0] < now - 60:
        _client_log_times.pop(0)
    if len(_client_log_times) >= 30:
        return {"ok": False}
    _client_log_times.append(now)
    device = getattr(request.state, "device", None)
    where = f"el dispositivo '{device['name']}'" if device else "el ordenador"
    log.warning("Error en la pantalla (%s, %s): %s | %s%s", where, body.page or "?", body.message,
                body.source, f"\n{body.stack}" if body.stack else "")
    return {"ok": True}
