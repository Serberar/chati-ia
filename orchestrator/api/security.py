import logging

from accounts import devices

log = logging.getLogger("chati")

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
REMOTE_HOSTS: set[str] = set()
PAIR_PATHS = {"/pair", "/pair/claim", "/pair/check", "/static/js/pair.js", "/favicon.ico", "/client-log",
              "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/manifest.webmanifest", "/sw.js", "/push/key",
              "/static/icon-192.png", "/static/icon-512.png",
              "/health"}
MAX_BODY_BYTES = 250 * 1024 * 1024
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def host_name(host_header: str) -> str:
    host = (host_header or "").strip().lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def is_local_host(host_header: str) -> bool:
    return host_name(host_header) in LOCAL_HOSTS


def is_remote_host(host_header: str) -> bool:
    return host_name(host_header) in REMOTE_HOSTS


def origin_allowed(origin: str | None, host_header: str) -> bool:
    if origin is None:
        return True
    origin = origin.strip().lower()
    host = host_header.strip().lower()
    if is_remote_host(host_header):
        return origin in (f"https://{host}", f"https://{host_name(host_header)}")
    return origin in (f"http://{host}",) and is_local_host(host_header)


def _rejected(request, status: int, why: str, where: str) -> JSONResponse:
    log.warning("Rechazada %s %s (%d, %s) desde %s", request.method, request.url.path, status, why, where)
    return JSONResponse({"detail": why}, status_code=status)


_QUIET_STATUSES = {401, 404}


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        host = request.headers.get("host", "")
        request.state.device = None
        if is_remote_host(host):
            device = devices.verify(request.cookies.get(devices.COOKIE_NAME))
            where = f"fuera ({device['name']})" if device else "fuera (sin vincular)"
            if device is None and request.url.path not in PAIR_PATHS:
                if request.method == "GET" and request.url.path == "/":
                    return RedirectResponse("/pair", status_code=303)
                return _rejected(request, 403, "Este dispositivo no esta vinculado a Chati.", where)
            request.state.device = device
        elif not is_local_host(host):
            return _rejected(request, 400, "Solo se aceptan conexiones a localhost.", f"host {host_name(host)!r}")
        else:
            where = "el ordenador"
        if request.method not in SAFE_METHODS and not origin_allowed(request.headers.get("origin"), host):
            return _rejected(request, 403, "Origen no permitido.", where)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return _rejected(request, 413, "Peticion demasiado grande.", where)
        response = await call_next(request)
        if response.status_code >= 400:
            level = logging.INFO if response.status_code in _QUIET_STATUSES else logging.WARNING
            log.log(level, "Respuesta %d a %s %s desde %s", response.status_code, request.method,
                    request.url.path, where)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        path = request.url.path
        if path in ("/", "/pair") or path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response
