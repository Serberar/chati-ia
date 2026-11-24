import base64
import json
import logging
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from argon2.low_level import Type, hash_secret_raw
from cryptography.fernet import Fernet, InvalidToken

from infra.paths import DATA_DIR

_logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "users.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

REGISTRATION_KEY_FILE = DATA_DIR / "registration_key.txt"
SECURITY_LOG_FILE = DATA_DIR / "security_events.jsonl"

_password_hasher = PasswordHasher()
_DUMMY_HASH = _password_hasher.hash(secrets.token_urlsafe(16))
USERNAME_RE = re.compile(r"[\w.\-]{3,32}")

KDF_TIME_COST = 3
KDF_MEMORY_COST = 65536
KDF_PARALLELISM = 2
KDF_KEY_LEN = 32


class UserError(Exception):
    pass


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with closing(_connect()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                password_hash TEXT NOT NULL,
                salt BLOB NOT NULL,
                wrapped_dek BLOB NOT NULL,
                key_generation INTEGER NOT NULL DEFAULT 1,
                security_question TEXT,
                security_answer_hash TEXT,
                created_at TEXT NOT NULL
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "display_name" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
        if "pc_access" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN pc_access INTEGER NOT NULL DEFAULT 0")
        conn.commit()


init_db()


def _derive_kek(secret: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret=secret.encode("utf-8"), salt=salt,
        time_cost=KDF_TIME_COST, memory_cost=KDF_MEMORY_COST,
        parallelism=KDF_PARALLELISM, hash_len=KDF_KEY_LEN, type=Type.ID,
    )


def _fernet_from_raw_key(raw_key: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(raw_key))


def _row_to_dict(row) -> dict:
    return {
        "id": row[0], "username": row[1], "role": row[2], "password_hash": row[3],
        "salt": row[4], "wrapped_dek": row[5], "key_generation": row[6],
        "security_question": row[7], "security_answer_hash": row[8], "created_at": row[9],
        "display_name": row[10], "pc_access": bool(row[11]),
    }


def get_user(username: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, username, role, password_hash, salt, wrapped_dek, key_generation, "
            "security_question, security_answer_hash, created_at, display_name, pc_access FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_users() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at, pc_access FROM users ORDER BY created_at"
        ).fetchall()
    return [{"id": r[0], "username": r[1], "role": r[2], "created_at": r[3],
             "pc_access": r[2] == "admin" or bool(r[4])} for r in rows]


def can_use_pc(username: str | None) -> bool:
    user = get_user(username) if username else None
    return bool(user) and (user["role"] == "admin" or user["pc_access"])


def set_pc_access(username: str, allowed: bool) -> None:
    with closing(_connect()) as conn:
        cur = conn.execute("UPDATE users SET pc_access = ? WHERE username = ?", (1 if allowed else 0, username))
        conn.commit()
    if not cur.rowcount:
        raise UserError(f"No existe el usuario '{username}'.")


def any_users_exist() -> bool:
    with closing(_connect()) as conn:
        return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def create_user(username: str, password: str, role: str,
                 security_question: str | None = None, security_answer: str | None = None) -> str:
    username = username.strip()
    if not username:
        raise UserError("El nombre de usuario no puede estar vacio.")
    if not USERNAME_RE.fullmatch(username):
        raise UserError("El nombre de usuario solo puede tener letras, numeros, punto, guion y guion bajo (3-32).")
    if len(password) < 8:
        raise UserError("La contraseña debe tener al menos 8 caracteres.")
    if role not in ("admin", "user"):
        raise UserError(f"Rol invalido: {role}")
    with closing(_connect()) as conn:
        taken = conn.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
    if taken:
        raise UserError(f"Ya existe un usuario '{username}'.")

    salt = os.urandom(16)
    kek = _derive_kek(password, salt)
    dek = Fernet.generate_key()
    wrapped_dek = _fernet_from_raw_key(kek).encrypt(dek)
    password_hash = _password_hasher.hash(password)
    security_answer_hash = _password_hasher.hash(security_answer.strip().lower()) if security_answer else None

    user_id = uuid.uuid4().hex
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO users (id, username, role, password_hash, salt, wrapped_dek, "
            "key_generation, security_question, security_answer_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (user_id, username, role, password_hash, salt, wrapped_dek,
             security_question, security_answer_hash, datetime.now(UTC).isoformat()),
        )
        conn.commit()
    return user_id


def login(username: str, password: str) -> dict:
    user = get_user(username)
    if not user:
        try:
            _password_hasher.verify(_DUMMY_HASH, password)
        except VerifyMismatchError:
            _logger.debug("login: se sigue sin ello", exc_info=True)
        raise UserError("Usuario o contraseña incorrectos.")
    try:
        _password_hasher.verify(user["password_hash"], password)
    except VerifyMismatchError:
        raise UserError("Usuario o contraseña incorrectos.")

    kek = _derive_kek(password, user["salt"])
    try:
        dek = _fernet_from_raw_key(kek).decrypt(user["wrapped_dek"])
    except InvalidToken:
        raise UserError("No se pudo desbloquear la clave de datos.")

    return {
        "id": user["id"], "username": user["username"], "role": user["role"],
        "key_generation": user["key_generation"], "dek": dek,
    }


def change_password(username: str, old_password: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise UserError("La contraseña debe tener al menos 8 caracteres.")
    session = login(username, old_password)
    dek = session["dek"]

    new_salt = os.urandom(16)
    new_kek = _derive_kek(new_password, new_salt)
    new_wrapped_dek = _fernet_from_raw_key(new_kek).encrypt(dek)
    new_password_hash = _password_hasher.hash(new_password)

    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ?, wrapped_dek = ? WHERE username = ?",
            (new_password_hash, new_salt, new_wrapped_dek, username),
        )
        conn.commit()


def set_display_name(username: str, display_name: str) -> None:
    display_name = display_name.strip()
    if len(display_name) > 40:
        raise UserError("El nombre no puede tener mas de 40 caracteres.")
    with closing(_connect()) as conn:
        conn.execute("UPDATE users SET display_name = ? WHERE username = ?", (display_name or None, username))
        conn.commit()


def set_security_question(username: str, password: str, question: str, answer: str) -> None:
    login(username, password)
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        raise UserError("Escribe la pregunta y la respuesta.")
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE users SET security_question = ?, security_answer_hash = ? WHERE username = ?",
            (question, _password_hasher.hash(answer.lower()), username),
        )
        conn.commit()
    log_security_event("security_question_changed", username)


def reset_via_security_question(username: str, security_answer: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise UserError("La contraseña debe tener al menos 8 caracteres.")
    user = get_user(username)
    target_hash = user["security_answer_hash"] if user and user["security_answer_hash"] else _DUMMY_HASH
    try:
        _password_hasher.verify(target_hash, security_answer.strip().lower())
        if target_hash is _DUMMY_HASH:
            raise VerifyMismatchError()
    except VerifyMismatchError:
        log_security_event("password_reset_failed", username)
        raise UserError("Respuesta incorrecta.")

    salt = os.urandom(16)
    kek = _derive_kek(new_password, salt)
    dek = Fernet.generate_key()
    wrapped_dek = _fernet_from_raw_key(kek).encrypt(dek)
    password_hash = _password_hasher.hash(new_password)

    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ?, wrapped_dek = ?, "
            "key_generation = key_generation + 1 WHERE username = ?",
            (password_hash, salt, wrapped_dek, username),
        )
        conn.commit()
    log_security_event("password_reset_via_security_question", username)


def get_or_create_registration_key() -> str:
    if REGISTRATION_KEY_FILE.exists():
        existing = REGISTRATION_KEY_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    key = secrets.token_urlsafe(24)
    REGISTRATION_KEY_FILE.write_text(key, encoding="utf-8")
    return key


def log_security_event(event: str, username: str) -> None:
    entry = {"event": event, "username": username, "at": datetime.now(UTC).isoformat()}
    with open(SECURITY_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_security_events(last_n: int = 100) -> list[dict]:
    if not SECURITY_LOG_FILE.exists():
        return []
    lines = SECURITY_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[-last_n:]]


def delete_user(username: str) -> bool:
    with closing(_connect()) as conn:
        cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        return cur.rowcount > 0
