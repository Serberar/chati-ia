"""Rutas de conversaciones: listar, renombrar y borrar, editar mensajes y documentos adjuntos."""
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from agents import comfyui_client
from api.replies import MAX_DOC_BYTES, read_upload, remember
from chat import memory, session_docs
from infra.core import knowledge_base
from media import media_store

router = APIRouter()


@router.get("/sessions")
def get_sessions(request: Request):
    session = request.state.session
    return memory.list_sessions(user_id=session["user_id"], dek=session["dek"], key_generation=session["key_generation"])


def attached_docs(session_id: str, message: str, auth_session: dict) -> tuple[str, list[dict]]:
    if not auth_session.get("user_id"):
        return "", []
    return session_docs.context_for(auth_session["user_id"], session_id, message,
                                    auth_session["dek"], auth_session["key_generation"])


def with_docs(message: str, docs_context: str) -> str:
    return f"{message}\n\n{docs_context}" if docs_context else message


def own_session_id(session_id: str | None, auth_session: dict) -> str:
    sid = _resolve_session_id(session_id, auth_session)
    comfyui_client.note_conversation(comfyui_client.current_owner.get(), sid)
    return sid


def _resolve_session_id(session_id: str | None, auth_session: dict) -> str:
    started = auth_session.setdefault("chat_sessions", set())
    if session_id:
        owner = memory.session_owner(session_id)
        if owner == auth_session["user_id"] and owner is not None:
            return session_id
        if owner is None and (session_id in started or not memory.session_exists(session_id)):
            started.add(session_id)
            return session_id
    new_id = memory.new_session_id()
    started.add(new_id)
    return new_id


def owns_session(request: Request, session_id: str) -> bool:
    user_id = request.state.session["user_id"]
    return user_id is not None and memory.session_owner(session_id) == user_id


def _not_your_session() -> JSONResponse:
    return JSONResponse({"detail": "Conversacion no encontrada."}, status_code=404)
ATTACHED_DOC_PREFIX = "📄 Documento adjuntado: "


@router.post("/sessions/docs")
def attach_session_doc(request: Request, file: UploadFile = File(...), session_id: str | None = Form(None)):
    session = request.state.session
    session_id = own_session_id(session_id, session)
    try:
        doc = session_docs.save(session["user_id"], session_id, file.filename or "documento.txt",
                                read_upload(file, MAX_DOC_BYTES), session["dek"], session["key_generation"])
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    remember(session_id, session, "user", f"{ATTACHED_DOC_PREFIX}{doc['name']}", agent="adjunto")
    return {"session_id": session_id, "document": doc,
            "documents": session_docs.list_docs(session["user_id"], session_id)}


@router.get("/sessions/{session_id}/docs")
def list_session_docs(session_id: str, request: Request):
    session = request.state.session
    if session["role"] == "guest":
        return []
    return session_docs.list_docs(session["user_id"], session_id)


@router.delete("/sessions/{session_id}/docs/{filename}")
def remove_session_doc(session_id: str, filename: str, request: Request):
    session = request.state.session
    session_docs.remove(session["user_id"], session_id, filename)
    return {"ok": True}


@router.post("/sessions/{session_id}/docs/{filename}/keep")
def keep_session_doc(session_id: str, filename: str, request: Request):
    session = request.state.session
    content = session_docs.get_original(session["user_id"], session_id, filename,
                                        session["dek"], session["key_generation"])
    if content is None:
        return JSONResponse({"detail": "Documento no encontrado."}, status_code=404)
    knowledge_base.add_document(filename, content, user_id=session["user_id"],
                                dek=session["dek"], key_generation=session["key_generation"])
    return {"ok": True}


@router.get("/sessions/{session_id}")
def get_session_history(session_id: str, request: Request):
    session = request.state.session
    if not owns_session(request, session_id):
        return _not_your_session()
    return memory.get_history(session_id, limit=200, dek=session["dek"], key_generation=session["key_generation"])


@router.put("/sessions/{session_id}/title")
def rename_session(session_id: str, request: Request, title: str = Form(...)):
    session = request.state.session
    if not owns_session(request, session_id):
        return _not_your_session()
    title = title.strip()[:80]
    if not title:
        return JSONResponse({"detail": "El nombre no puede estar vacio."}, status_code=400)
    memory.set_session_title(session_id, title, user_id=session["user_id"],
                              dek=session["dek"], key_generation=session["key_generation"])
    return {"ok": True, "title": title}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request):
    if not owns_session(request, session_id):
        return _not_your_session()
    _delete_conversation(request.state.session, session_id)
    return {"ok": True}


@router.delete("/sessions")
def delete_all_sessions(request: Request):
    session = request.state.session
    if not session.get("user_id"):
        return JSONResponse({"detail": "Hay que iniciar sesion para borrar el historial."}, status_code=403)
    ids = [s["session_id"] for s in memory.list_sessions(limit=1_000_000, user_id=session["user_id"])]
    for session_id in ids:
        _delete_conversation(session, session_id)
    return {"ok": True, "deleted": len(ids)}


def _delete_conversation(session: dict, session_id: str) -> None:
    names = {m["media"] for m in memory.get_history(session_id, limit=100000) if m.get("media")}
    for name in names:
        media_store.delete(name)
    memory.clear_session(session_id)
    knowledge_base.delete_conversation(session_id)
    session_docs.delete_session(session["user_id"], session_id)


@router.put("/sessions/{session_id}/messages/{message_id}")
def edit_message(session_id: str, message_id: int, request: Request, content: str = Form(...)):
    session = request.state.session
    if not owns_session(request, session_id) or memory.message_session(message_id) != session_id:
        return _not_your_session()
    ok = memory.update_message(message_id, content, dek=session["dek"], key_generation=session["key_generation"])
    return {"ok": ok}


@router.delete("/sessions/{session_id}/messages/{message_id}")
def delete_message(session_id: str, message_id: int, request: Request):
    if not owns_session(request, session_id) or memory.message_session(message_id) != session_id:
        return _not_your_session()
    ok = memory.delete_message(message_id)
    return {"ok": ok}
