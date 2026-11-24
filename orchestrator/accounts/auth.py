import secrets

from infra.paths import DATA_DIR

KEY_FILE = DATA_DIR / "api_key.txt"
KEY_FILE.parent.mkdir(parents=True, exist_ok=True)


def get_or_create_key() -> str:
    if KEY_FILE.exists():
        existing = KEY_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    key = secrets.token_urlsafe(32)
    KEY_FILE.write_text(key, encoding="utf-8")
    return key


API_KEY = get_or_create_key()

PUBLIC_PATHS = {
    "/", "/health", "/favicon.ico",
    "/auth/login", "/auth/guest", "/auth/register", "/auth/reset-password",
    "/pair", "/pair/claim", "/pair/check",
    "/client-log",
    "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/manifest.webmanifest",
    "/sw.js",
    "/push/key",
}
PUBLIC_PATH_PREFIXES = ("/auth/security-question/", "/static/", "/llm/")


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PATH_PREFIXES)
