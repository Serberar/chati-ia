import base64
import hashlib
import json
import secrets
import threading
import time

from cryptography.fernet import Fernet, InvalidToken

from infra.paths import DATA_DIR

SESSION_TTL_SECONDS = 12 * 60 * 60
REMEMBER_SECONDS = 30 * 24 * 60 * 60
MAX_GUEST_SESSIONS = 50
# "Recordarme": la sesion sobrevive a reinicios. La clave de los datos va cifrada con el token de la cookie,
# asi que este archivo solo no abre nada.
REMEMBERED = DATA_DIR / "sesiones_recordadas.json"

_sessions: dict[str, dict] = {}
_lock = threading.Lock()


def _purge_expired() -> None:
    now = time.time()
    for token in [t for t, s in _sessions.items() if s["expires_at"] < now]:
        del _sessions[token]


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_key(token: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"chati-recordar:" + token.encode("utf-8")).digest()))


def _load_remembered() -> dict:
    try:
        records = json.loads(REMEMBERED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: r for k, r in records.items() if r["expires_at"] > now}


def _save_remembered(records: dict) -> None:
    REMEMBERED.parent.mkdir(parents=True, exist_ok=True)
    tmp = REMEMBERED.with_suffix(".tmp")
    tmp.write_text(json.dumps(records), encoding="utf-8")
    tmp.replace(REMEMBERED)


def _restore(token: str) -> dict | None:
    record = _load_remembered().get(_token_id(token))
    if record is None:
        return None
    try:
        dek = _token_key(token).decrypt(record["dek"].encode("ascii"))
    except InvalidToken:
        return None
    session = {k: record[k] for k in ("user_id", "username", "role", "key_generation", "expires_at")}
    session["dek"] = dek
    return session


def create_session(user_id: str, username: str, role: str, dek: bytes, key_generation: int,
                   remember: bool = False) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + (REMEMBER_SECONDS if remember else SESSION_TTL_SECONDS)
    with _lock:
        _purge_expired()
        _sessions[token] = {
            "user_id": user_id, "username": username, "role": role,
            "dek": dek, "key_generation": key_generation,
            "expires_at": expires_at,
        }
        if remember:
            records = _load_remembered()
            records[_token_id(token)] = {
                "user_id": user_id, "username": username, "role": role, "key_generation": key_generation,
                "expires_at": expires_at, "dek": _token_key(token).encrypt(dek).decode("ascii"),
            }
            _save_remembered(records)
    return token


def create_guest_session() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _purge_expired()
        guests = [t for t, s in _sessions.items() if s["role"] == "guest"]
        for old in sorted(guests, key=lambda t: _sessions[t]["expires_at"])[:max(0, len(guests) - MAX_GUEST_SESSIONS + 1)]:
            del _sessions[old]
        _sessions[token] = {
            "user_id": None, "username": None, "role": "guest",
            "dek": Fernet.generate_key(), "key_generation": 0,
            "expires_at": time.time() + SESSION_TTL_SECONDS,
        }
    return token


def get_session(token: str) -> dict | None:
    with _lock:
        session = _sessions.get(token)
        if session is None and token:
            session = _restore(token)
            if session is not None:
                _sessions[token] = session
        if session is None:
            return None
        if time.time() > session["expires_at"]:
            del _sessions[token]
            return None
        return session


def destroy_session(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)
        records = _load_remembered()
        if records.pop(_token_id(token), None) is not None:
            _save_remembered(records)


def destroy_all_sessions_for_user(username: str) -> None:
    with _lock:
        for token in [t for t, s in _sessions.items() if s["username"] == username]:
            del _sessions[token]
        records = _load_remembered()
        kept = {k: r for k, r in records.items() if r["username"] != username}
        if len(kept) != len(records):
            _save_remembered(kept)
