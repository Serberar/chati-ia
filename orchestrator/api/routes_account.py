"""Rutas de la cuenta: vincular dispositivos, CV, avatar, documentos de conocimiento y memoria."""
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from accounts import devices, profile_store
from api import security
from api.replies import MAX_DOC_BYTES, read_upload
from infra.core import knowledge_base
from infra.paths import ORCH_DIR

router = APIRouter()


@router.get("/pair")
def pair_page():
    return FileResponse(ORCH_DIR / "static" / "pair.html")


class PairClaim(BaseModel):
    code: str
    name: str = "Dispositivo"


@router.post("/pair/claim")
def pair_claim(body: PairClaim, request: Request):
    if not security.is_remote_host(request.headers.get("host", "")):
        return JSONResponse({"detail": "Abre esta pagina desde el dispositivo que quieres vincular."},
                            status_code=400)
    token = devices.claim(body.code, body.name)
    if token is None:
        return JSONResponse({"detail": "Codigo no valido o caducado. Pide otro en el ordenador."},
                            status_code=403)
    resp = JSONResponse({"ok": True})
    _set_device_cookie(resp, token)
    return resp


def _set_device_cookie(resp, token: str) -> None:
    resp.set_cookie(devices.COOKIE_NAME, token, max_age=400 * 24 * 3600, httponly=True, secure=True,
                    samesite="lax", path="/")


@router.get("/pair/check")
def pair_check(request: Request):
    device = getattr(request.state, "device", None)
    if device is None:
        return {"paired": False}
    resp = JSONResponse({"paired": True})
    _set_device_cookie(resp, request.cookies.get(devices.COOKIE_NAME, ""))
    return resp


@router.post("/devices/pair")
def devices_pair(request: Request):
    session = request.state.session
    if getattr(request.state, "device", None) is not None:
        return JSONResponse({"detail": "Los dispositivos se vinculan desde el ordenador."}, status_code=403)
    if not session.get("user_id"):
        return JSONResponse({"detail": "Hay que iniciar sesion."}, status_code=403)
    if not security.REMOTE_HOSTS:
        return JSONResponse({"detail": "Falta la direccion de Tailscale de este ordenador (data/remote_hosts.txt)."},
                            status_code=400)
    import segno
    pairing = devices.start_pairing(session["user_id"])
    host = min(security.REMOTE_HOSTS)
    url = f"https://{host}/pair#{pairing['secret']}"
    qr = segno.make(url, error="m").svg_data_uri(scale=6, border=2)
    return {"url": f"https://{host}/pair", "qr": qr, "code": pairing["short"],
            "expires_in": pairing["expires_in"]}


@router.get("/devices")
def devices_list(request: Request):
    session = request.state.session
    if not session.get("user_id"):
        return []
    current = getattr(request.state, "device", None)
    return [dict(d, current=bool(current and current["id"] == d["id"]))
            for d in devices.list_for(session["user_id"])]


@router.delete("/devices/{device_id}")
def devices_revoke(device_id: str, request: Request):
    session = request.state.session
    if not session.get("user_id") or not devices.revoke(device_id, session["user_id"]):
        return JSONResponse({"detail": "No existe ese dispositivo."}, status_code=404)
    return {"ok": True}


@router.get("/cv")
def get_cv_status(request: Request):
    session = request.state.session
    filename = profile_store.cv_filename(user_id=session["user_id"])
    return {"has_cv": filename is not None, "filename": filename}


@router.post("/cv")
def upload_cv(request: Request, file: UploadFile = File(...)):
    session = request.state.session
    try:
        content = read_upload(file, MAX_DOC_BYTES)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=413)
    saved = profile_store.save_cv(file.filename or "cv.pdf", content, user_id=session["user_id"],
                                   dek=session["dek"], key_generation=session["key_generation"])
    return {"ok": True, "filename": saved.name.removesuffix(".enc")}


@router.get("/profile/avatar")
def get_avatar(request: Request):
    session = request.state.session
    data = profile_store.get_avatar_bytes(session["user_id"], session["dek"], session["key_generation"])
    if data is None:
        return JSONResponse({"detail": "Sin avatar."}, status_code=404)
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/profile/avatar")
def upload_avatar(request: Request, file: UploadFile = File(...)):
    session = request.state.session
    try:
        profile_store.save_avatar(read_upload(file), session["user_id"], session["dek"], session["key_generation"])
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"ok": True}


@router.delete("/profile/avatar")
def delete_avatar(request: Request):
    session = request.state.session
    profile_store.delete_avatar(session["user_id"])
    return {"ok": True}


@router.get("/knowledge")
def list_knowledge(request: Request):
    session = request.state.session
    return knowledge_base.list_documents(user_id=session["user_id"])


@router.post("/knowledge")
def add_knowledge(request: Request, file: UploadFile = File(...)):
    session = request.state.session
    filename = file.filename or f"{uuid.uuid4().hex}.txt"
    try:
        n_chunks = knowledge_base.add_document(filename, read_upload(file, MAX_DOC_BYTES), user_id=session["user_id"],
                                                dek=session["dek"], key_generation=session["key_generation"])
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "filename": filename, "chunks": n_chunks}


@router.delete("/knowledge/{filename}")
def delete_knowledge(filename: str, request: Request):
    session = request.state.session
    knowledge_base.delete_document(filename, user_id=session["user_id"])
    return {"ok": True}


@router.get("/memory/entries")
def list_memory_entries(request: Request):
    session = request.state.session
    return knowledge_base.list_memory_entries(user_id=session["user_id"],
                                               dek=session["dek"], key_generation=session["key_generation"])


@router.post("/memory/entries")
def add_memory_entry(request: Request, text: str = Form(...)):
    session = request.state.session
    text = text.strip()
    if not text:
        return JSONResponse({"detail": "El texto no puede estar vacio."}, status_code=400)
    entry_id = knowledge_base.add_context_note(text, user_id=session["user_id"],
                                                dek=session["dek"], key_generation=session["key_generation"])
    return {"ok": True, "id": entry_id}


@router.put("/memory/entries/{entry_id}")
def update_memory_entry(entry_id: str, request: Request, text: str = Form(...)):
    session = request.state.session
    text = text.strip()
    if not text:
        return JSONResponse({"detail": "El texto no puede estar vacio."}, status_code=400)
    ok = knowledge_base.update_memory_entry(entry_id, text, user_id=session["user_id"],
                                             dek=session["dek"], key_generation=session["key_generation"])
    if not ok:
        return JSONResponse({"detail": "No se pudo editar (no existe, no es tuyo, o no es una nota manual)."},
                             status_code=404)
    return {"ok": True}


@router.delete("/memory/entries/{entry_id}")
def delete_memory_entry(entry_id: str, request: Request):
    session = request.state.session
    ok = knowledge_base.delete_memory_entry(entry_id, user_id=session["user_id"])
    if not ok:
        return JSONResponse({"detail": "No se encontro esa entrada (o no es tuya)."}, status_code=404)
    return {"ok": True}
