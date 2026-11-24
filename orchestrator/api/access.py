from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from accounts import auth_sessions, users

SESSION_COOKIE = "chati_session"
LAUNCHER_ORIGIN = "https://serberar.github.io"

GUEST_PATHS = {
    "/auth/me", "/auth/logout", "/chat", "/chat/stream", "/cancel", "/voice_chat", "/speak",
    "/image/upscale",
    "/models/status", "/models/profiles", "/models/roles", "/models/prepare", "/models/image",
    "/models/video", "/work/pending",
}
GUEST_PATH_PREFIXES = ("/plan/", "/media/")
PC_PATH_PREFIXES = ("/agent/", "/code/", "/work/agent/")


def session_token(request: Request) -> str | None:
    return request.headers.get("X-Session-Token") or request.cookies.get(SESSION_COOKIE)


def current_session(request: Request) -> dict | None:
    token = session_token(request)
    return auth_sessions.get_session(token) if token else None


def guest_may_use(path: str) -> bool:
    return path in GUEST_PATHS or path.startswith(GUEST_PATH_PREFIXES)


def can_use_pc(session: dict) -> bool:
    if session.get("role") == "admin":
        return True
    return session.get("role") != "guest" and users.can_use_pc(session.get("username"))


def guest_blocked() -> JSONResponse:
    return JSONResponse({"detail": "No disponible en modo invitado."}, status_code=403)


def pc_blocked() -> JSONResponse:
    return JSONResponse({"detail": "Tu cuenta no tiene permiso para usar el ordenador (agente, archivos, "
                                   "ejecutar codigo). Pideselo al administrador."}, status_code=403)


def admin_only(detail: str = "Solo el administrador."):
    """Dependencia de ruta: 403 con `detail` si quien llama no es administrador."""
    def check(request: Request) -> None:
        if request.state.session["role"] != "admin":
            raise HTTPException(status_code=403, detail=detail)
    return Depends(check)


def owner_of(session: dict) -> str:
    return session.get("user_id") or f"invitado:{id(session)}"
