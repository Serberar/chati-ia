import logging
import sys
from logging.handlers import RotatingFileHandler

from infra import paths

LOG_DIR = paths.DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "chati.log"
ERROR_FILE = LOG_DIR / "errores.log"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup() -> logging.Logger:
    root = logging.getLogger()
    if any(getattr(h, "_chati", False) for h in root.handlers):
        return logging.getLogger("chati")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler._chati = True
    root.addHandler(handler)
    errors = RotatingFileHandler(ERROR_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    errors.setLevel(logging.WARNING)
    errors.setFormatter(logging.Formatter(_FORMAT))
    errors._chati = True
    errors.addFilter(_skip_client_disconnects)
    root.addHandler(errors)
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_FORMAT))
        console._chati = True
        root.addHandler(console)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    for noisy in ("httpx", "httpx2", "urllib3", "chromadb", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("asyncio").addFilter(_skip_client_disconnects)
    return logging.getLogger("chati")


def _skip_client_disconnects(record: logging.LogRecord) -> bool:
    exc = record.exc_info[1] if record.exc_info else None
    return not isinstance(exc, (ConnectionResetError, ConnectionAbortedError))
