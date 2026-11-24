import contextlib
import contextvars
import json
import logging
import queue
import re
import secrets
import threading
import time
from functools import partial
from pathlib import Path

import requests
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

import installer_download_models
from accounts import auth, auth_sessions, profile_store, push, task_owners
from agents import comfyui_client
from agents import video_agent as video_agent_module
from agents.ollama_client import OllamaClient
from api import (
    access,
    routes_account,
    routes_agent,
    routes_apps,
    routes_auth,
    routes_media,
    routes_models,
    routes_push,
    routes_pwa,
    routes_sessions,
    routes_work,
    security,
)
from api.replies import (
    MAX_SPEAK_CHARS,
    assistant_reply,
    generation_error_message,
    read_upload,
    remember,
    with_bytes,
)
from api.schemas import ChatRequest, ChatResponse
from chat import (
    deep_search,
    file_access,
    gen_options,
    job_search,
    memory,
    night_queue,
    plans,
    prompt_writer,
    session_docs,
    shopping,
    tools,
    video_replies,
)
from coding import agent_attachments, agent_watch, opencode_client, project_watch
from infra import computers, metrics, paths
from infra.core import (
    AGENTS,
    CONFIG,
    image_agent,
    knowledge_base,
    log,
    ollama,
    router,
    verifier,
    video_agent,
    vision_agent,
    voice_agent,
)
from media import media_store, video_pipeline
from models import gpu_memory, llm_proxy, llm_status, model_choice

_logger = logging.getLogger(__name__)

opencode_client.WORKDIR = agent_attachments.AGENT_DIR
video_agent.on_start = lambda text: gen_options.report(text)


def _loading_event(model: str) -> str:
    return json.dumps({"type": "status",
                       "text": f"Cargando el modelo {model}… la primera respuesta tarda más"}) + "\n"


def _index_in_background(session_id: str, message: str, answer: str, user_id: str | None,
                         dek: bytes | None, key_generation: int | None) -> None:
    if not user_id:
        return

    def work():
        try:
            knowledge_base.add_conversation(session_id, message, answer, user_id=user_id,
                                            dek=dek, key_generation=key_generation)
        except Exception as exc:
            log.warning("No se pudo indexar la conversacion en la memoria larga: %s", exc)
    threading.Thread(target=work, daemon=True).start()


comfyui_client.before_submit = gpu_memory.free_memory_for_generation
llm_status.OLLAMA_URL = CONFIG["ollama"]["base_url"]
OllamaClient.gpu_busy = staticmethod(lambda: comfyui_client.gpu_busy(CONFIG["comfyui"]["base_url"]))
opencode_client.before_task = gpu_memory.free_memory_for_agent

OUTPUT_DIR = paths.OUTPUT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@contextlib.asynccontextmanager
async def _lifespan(_app):
    removed = media_store.cleanup_tmp()
    if removed:
        log.info("Temporales huerfanos borrados: %d", removed)
    old_media = media_store.cleanup_old_media()
    if old_media:
        log.info("Imagenes/videos generados de hace mas de %d dias borrados: %d",
                 media_store.MEDIA_MAX_AGE_DAYS, old_media)
    purged = memory.purge_guest_messages(older_than_hours=24)
    if purged:
        log.info("Mensajes de invitado antiguos borrados: %d", purged)
    threading.Thread(target=routes_push.watch, daemon=True).start()
    threading.Thread(target=installer_download_models.download_new_base, daemon=True).start()
    threading.Thread(target=agent_watch.resume_agent_watches, daemon=True).start()
    threading.Thread(target=project_watch.run_forever, name="vigilancia-proyectos", daemon=True,
                     args=(lambda: bool(agent_watch.code_watch_running or agent_watch.agent_watch_running),)).start()
    log.info("Orquestador arrancado")
    yield


app = FastAPI(title="IA personal - orquestador", lifespan=_lifespan)


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception):
    log.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Error interno. Esta anotado en el registro de Chati."}, status_code=500)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS" or auth.is_public_path(request.url.path):
            return await call_next(request)
        token = access.session_token(request)
        session = auth_sessions.get_session(token) if token else None
        if session is None:
            return JSONResponse({"detail": "No autorizado. Inicia sesion."}, status_code=401)
        device = getattr(request.state, "device", None)
        if device is not None and device["user_id"] != session.get("user_id"):
            return JSONResponse({"detail": "Este dispositivo esta vinculado a otro usuario."}, status_code=403)
        path = request.url.path
        if session["role"] == "guest" and not access.guest_may_use(path):
            return access.guest_blocked()
        if path.startswith(access.PC_PATH_PREFIXES) and not access.can_use_pc(session):
            return access.pc_blocked()
        request.state.session = session
        comfyui_client.current_owner.set(access.owner_of(session))
        _mark_activity(True, request.method)
        try:
            return await call_next(request)
        finally:
            _mark_activity(False, request.method)


app.add_middleware(SessionAuthMiddleware)
app.add_middleware(security.LocalOnlyMiddleware)


def _remote_hosts() -> set[str]:
    hosts = set((CONFIG.get("remote") or {}).get("hosts") or [])
    extra = paths.DATA_DIR / "remote_hosts.txt"
    if extra.exists():
        hosts |= {line.strip() for line in extra.read_text(encoding="utf-8").splitlines() if line.strip()}
    return {h.lower().rstrip(".") for h in hosts}


security.REMOTE_HOSTS |= _remote_hosts()


def _add_own_tailscale_host() -> None:
    host = computers.this_host()
    if host:
        security.REMOTE_HOSTS.add(host)
        log.info("Acceso desde fuera por %s", host)


threading.Thread(target=_add_own_tailscale_host, daemon=True).start()


def _on_login(login: dict) -> None:
    try:
        knowledge_base.encrypt_plain_originals(login["id"], login["dek"])
    except OSError:
        _logger.debug("_on_login: se sigue sin ello", exc_info=True)


def _delete_user_data(user_id: str) -> None:
    memory.delete_user_messages(user_id)
    profile_store.delete_all_for_user(user_id)
    knowledge_base.delete_all_for_user(user_id)
    session_docs.delete_all_for_user(user_id)
    task_owners.forget_user(user_id)
    push.forget_user(user_id)


routes_auth.configure(on_login=_on_login, delete_user_data=_delete_user_data)
app.include_router(routes_auth.router)


_last_user_action = 0.0
_in_flight = 0
_activity_lock = threading.Lock()
IDLE_AFTER_SECONDS = 15 * 60


def _mark_activity(start: bool, method: str) -> None:
    global _last_user_action, _in_flight
    with _activity_lock:
        _in_flight += 1 if start else -1
        if method not in ("GET", "HEAD", "OPTIONS"):
            _last_user_action = time.time()


def _is_busy() -> bool:
    if _in_flight > 0 or time.time() - _last_user_action < IDLE_AFTER_SECONDS:
        return True
    for module in (job_search, shopping, deep_search):
        if any(run.get("running") for run in list(module._runs.values())):
            return True
    try:
        if opencode_client.busy_session_ids(CONFIG["opencode"]["base_url"]):
            return True
        if sum(comfyui_client.user_queue(CONFIG["comfyui"]["base_url"])):
            return True
    except Exception:
        _logger.debug("_is_busy: se sigue sin ello", exc_info=True)
    return False


@app.get("/health")
def health(request: Request, busy: bool = False):
    if busy and security.is_local_host(request.headers.get("host", "")):
        return {"status": "ok", "busy": _is_busy()}
    response = JSONResponse({"status": "ok"})
    if request.headers.get("origin") == access.LAUNCHER_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = access.LAUNCHER_ORIGIN
    return response


@app.get("/computers")
def computers_list():
    return computers.list_computers()


AGENT_KEEP_ALIVE = "30m"
_keep_alive_sent: dict[str, float] = {}


def _keep_agent_model_loaded(model: str | None) -> None:
    if not model or model not in gpu_memory.agent_models() or time.time() - _keep_alive_sent.get(model, 0) < 60:
        return
    _keep_alive_sent[model] = time.time()

    def send():
        try:
            requests.post(f"{CONFIG['ollama']['base_url']}/api/generate",
                          json={"model": model, "keep_alive": AGENT_KEEP_ALIVE}, timeout=900)
        except requests.RequestException:
            _logger.debug("send: se sigue sin ello", exc_info=True)

    threading.Thread(target=send, daemon=True).start()


@app.api_route("/llm/v1/{path:path}", methods=["GET", "POST"])
async def llm_proxy_route(path: str, request: Request):
    expected = f"Bearer {opencode_client.AUTH[1]}"
    if not secrets.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
        return JSONResponse({"detail": "No autorizado."}, status_code=401)
    if not re.fullmatch(r"[A-Za-z0-9_\-/.]*", path) or ".." in path or "//" in path:
        return JSONResponse({"detail": "Ruta no permitida."}, status_code=400)
    target = f"{CONFIG['ollama']['base_url']}/v1/{path}"
    body = llm_proxy.disable_thinking(await request.body(), set(CONFIG["opencode"].get("no_think_models", [])))
    body = llm_proxy.cpu_when_gpu_busy(body, comfyui_client.gpu_busy(CONFIG["comfyui"]["base_url"]))
    body = llm_proxy.hide_secrets(llm_proxy.annotate_tool_results(body))
    _keep_agent_model_loaded(llm_proxy.model_of(body))
    headers = {"Content-Type": request.headers.get("content-type", "application/json")}
    wants_stream = b'"stream":true' in body.replace(b" ", b"")

    def forward():
        return requests.request(request.method, target, data=body or None, headers=headers,
                                stream=wants_stream, timeout=(10, 3600))

    rid = llm_status.start(body, llm_proxy.model_of(body))
    try:
        upstream = await run_in_threadpool(forward)
    except requests.RequestException:
        llm_status.finish(rid)
        raise
    if not wants_stream:
        llm_status.finish(rid, wrote=upstream.ok)
        content = upstream.content
        if upstream.ok and b"tool_calls" in content:
            try:
                content = json.dumps(llm_proxy.clean_completion(upstream.json()), ensure_ascii=False).encode("utf-8")
            except ValueError:
                _logger.debug("llm_proxy_route: se sigue sin ello", exc_info=True)
        return Response(content=content, status_code=upstream.status_code,
                        media_type=upstream.headers.get("content-type", "application/json"))

    def stream():
        text_calls = llm_proxy.TextToolCalls()
        try:
            for line in upstream.iter_lines():
                llm_status.output(rid, line)
                for out in text_calls.feed(llm_proxy.clean_stream_line(line)) if line else [b""]:
                    yield out + b"\n\n" if out else b""
            for out in text_calls.finish():
                yield out + b"\n\n"
        finally:
            llm_status.finish(rid)
            upstream.close()
    return StreamingResponse(stream(), status_code=upstream.status_code,
                             media_type=upstream.headers.get("content-type", "text/event-stream"))


@app.get("/metrics/summary", dependencies=[access.admin_only("Solo un administrador puede ver esto.")])
def metrics_summary(request: Request, last_n: int = 2000):
    return metrics.summary(last_n=min(max(last_n, 1), 20000))


@app.get("/plan/{session_id}")
def get_plan(session_id: str, request: Request):
    auth_session = request.state.session
    if not (routes_sessions.owns_session(request, session_id) or session_id in auth_session.get("chat_sessions", set())):
        return {"pasos": []}
    return {"pasos": plans.get_plan(session_id)}


app.include_router(routes_models.router)


app.include_router(routes_work.router)


app.include_router(routes_agent.router)


APPS_NUM_CTX = 8192
APPS_NUM_PREDICT = 2000


def _job_chat(prompt: str) -> str:
    return ollama.chat(CONFIG["opencode"]["model"], [{"role": "user", "content": prompt}],
                       temperature=0.2, think=False, num_ctx=APPS_NUM_CTX, num_predict=APPS_NUM_PREDICT)


def _describe_product_image(b64: str) -> str:
    gpu_memory.ensure_active_model(vision_agent.model)
    try:
        return "".join(vision_agent.respond_with_image_stream(shopping.IMAGE_PROMPT, b64))
    finally:
        ollama.unload(vision_agent.model)


routes_apps.configure(chat=_job_chat,
                      before=lambda: gpu_memory.free_memory_for_agent(CONFIG["opencode"]["agent"], wait=True),
                      describe_image=_describe_product_image)
app.include_router(routes_apps.router)


app.include_router(routes_push.router)


app.include_router(routes_media.router)


app.include_router(routes_pwa.router)


app.include_router(routes_account.router)


class _RevalidatedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _RevalidatedStaticFiles(directory=Path(__file__).parent / "static"), name="static")


PC_TOOLS = {"leer_archivo", "listar_carpeta", "ejecutar_python", "delegar_a_agente_de_codigo"}
OWN_DATA_TOOLS = {"buscar_en_memoria", "listar_documentos"}


def _execute_tool(name: str, arguments: dict, session_id: str, user_id: str | None = None,
                   dek: bytes | None = None, key_generation: int | None = None,
                   pc_access: bool = False) -> tuple[str, list[dict] | None]:
    if name in PC_TOOLS and not pc_access:
        return "Esta cuenta no tiene permiso para usar el ordenador (archivos, codigo, agente).", None
    if name in OWN_DATA_TOOLS and not user_id:
        return "En modo invitado no hay memoria ni documentos guardados.", None
    if name == "actualizar_plan":
        pasos = (arguments or {}).get("pasos", []) if isinstance(arguments, dict) else []
        if not pasos:
            return "Falta la lista de pasos.", None
        plans.set_plan(session_id, pasos)
        text = "Plan actualizado:\n" + "\n".join(
            f"[{p.get('estado', 'pendiente')}] {p.get('texto', '')}" for p in pasos
        )
        return text, None

    if name == "fecha_actual":
        text = tools.fecha_actual()
        return text, [{"source": "sistema:fecha_actual", "text": text}]

    if name == "buscar_en_memoria":
        query = (arguments or {}).get("consulta", "") if isinstance(arguments, dict) else ""
        if not query:
            return "Falta indicar que buscar.", None
        results = knowledge_base.query(query, k=4, user_id=user_id, dek=dek, key_generation=key_generation)
        if not results:
            return "No se encontro nada relevante en la memoria ni en los documentos.", None
        text = "\n\n---\n\n".join(f"[{r['source']}] {r['text']}" for r in results)
        return text, results

    if name == "listar_documentos":
        docs = knowledge_base.list_documents(user_id=user_id)
        if not docs:
            return "No hay documentos subidos todavia.", [{"source": "sistema:listar_documentos", "text": "No hay documentos subidos."}]
        text = "Documentos: " + ", ".join(d["filename"] for d in docs)
        return text, [{"source": "sistema:listar_documentos", "text": text}]

    if name == "leer_archivo":
        ruta = (arguments or {}).get("ruta", "") if isinstance(arguments, dict) else ""
        if not ruta:
            return "Falta indicar la ruta.", None
        text = file_access.leer_archivo(ruta)
        return text, [{"source": f"archivo:{ruta}", "text": text}]

    if name == "listar_carpeta":
        ruta = (arguments or {}).get("ruta", "") if isinstance(arguments, dict) else ""
        if not ruta:
            return "Falta indicar la ruta.", None
        text = file_access.listar_carpeta(ruta)
        return text, [{"source": f"carpeta:{ruta}", "text": text}]

    if name == "ejecutar_python":
        codigo = (arguments or {}).get("codigo", "") if isinstance(arguments, dict) else ""
        if not codigo:
            return "Falta el codigo a ejecutar.", None
        text = tools.ejecutar_python(codigo)
        return text, [{"source": "sistema:ejecutar_python", "text": text}]

    if name == "delegar_a_agente_de_codigo":
        tarea = (arguments or {}).get("tarea", "") if isinstance(arguments, dict) else ""
        if not tarea:
            return "Falta describir la tarea.", None
        text, task_id = opencode_client.delegate(CONFIG["opencode"]["base_url"], tarea,
                                                 CONFIG["opencode"]["agent"])
        task_owners.record(task_id, user_id)
        agent_watch.start_agent_watch(task_id)
        return text, [{"source": "sistema:delegar_a_agente_de_codigo", "text": text, "agent_task_id": task_id}]

    return f"Herramienta desconocida: {name}", None


def _delegated_task_id(evidence: list[dict] | None) -> str | None:
    return next((e["agent_task_id"] for e in evidence or [] if e.get("agent_task_id")), None)


def _resolve_agent(message: str, agent_override: str | None) -> tuple[str, bool]:
    if agent_override in (AGENTS.keys() | {"image", "video", "opencode"}):
        return agent_override, True
    route = router.classify(message)
    return route["agent"], route["factual"]


def _tools_for(agent_name: str, pc_access: bool = True, guest: bool = False) -> list[dict]:
    defs = tools.TOOL_DEFS if agent_name == "code" else \
        [t for t in tools.TOOL_DEFS if t["function"]["name"] != "delegar_a_agente_de_codigo"]
    hidden = (set() if pc_access else PC_TOOLS) | (OWN_DATA_TOOLS if guest else set())
    return [t for t in defs if t["function"]["name"] not in hidden]


_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def _fix_language(answer: str, message: str, model: str) -> str:
    if not _CJK.search(answer) or _CJK.search(message):
        return answer
    try:
        fixed = ollama.chat(model, [{"role": "user", "content": (
            "Este texto mezcla español con otro idioma. Reescribelo entero solo en español, sin "
            "cambiar el contenido ni el formato (markdown, listas, codigo). Devuelve solo el "
            "texto reescrito.\n\n" + answer)}], temperature=0.2, think=False)
    except Exception as exc:
        log.warning("No se pudo corregir el idioma de la respuesta: %s", exc)
        return answer
    return fixed.strip() if fixed.strip() and not _CJK.search(fixed) else answer


def _generate_response(message: str, agent_name: str, is_factual: bool, session_id: str,
                        auth_session: dict, model_profile: str | None = None,
                        verify: bool = True, image_model: str | None = None,
                        video_model: str | None = None) -> ChatResponse:
    dek = auth_session["dek"]
    key_generation = auth_session["key_generation"]
    user_id = auth_session["user_id"]
    override_model = model_choice.profile_model(model_profile)
    think = model_choice.profile_think(model_profile)

    def _save_assistant_message(content: str, agent: str, media: str | None = None) -> None:
        memory.add_message(session_id, "assistant", content, agent=agent,
                            dek=dek, key_generation=key_generation, user_id=user_id, media=media)

    if agent_name == "image":
        try:
            prompt, (width, height) = prompt_writer.image_prompt(ollama, gen_options.writer_model(), message)
            img_bytes = image_agent.generate(prompt, width=width, height=height, model_id=image_model)
        except Exception as exc:
            resp = ChatResponse(agent_used="image", response=generation_error_message("generando la imagen", exc),
                                 verifier_gated=False, session_id=session_id)
            _save_assistant_message(resp.response, "image")
            return resp
        resp = with_bytes(
            ChatResponse(agent_used="image", response="Imagen generada.", verifier_gated=False,
                         session_id=session_id),
            img_bytes, ".png", auth_session,
        )
        _save_assistant_message(resp.response, "image", media=resp.file_path)
        return resp

    if agent_name == "video":
        redo = video_replies.film_redo(session_id, message)
        if redo or (video_replies.FILM.search(message) and not video_replies.video_again(session_id, message)):
            return video_replies.film_reply(message, session_id, auth_session, video_model=video_model, redo=redo)
        video_started = time.time()
        try:
            again = video_replies.video_again(session_id, message)
            if again:
                last = video_replies.last_videos[session_id]
                prompt, seconds, (width, height), seed = last["prompt"], again, last["size"], last["seed"]
                video_model = video_model or last["model"]
            else:
                prompt, asked, (width, height) = prompt_writer.video_plan(ollama, gen_options.writer_model(), message)
                seconds, seed = asked or video_pipeline.VIDEO_DEFAULT_SECONDS, video_agent_module.new_seed()
            vid_bytes = video_agent.generate(prompt, width=width, height=height, seconds=seconds, seed=seed,
                                             model_id=video_model)
            video_replies.last_videos[session_id] = {"prompt": prompt, "size": (width, height), "seed": seed,
                                        "model": video_model}
        except Exception as exc:
            resp = ChatResponse(agent_used="video", response=generation_error_message("generando el video", exc),
                                 verifier_gated=False, session_id=session_id)
            _save_assistant_message(resp.response, "video")
            return resp
        resp = with_bytes(
            ChatResponse(agent_used="video", verifier_gated=False, session_id=session_id,
                         response=f"Video generado ({seconds:g} s). Lo que ha entendido el generador: {prompt}\n\n"
                                  "Si te gusta, pide \"hazlo de 10 segundos\" y lo repito igual pero mas largo."),
            vid_bytes, ".mp4", auth_session,
        )
        _save_assistant_message(resp.response, "video")
        video_replies.notify_if_long(auth_session, video_started, f"Tu vídeo de {seconds:g} s está listo.")
        return resp

    if agent_name == "opencode":
        task_id, choice = None, None
        if auth_session.get("role") == "guest":
            text = "El agente solo esta disponible para usuarios registrados, no en modo invitado."
        elif not access.can_use_pc(auth_session):
            text = "Tu cuenta no tiene permiso para usar el agente (toca archivos del ordenador). Pideselo al administrador."
        else:
            choice = routes_agent.assess_for_fast_agent(message)
            if choice:
                text = ("Esta tarea parece compleja para el agente rapido: " + (choice["reason"] or "tiene varios pasos.")
                        + " Te recomiendo el modelo potente: se equivoca menos, pero tarda minutos en vez de segundos.")
            else:
                text, task_id = opencode_client.delegate(CONFIG["opencode"]["base_url"], message,
                                                         CONFIG["opencode"]["agent"])
                task_owners.record(task_id, auth_session.get("user_id"))
                agent_watch.start_agent_watch(task_id)
        resp = ChatResponse(agent_used="opencode", response=text, verifier_gated=False,
                            session_id=session_id, agent_task_id=task_id,
                            agent_choice=choice)
        _save_assistant_message(resp.response, "opencode")
        return resp

    if agent_name not in AGENTS:
        resp = ChatResponse(
            agent_used=agent_name,
            response=f"El agente '{agent_name}' todavia no esta conectado al orquestador.",
            verifier_gated=False,
            session_id=session_id,
        )
        _save_assistant_message(resp.response, agent_name)
        return resp

    agent = AGENTS[agent_name]
    raw_history = memory.get_history(session_id, limit=12, dek=dek, key_generation=key_generation)[:-1]
    history = [{"role": h["role"], "content": h["content"]} for h in raw_history]

    if agent_name in ("text", "code"):
        gpu_memory.ensure_active_model(override_model or agent.model)
        pc_access = access.can_use_pc(auth_session)
        tool_executor = partial(_execute_tool, session_id=session_id, user_id=user_id,
                                 dek=dek, key_generation=key_generation, pc_access=pc_access)
        docs_context, docs_evidence = routes_sessions.attached_docs(session_id, message, auth_session)
        raw_answer, evidence = agent.respond_with_tools(
            routes_sessions.with_docs(message, docs_context), history, _tools_for(agent_name, pc_access, not user_id), tool_executor,
            model=override_model, think=think)
        evidence = docs_evidence + (evidence or []) or None
        raw_answer = _fix_language(raw_answer, message, override_model or agent.model)
    else:
        evidence = None
        raw_answer = agent.respond(message, history=history, context_chunks=None)

    if CONFIG["verifier"]["enabled"] and verify and agent_name in ("text", "code"):
        result = verifier.check(message, raw_answer, is_factual=is_factual, evidence=evidence)
        resp = ChatResponse(
            agent_used=agent_name,
            response=result.answer,
            verifier_gated=result.gated,
            verifier_reason=result.reason,
            session_id=session_id,
            sources=result.sources,
        )
    else:
        resp = ChatResponse(agent_used=agent_name, response=raw_answer, verifier_gated=False, session_id=session_id)
    resp.agent_task_id = _delegated_task_id(evidence)

    _save_assistant_message(resp.response, agent_name)
    if agent_name in ("text", "code") and not resp.verifier_gated:
        _index_in_background(session_id, message, resp.response, user_id, dek, key_generation)
    return resp


def _run_vision_chat(message: str, image_base64: str, session_id: str | None, auth_session: dict) -> ChatResponse:
    session_id = routes_sessions.own_session_id(session_id, auth_session)
    dek, key_generation, user_id = auth_session["dek"], auth_session["key_generation"], auth_session["user_id"]
    remember(session_id, auth_session, "user", message or "[imagen adjunta]")
    gpu_memory.ensure_active_model(vision_agent.model)
    start = time.perf_counter()
    try:
        full_text = "".join(vision_agent.respond_with_image_stream(message, image_base64))
    except Exception as exc:
        metrics.log_since("vision", start, False, error=str(exc))
        full_text = f"Fallo analizando la imagen: {exc}"
        memory.add_message(session_id, "assistant", full_text, agent="vision",
                            dek=dek, key_generation=key_generation, user_id=user_id)
        return ChatResponse(agent_used="vision", response=full_text, verifier_gated=False, session_id=session_id)
    memory.add_message(session_id, "assistant", full_text, agent="vision",
                        dek=dek, key_generation=key_generation, user_id=user_id)
    metrics.log_since("vision", start, False)
    return ChatResponse(agent_used="vision", response=full_text, verifier_gated=False, session_id=session_id)


def _stream_vision_chat(message: str, image_base64: str, session_id: str | None, auth_session: dict):
    session_id = routes_sessions.own_session_id(session_id, auth_session)
    dek, key_generation, user_id = auth_session["dek"], auth_session["key_generation"], auth_session["user_id"]
    remember(session_id, auth_session, "user", message or "[imagen adjunta]")
    yield json.dumps({"type": "start", "agent_used": "vision", "session_id": session_id}) + "\n"
    gpu_memory.ensure_active_model(vision_agent.model)
    start = time.perf_counter()
    full_text = ""
    try:
        for chunk in vision_agent.respond_with_image_stream(message, image_base64):
            full_text += chunk
            yield json.dumps({"type": "chunk", "text": chunk}) + "\n"
    except Exception as exc:
        metrics.log_since("vision", start, False, error=str(exc))
        yield json.dumps({"type": "done", "response": f"Fallo analizando la imagen: {exc}",
                           "verifier_gated": False, "session_id": session_id}) + "\n"
        return
    memory.add_message(session_id, "assistant", full_text, agent="vision",
                        dek=dek, key_generation=key_generation, user_id=user_id)
    metrics.log_since("vision", start, False)
    yield json.dumps({
        "type": "done", "response": full_text, "verifier_gated": False, "verifier_reason": None,
        "sources": None, "session_id": session_id, "corrected": False,
    }) + "\n"


def _run_chat(message: str, agent_override: str | None, session_id: str | None, auth_session: dict,
              model_profile: str | None = None, verify: bool = True,
              image_model: str | None = None, video_model: str | None = None) -> ChatResponse:
    session_id = routes_sessions.own_session_id(session_id, auth_session)
    remember(session_id, auth_session, "user", message)
    queued = night_queue.queue_videos(message, session_id, auth_session) if agent_override == "video" else None
    if queued:
        return assistant_reply(queued, "video", session_id, auth_session)
    if agent_override in (None, "video") and video_replies.video_again(session_id, message):
        agent_override = "video"
    agent_name, is_factual = _resolve_agent(message, agent_override)
    start = time.perf_counter()
    resp = _generate_response(message, agent_name, is_factual, session_id, auth_session, model_profile,
                               verify, image_model, video_model)
    metrics.log_since(resp.agent_used, start, resp.verifier_gated)
    return resp


night_queue.configure(run_chat=_run_chat)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    if req.image_base64:
        return _run_vision_chat(req.message, req.image_base64, req.session_id, request.state.session)
    return _run_chat(req.message, req.agent, req.session_id, request.state.session, req.model_profile, req.verify,
                      req.image_model, req.video_model)


def _stream_chat(message: str, agent_override: str | None, session_id: str | None, auth_session: dict,
                  model_profile: str | None = None, verify: bool = True, image_model: str | None = None,
                  video_model: str | None = None):
    dek = auth_session["dek"]
    key_generation = auth_session["key_generation"]
    user_id = auth_session["user_id"]
    override_model = model_choice.profile_model(model_profile)
    think = model_choice.profile_think(model_profile)

    session_id = routes_sessions.own_session_id(session_id, auth_session)
    memory.add_message(session_id, "user", message, dek=dek, key_generation=key_generation, user_id=user_id)

    queued = night_queue.queue_videos(message, session_id, auth_session) if agent_override == "video" else None
    if queued:
        yield from _stream_with_progress(lambda: assistant_reply(queued, "video", session_id, auth_session),
                                         "video", session_id, message)
        return
    if agent_override in (None, "video") and video_replies.video_again(session_id, message):
        agent_override = "video"

    loaded = set(ollama.running_models())
    announced = set()
    if agent_override is None and gpu_memory.LIGHT_MODEL not in loaded:
        announced.add(gpu_memory.LIGHT_MODEL)
        yield _loading_event(gpu_memory.LIGHT_MODEL)

    agent_name, is_factual = _resolve_agent(message, agent_override)
    yield json.dumps({"type": "start", "agent_used": agent_name, "session_id": session_id}) + "\n"
    stream_start = time.perf_counter()

    if agent_name in AGENTS:
        target_model = override_model or AGENTS[agent_name].model
        if target_model not in loaded and target_model not in announced:
            yield _loading_event(target_model)

    if agent_name not in AGENTS:
        def work():
            resp = _generate_response(message, agent_name, is_factual, session_id, auth_session, model_profile,
                                       verify, image_model, video_model)
            metrics.log_since(resp.agent_used, stream_start, resp.verifier_gated)
            return resp
        yield from _stream_with_progress(work, agent_name, session_id, message, announce=False)
        return

    agent = AGENTS[agent_name]
    raw_history = memory.get_history(session_id, limit=12, dek=dek, key_generation=key_generation)[:-1]
    history = [{"role": h["role"], "content": h["content"]} for h in raw_history]

    docs_context, evidence = routes_sessions.attached_docs(session_id, message, auth_session)
    full_text = ""
    try:
        if agent_name in ("text", "code"):
            gpu_memory.ensure_active_model(override_model or agent.model)
            pc_access = access.can_use_pc(auth_session)
            tool_executor = partial(_execute_tool, session_id=session_id, user_id=user_id,
                                     dek=dek, key_generation=key_generation, pc_access=pc_access)
            chunks = agent.respond_with_tools_stream(
                routes_sessions.with_docs(message, docs_context), history, _tools_for(agent_name, pc_access, not user_id), tool_executor, evidence,
                model=override_model, think=think)
        else:
            chunks = agent.respond_stream(message, history=history, context_chunks=None)
        for chunk in chunks:
            full_text += chunk
            yield json.dumps({"type": "chunk", "text": chunk}) + "\n"
    except Exception as exc:
        log.exception("Fallo generando la respuesta del chat")
        metrics.log_since(agent_name, stream_start, False, error=str(exc))
        yield json.dumps({"type": "done", "response": f"Fallo generando la respuesta: {exc}",
                           "verifier_gated": False, "session_id": session_id}) + "\n"
        return

    final_response = full_text
    if agent_name in ("text", "code"):
        final_response = _fix_language(full_text, message, override_model or agent.model)
    verifier_gated = False
    verifier_reason = None
    sources = None

    if CONFIG["verifier"]["enabled"] and verify and agent_name in ("text", "code"):
        result = verifier.check(message, final_response, is_factual=is_factual, evidence=evidence)
        final_response = result.answer
        verifier_gated = result.gated
        verifier_reason = result.reason
        sources = result.sources

    memory.add_message(session_id, "assistant", final_response, agent=agent_name,
                        dek=dek, key_generation=key_generation, user_id=user_id)
    if agent_name in ("text", "code") and not verifier_gated:
        _index_in_background(session_id, message, final_response, user_id, dek, key_generation)
    metrics.log_since(agent_name, stream_start, verifier_gated)
    yield json.dumps({
        "type": "done",
        "response": final_response,
        "verifier_gated": verifier_gated,
        "verifier_reason": verifier_reason,
        "sources": sources,
        "session_id": session_id,
        "corrected": verifier_gated or (final_response != full_text),
        "agent_task_id": _delegated_task_id(evidence),
    }) + "\n"


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request):
    if req.image_base64:
        return StreamingResponse(
            _stream_vision_chat(req.message, req.image_base64, req.session_id, request.state.session),
            media_type="application/x-ndjson",
        )
    return StreamingResponse(
        _stream_chat(req.message, req.agent, req.session_id, request.state.session, req.model_profile, req.verify,
                     req.image_model, req.video_model),
        media_type="application/x-ndjson",
    )


app.include_router(routes_sessions.router)


@app.post("/voice_chat")
def voice_chat(request: Request, audio: UploadFile = File(...), session_id: str | None = Form(None)):
    try:
        audio_bytes = read_upload(audio)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=413)
    try:
        with media_store.plain_copy(audio_bytes, ".wav") as audio_path:
            transcript = voice_agent.transcribe(str(audio_path))
    except RuntimeError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503)
    if not transcript:
        return {"transcript": "", "agent_used": None, "response": "No se entendio ningun audio.",
                "verifier_gated": False, "file_url": None, "session_id": session_id}

    result = _run_chat(transcript, None, session_id, request.state.session)

    speech_path = media_store.new_tmp_path(".wav")
    try:
        voice_agent.speak(result.response, str(speech_path))
        speech_name = media_store.save_file(speech_path, request.state.session["dek"])
    except RuntimeError:
        speech_path.unlink(missing_ok=True)
        speech_name = None

    return {
        "transcript": transcript,
        "agent_used": result.agent_used,
        "response": result.response,
        "verifier_gated": result.verifier_gated,
        "verifier_reason": result.verifier_reason,
        "file_url": media_store.url_for(speech_name) if speech_name else None,
        "session_id": result.session_id,
    }


@app.post("/speak")
def speak(request: Request, text: str = Form(...)):
    out_path = media_store.new_tmp_path(".wav")
    try:
        voice_agent.speak(text[:MAX_SPEAK_CHARS], str(out_path))
    except RuntimeError as exc:
        out_path.unlink(missing_ok=True)
        return JSONResponse({"detail": str(exc)}, status_code=503)
    return {"file_url": media_store.url_for(media_store.save_file(out_path, request.state.session["dek"]))}


STREAM_HEARTBEAT_SECONDS = 10


MEDIA_NOTICE_SECONDS = 60
_MEDIA_TITLES = {"image": "🖼 Imagen lista", "video": "🎬 Vídeo listo"}


def _notice_media(agent: str, started: float, resp, request_text: str) -> None:
    owner = comfyui_client.current_owner.get()
    if agent not in _MEDIA_TITLES or not owner or owner.startswith("invitado:") \
            or time.monotonic() - started < MEDIA_NOTICE_SECONDS:
        return
    what = " ".join(request_text.split())[:90] or "Tu petición"
    if resp is not None and getattr(resp, "file_url", None):
        push.notify(owner, _MEDIA_TITLES[agent], what, tag="chati-media")
    else:
        detail = getattr(resp, "response", "") if resp is not None else "Ha fallado; míralo en Chati."
        push.notify(owner, "💬 Chati te ha contestado", (detail or what)[:200], tag="chati-media")


_DOING = {"image": "generando la imagen", "video": "generando el vídeo"}


def _stream_with_progress(work, agent_used: str, session_id: str, request_text: str = "", announce: bool = True):
    events: queue.Queue = queue.Queue()
    result: dict = {}
    started = time.monotonic()

    def run():
        gen_options.progress.set(events.put)
        comfyui_client.current_conversation.set(session_id)
        try:
            result["resp"] = work()
        except Exception as exc:
            log.exception("Fallo %s", _DOING.get(agent_used, "generando la respuesta"))
            result["error"] = exc
        _notice_media(agent_used, started, result.get("resp"), request_text)

    if announce:
        yield json.dumps({"type": "start", "agent_used": agent_used, "session_id": session_id}) + "\n"
    thread = threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True)
    thread.start()
    last_sent = time.monotonic()
    last_step = None
    while thread.is_alive() or not events.empty():
        try:
            yield json.dumps({"type": "status", "text": events.get(timeout=1)}) + "\n"
            last_sent = time.monotonic()
        except queue.Empty:
            step = comfyui_client.conversation_progress(session_id)
            if step and step["texto"] != last_step:
                last_step = step["texto"]
                yield json.dumps({"type": "status", "text": step["texto"] + "…"}) + "\n"
                last_sent = time.monotonic()
                continue
            if time.monotonic() - last_sent >= STREAM_HEARTBEAT_SECONDS:
                yield json.dumps({"type": "ping"}) + "\n"
                last_sent = time.monotonic()
    thread.join()
    if "error" in result:
        yield json.dumps({"type": "done", "response": generation_error_message(
                              _DOING.get(agent_used, "generando la respuesta"), result["error"]),
                          "verifier_gated": False, "session_id": session_id}) + "\n"
        return
    yield json.dumps({"type": "done", **result["resp"].model_dump()}) + "\n"



