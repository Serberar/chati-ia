import json
import re
import shutil
import tempfile
from pathlib import Path

from chat.rag import _chunk_text, _extract_text, _sanitize_filename
from infra import atomic, crypto_utils
from infra.paths import DATA_DIR

SESSION_DOCS_DIR = DATA_DIR / "session_docs"
ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
FULL_TEXT_LIMIT = 15000
TOP_CHUNKS = 5

_WORD = re.compile(r"\w{3,}", re.UNICODE)


def _dir(user_id: str, session_id: str) -> Path:
    return SESSION_DOCS_DIR / _sanitize_filename(user_id) / _sanitize_filename(session_id)


def _meta_path(user_id: str, session_id: str) -> Path:
    return _dir(user_id, session_id) / "meta.json"


def _read_meta(user_id: str, session_id: str) -> dict:
    path = _meta_path(user_id, session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        return {}


def _write_meta(user_id: str, session_id: str, meta: dict) -> None:
    atomic.write_text(_meta_path(user_id, session_id), json.dumps(meta, ensure_ascii=False))


def save(user_id: str, session_id: str, filename: str, content: bytes,
         dek: bytes, key_generation: int) -> dict:
    filename = _sanitize_filename(filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("Formato no soportado - usa PDF, Word (.docx), .txt o .md.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("El documento es demasiado grande (maximo 20 MB).")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / filename
        tmp_path.write_bytes(content)
        try:
            text = _extract_text(tmp_path).strip()
        except Exception as exc:
            raise ValueError(f"No se pudo leer el documento: {exc}") from exc
    if not text:
        raise ValueError("El documento no tiene texto que se pueda leer (¿es un PDF escaneado?).")

    d = _dir(user_id, session_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{filename}.orig.enc").write_bytes(crypto_utils.encrypt_bytes(dek, content))
    (d / f"{filename}.txt.enc").write_bytes(crypto_utils.encrypt_bytes(dek, text.encode("utf-8")))
    meta = _read_meta(user_id, session_id)
    meta[filename] = {"chars": len(text), "key_generation": key_generation}
    _write_meta(user_id, session_id, meta)
    return {"name": filename, "chars": len(text)}


def list_docs(user_id: str, session_id: str) -> list[dict]:
    return [{"name": name, "chars": info["chars"]}
            for name, info in sorted(_read_meta(user_id, session_id).items())]


def _read(user_id: str, session_id: str, filename: str, kind: str,
          dek: bytes, key_generation: int) -> bytes | None:
    info = _read_meta(user_id, session_id).get(filename)
    path = _dir(user_id, session_id) / f"{filename}.{kind}.enc"
    if not info or info.get("key_generation") != key_generation or not path.exists():
        return None
    return crypto_utils.decrypt_bytes(dek, path.read_bytes())


def get_original(user_id: str, session_id: str, filename: str,
                 dek: bytes, key_generation: int) -> bytes | None:
    return _read(user_id, session_id, _sanitize_filename(filename), "orig", dek, key_generation)


def remove(user_id: str, session_id: str, filename: str) -> None:
    filename = _sanitize_filename(filename)
    d = _dir(user_id, session_id)
    for kind in ("orig", "txt"):
        (d / f"{filename}.{kind}.enc").unlink(missing_ok=True)
    meta = _read_meta(user_id, session_id)
    if meta.pop(filename, None) is not None:
        _write_meta(user_id, session_id, meta)


def delete_session(user_id: str, session_id: str) -> None:
    shutil.rmtree(_dir(user_id, session_id), ignore_errors=True)


def delete_all_for_user(user_id: str) -> None:
    shutil.rmtree(SESSION_DOCS_DIR / _sanitize_filename(user_id), ignore_errors=True)


def _best_chunks(text: str, question: str, k: int) -> list[str]:
    chunks = _chunk_text(text)
    q_words = {w.lower() for w in _WORD.findall(question)}
    scored = sorted(enumerate(chunks),
                    key=lambda ic: -len(q_words & {w.lower() for w in _WORD.findall(ic[1])}))
    return [c for _, c in sorted(scored[:k])]


def context_for(user_id: str, session_id: str, question: str,
                dek: bytes, key_generation: int) -> tuple[str, list[dict]]:
    parts, evidence = [], []
    for doc in list_docs(user_id, session_id):
        raw = _read(user_id, session_id, doc["name"], "txt", dek, key_generation)
        if raw is None:
            continue
        text = raw.decode("utf-8")
        if len(text) <= FULL_TEXT_LIMIT:
            body, label = text, "completo"
        else:
            body, label = "\n[...]\n".join(_best_chunks(text, question, TOP_CHUNKS)), "fragmentos relevantes"
        parts.append(f"<documento nombre=\"{doc['name']}\" contenido=\"{label}\">\n{body}\n</documento>")
        evidence.append({"source": f"adjunto:{doc['name']}", "text": body})
    if not parts:
        return "", []
    header = ("El usuario ha adjuntado estos documentos a la conversacion. Usalos para responder "
              "y di de cual sale la informacion:\n")
    return header + "\n".join(parts), evidence
