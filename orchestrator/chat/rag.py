import re
import shutil
import tempfile
import uuid
from pathlib import Path

import chromadb
import pypdf
from chromadb import EmbeddingFunction
from docx import Document as DocxDocument

from agents.ollama_client import OllamaClient
from infra import crypto_utils
from infra.paths import DATA_DIR

ORPHANED_PLACEHOLDER = "[contenido no disponible - se cifro con una clave anterior a un restablecimiento de contraseña]"

KB_DIR = DATA_DIR / "knowledge"
KB_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR = KB_DIR / "documents"
DOCS_DIR.mkdir(exist_ok=True)

EMBED_MODEL = "nomic-embed-text"
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" ")
    name = name.lstrip(".")
    if not name:
        raise ValueError("Nombre de archivo invalido")
    return name


MAX_TEXT_CHARS = 2_000_000
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_PDF_PAGES = 2000


def _check_docx(path: Path) -> None:
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            total = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo .docx esta dañado o no es un documento de Word.") from exc
    if total > MAX_DOCX_UNCOMPRESSED:
        raise ValueError("El documento es demasiado grande por dentro (mas de 50 MB descomprimido).")


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = pypdf.PdfReader(str(path))
        parts, size = [], 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            text = page.extract_text() or ""
            parts.append(text)
            size += len(text)
            if size >= MAX_TEXT_CHARS:
                break
        return "\n".join(parts)[:MAX_TEXT_CHARS]
    if suffix == ".docx":
        _check_docx(path)
        doc = DocxDocument(str(path))
        return "\n".join(p.text for p in doc.paragraphs)[:MAX_TEXT_CHARS]
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read(MAX_TEXT_CHARS)


def _split_long(sentence: str, limit: int) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    pieces, current = [], ""
    for word in sentence.split(" "):
        while len(word) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:limit])
            word = word[limit:]
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    piece_len = max(overlap, size // 3)
    sentences = [piece for s in _SENTENCE_SPLIT.split(text) if s for piece in _split_long(s, piece_len)]
    if not sentences:
        return []

    chunks = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence_len = len(sentence) + 1
        if current and current_len + sentence_len > size:
            chunks.append(" ".join(current))
            overlap_sentences: list[str] = []
            overlap_len = 0
            for s in reversed(current):
                if overlap_len >= overlap:
                    break
                overlap_sentences.insert(0, s)
                overlap_len += len(s) + 1
            current = overlap_sentences
            current_len = overlap_len
        current.append(sentence)
        current_len += sentence_len

    if current:
        chunks.append(" ".join(current))
    return chunks


class _OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, client: OllamaClient, model: str):
        self.client = client
        self.model = model

    def __call__(self, input: list[str]) -> list[list[float]]:
        return self.client.embed(self.model, input)

    @staticmethod
    def name() -> str:
        return "ollama_nomic_embed_text"

    def get_config(self) -> dict:
        return {"model": self.model}

    @staticmethod
    def build_from_config(config: dict) -> "_OllamaEmbeddingFunction":
        from agents.ollama_client import OllamaClient as _OC
        return _OllamaEmbeddingFunction(_OC("http://127.0.0.1:11434"), config.get("model", EMBED_MODEL))


class KnowledgeBase:
    def __init__(self, ollama_client: OllamaClient):
        self.chroma = chromadb.PersistentClient(path=str(KB_DIR / "chroma"))
        self.embed_fn = _OllamaEmbeddingFunction(ollama_client, EMBED_MODEL)
        self.collection = self.chroma.get_or_create_collection(
            name="knowledge", embedding_function=self.embed_fn
        )

    def _add_chunks(self, ids: list[str], chunks: list[str], metadatas: list[dict],
                     dek: bytes | None, key_generation: int | None) -> None:
        embeddings = self.embed_fn(chunks)
        if dek is not None:
            stored_docs = [crypto_utils.encrypt_text(dek, c).decode("ascii") for c in chunks]
            metadatas = [{**m, "key_generation": key_generation} for m in metadatas]
        else:
            stored_docs = chunks
        self.collection.add(ids=ids, embeddings=embeddings, documents=stored_docs, metadatas=metadatas)

    def _docs_dir(self, user_id: str | None) -> Path:
        d = DOCS_DIR / user_id if user_id else DOCS_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_document(self, filename: str, content: bytes, user_id: str | None = None,
                      dek: bytes | None = None, key_generation: int | None = None) -> int:
        filename = _sanitize_filename(filename)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / filename
            tmp_path.write_bytes(content)
            text = _extract_text(tmp_path)
        chunks = _chunk_text(text)
        if not chunks:
            return 0

        self.delete_document(filename, user_id=user_id)
        docs_dir = self._docs_dir(user_id)
        if dek is not None:
            (docs_dir / f"{filename}.enc").write_bytes(crypto_utils.encrypt_bytes(dek, content))
        else:
            (docs_dir / filename).write_bytes(content)

        ids = [f"{filename}::{i}::{uuid.uuid4().hex[:8]}" for i in range(len(chunks))]
        metadatas = [{"source": filename, "chunk": i, "type": "document"} for i in range(len(chunks))]
        if user_id:
            metadatas = [{**m, "user_id": user_id} for m in metadatas]
        self._add_chunks(ids, chunks, metadatas, dek, key_generation)
        return len(chunks)

    def add_conversation(self, session_id: str, user_message: str, assistant_message: str,
                          user_id: str | None = None,
                          dek: bytes | None = None, key_generation: int | None = None) -> None:
        text = f"Pregunta: {user_message}\nRespuesta: {assistant_message}"
        source = f"conversacion:{session_id}"
        doc_id = f"{source}::{uuid.uuid4().hex}"
        metadata = {"source": source, "type": "conversation", "session_id": session_id}
        if user_id:
            metadata["user_id"] = user_id
        self._add_chunks([doc_id], [text], [metadata], dek, key_generation)

    def delete_conversation(self, session_id: str) -> None:
        self.collection.delete(where={"session_id": session_id})

    def delete_all_for_user(self, user_id: str) -> None:
        self.collection.delete(where={"user_id": user_id})
        user_docs_dir = DOCS_DIR / user_id
        if user_docs_dir.exists():
            shutil.rmtree(user_docs_dir)

    def delete_document(self, filename: str, user_id: str | None = None) -> None:
        filename = _sanitize_filename(filename)
        where = {"$and": [{"source": filename}, {"user_id": user_id}]} if user_id else {"source": filename}
        self.collection.delete(where=where)
        docs_dir = self._docs_dir(user_id)
        for stored_path in (docs_dir / filename, docs_dir / f"{filename}.enc"):
            stored_path.unlink(missing_ok=True)

    def encrypt_plain_originals(self, user_id: str, dek: bytes) -> int:
        d = DOCS_DIR / user_id
        if not d.exists():
            return 0
        n = 0
        for path in d.iterdir():
            if path.is_file() and path.suffix != ".enc":
                path.with_name(path.name + ".enc").write_bytes(crypto_utils.encrypt_bytes(dek, path.read_bytes()))
                path.unlink()
                n += 1
        return n

    def list_documents(self, user_id: str | None = None) -> list[dict]:
        where = {"$and": [{"type": "document"}, {"user_id": user_id}]} if user_id else {"type": "document"}
        all_items = self.collection.get(where=where)
        sources: dict[str, int] = {}
        for meta in all_items.get("metadatas", []):
            src = meta["source"]
            sources[src] = sources.get(src, 0) + 1
        return [{"filename": k, "chunks": v} for k, v in sorted(sources.items())]

    def add_context_note(self, text: str, user_id: str | None = None,
                          dek: bytes | None = None, key_generation: int | None = None) -> str:
        doc_id = f"nota:{uuid.uuid4().hex}"
        metadata = {"source": "nota manual", "type": "note"}
        if user_id:
            metadata["user_id"] = user_id
        self._add_chunks([doc_id], [text], [metadata], dek, key_generation)
        return doc_id

    def list_memory_entries(self, user_id: str | None = None,
                             dek: bytes | None = None, key_generation: int | None = None) -> list[dict]:
        where = {
            "$and": [{"type": {"$in": ["note", "conversation"]}}, {"user_id": user_id}]
        } if user_id else {"type": {"$in": ["note", "conversation"]}}
        items = self.collection.get(where=where)
        entries = []
        for doc_id, doc, meta in zip(items["ids"], items["documents"], items["metadatas"]):
            row_key_generation = meta.get("key_generation")
            if dek is not None and row_key_generation is not None:
                if row_key_generation != key_generation:
                    continue
                decrypted = crypto_utils.decrypt_text(dek, doc.encode("ascii"))
                doc = decrypted if decrypted is not None else ORPHANED_PLACEHOLDER
            entries.append({"id": doc_id, "text": doc, "type": meta.get("type", "conversation")})
        return entries

    def update_memory_entry(self, entry_id: str, text: str, user_id: str | None = None,
                             dek: bytes | None = None, key_generation: int | None = None) -> bool:
        existing = self.collection.get(ids=[entry_id])
        if not existing["ids"] or existing["metadatas"][0].get("type") != "note":
            return False
        metadata = existing["metadatas"][0]
        if user_id and metadata.get("user_id") != user_id:
            return False
        self.collection.delete(ids=[entry_id])
        self._add_chunks([entry_id], [text], [metadata], dek, key_generation)
        return True

    def delete_memory_entry(self, entry_id: str, user_id: str | None = None) -> bool:
        existing = self.collection.get(ids=[entry_id])
        if not existing["ids"]:
            return False
        if user_id and existing["metadatas"][0].get("user_id") != user_id:
            return False
        self.collection.delete(ids=[entry_id])
        return True

    def query(self, text: str, k: int = 4, user_id: str | None = None,
              dek: bytes | None = None, key_generation: int | None = None) -> list[dict]:
        if self.collection.count() == 0:
            return []

        fetch_n = min(max(k * 3, 8), self.collection.count())
        query_kwargs = {"query_texts": [text], "n_results": fetch_n}
        if user_id:
            query_kwargs["where"] = {"user_id": user_id}
        results = self.collection.query(**query_kwargs)
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]
        if not dists:
            return []

        max_dist = max(dists) or 1.0
        query_words = {w.lower() for w in _WORD_RE.findall(text) if len(w) > 2}

        candidates = []
        for doc, meta, dist in zip(docs, metas, dists):
            row_key_generation = meta.get("key_generation")
            if dek is not None and row_key_generation is not None:
                if row_key_generation != key_generation:
                    continue
                decrypted = crypto_utils.decrypt_text(dek, doc.encode("ascii"))
                if decrypted is None:
                    continue
                doc = decrypted

            vector_score = 1 - (dist / max_dist)
            doc_words = {w.lower() for w in _WORD_RE.findall(doc)}
            lexical_score = len(query_words & doc_words) / len(query_words) if query_words else 0.0
            combined = 0.6 * vector_score + 0.4 * lexical_score
            candidates.append({
                "text": doc, "source": meta["source"], "distance": dist, "combined_score": combined,
            })

        if not candidates:
            return []
        candidates.sort(key=lambda c: c["combined_score"], reverse=True)
        best_score = candidates[0]["combined_score"]
        relevant = [c for c in candidates if c["combined_score"] >= best_score - 0.35]
        return relevant[:k]
