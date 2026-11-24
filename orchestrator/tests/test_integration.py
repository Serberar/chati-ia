import base64
import io
import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient

import main
from accounts import users as users_module
from agents.comfyui_client import GenerationCancelled
from api import routes_agent, routes_sessions
from api.replies import generation_error_message
from chat import night_queue, plans, video_replies
from coding import agent_watch, checkpoints
from infra.core import text_agent
from main import CONFIG, app, knowledge_base
from media import film
from models import gpu_memory, model_registry, model_updates

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_TEST_USERNAME = f"_test_integration_{uuid.uuid4().hex[:8]}"
_TEST_PASSWORD = "contraseña-de-test-de-integracion-123"


def _create_and_login_test_admin() -> str:
    anon = TestClient(app)
    reg_key = users_module.get_or_create_registration_key()
    anon.post("/auth/register", json={
        "username": _TEST_USERNAME, "password": _TEST_PASSWORD, "registration_key": reg_key,
    })
    with closing(sqlite3.connect(users_module.DB_PATH)) as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE username = ?", (_TEST_USERNAME,))
        conn.commit()
    resp = anon.post("/auth/login", json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD})
    return resp.json()["token"]


_test_token = _create_and_login_test_admin()


@pytest.fixture(autouse=True)
def _agent_tasks_skip_difficulty_assessment(request):
    if request.node.get_closest_marker("assess"):
        yield
        return
    with patch.object(routes_agent, "assess_for_fast_agent", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _comfyui_queue_is_idle():
    # Sin esto, user_jobs pregunta al ComfyUI real del PC: si esta generando, free_comfyui no libera y fallan tests.
    with patch.object(main.comfyui_client, "user_jobs", return_value=[]):
        yield


client = TestClient(app, headers={"X-Session-Token": _test_token})


def teardown_module(module):
    users_module.delete_user(_TEST_USERNAME)


@pytest.mark.live
def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.live
def test_model_roles_describes_each_configured_model():
    resp = client.get("/models/roles")
    assert resp.status_code == 200
    roles = resp.json()

    security_model = CONFIG["agents"]["text"]["profiles"]["seguridad"]["model"]
    assert security_model in roles
    security_label = CONFIG["agents"]["text"]["profiles"]["seguridad"]["label"]
    assert security_label.lower() in roles[security_model].lower()

    assert "nomic-embed-text:latest" in roles
    assert "embeddings" in roles["nomic-embed-text:latest"].lower()

    router_model = CONFIG["router"]["model"]
    assert "router" in roles[router_model].lower()
    assert "verificador" in roles[router_model].lower()


@pytest.mark.live
def test_verify_false_skips_the_anti_hallucination_check():
    with patch.object(main.verifier, "check") as mock_check:
        resp = client.post("/chat", json={
            "message": "hola, responde solo con un saludo corto",
            "model_profile": "rapido",
            "verify": False,
        })
    assert resp.status_code == 200
    mock_check.assert_not_called()


def test_generation_error_message_distinguishes_cancellation():
    cancelled_msg = generation_error_message("generando la imagen", GenerationCancelled("prompt_id=x"))
    assert "cancel" in cancelled_msg.lower()
    assert "prompt_id" not in cancelled_msg

    other_msg = generation_error_message("generando la imagen", RuntimeError("la GPU exploto"))
    assert "cancel" not in other_msg.lower()
    assert "la GPU exploto" in other_msg


def test_get_plan_endpoint_returns_empty_for_unknown_session():
    resp = client.get("/plan/sesion-que-no-existe-en-el-test")
    assert resp.status_code == 200
    assert resp.json() == {"pasos": []}


def test_get_plan_endpoint_returns_stored_plan_only_to_its_owner():
    owner_id = users_module.get_user(_TEST_USERNAME)["id"]
    sid = main.memory.new_session_id()
    main.memory.add_message(sid, "user", "hola", user_id=owner_id)
    plans.set_plan(sid, [{"texto": "paso 1", "estado": "hecho"}])
    resp = client.get(f"/plan/{sid}")
    assert resp.status_code == 200
    assert resp.json() == {"pasos": [{"texto": "paso 1", "estado": "hecho"}]}
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.get(f"/plan/{sid}").json() == {"pasos": []}


def test_chat_requires_session():
    unauthenticated_client = TestClient(app)
    resp = unauthenticated_client.post("/chat", json={"message": "hola"})
    assert resp.status_code == 401

    wrong_token_client = TestClient(app, headers={"X-Session-Token": "token-que-no-existe"})
    resp2 = wrong_token_client.post("/chat", json={"message": "hola"})
    assert resp2.status_code == 401


@pytest.mark.live
def test_root_page_is_public():
    unauthenticated_client = TestClient(app)
    resp = unauthenticated_client.get("/")
    assert resp.status_code == 200


def test_static_files_are_revalidated_so_an_update_never_mixes_old_js():
    resp = TestClient(app).get("/static/js/app/base.js")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.live
def test_chat_text_basic():
    resp = client.post("/chat", json={"message": "Responde solo con la palabra: hola"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_used"] == "text"
    assert data["response"]
    client.delete(f"/sessions/{data['session_id']}")


@pytest.mark.live
def test_chat_stream_emits_chunks_then_done():
    resp = client.post("/chat/stream", json={"message": "Cuenta hasta 3, una palabra por numero"})
    assert resp.status_code == 200
    lines = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]

    assert lines[0]["type"] == "start"
    chunk_lines = [l for l in lines if l["type"] == "chunk"]
    done_lines = [l for l in lines if l["type"] == "done"]
    assert len(chunk_lines) > 0, "deberian llegar trozos de texto, no solo el evento final"
    assert len(done_lines) == 1

    reconstructed = "".join(c["text"] for c in chunk_lines)
    done = done_lines[0]
    assert done["response"]
    if not done["corrected"]:
        assert done["response"] == reconstructed

    client.delete(f"/sessions/{done['session_id']}")


@pytest.mark.live
def test_router_detects_code_request():
    resp = client.post("/chat", json={
        "message": "Escribe una funcion en Python que sume dos numeros"
    })
    data = resp.json()
    assert data["agent_used"] == "code"
    client.delete(f"/sessions/{data['session_id']}")


@pytest.mark.live
def test_conversation_memory_continuity():
    r1 = client.post("/chat", json={"message": "Mi ciudad favorita es Valencia. Recuerdalo."})
    sid = r1.json()["session_id"]

    r2 = client.post("/chat", json={"message": "Cual es mi ciudad favorita?", "session_id": sid})
    assert "valencia" in r2.json()["response"].lower()

    client.delete(f"/sessions/{sid}")


@pytest.mark.live
def test_long_term_memory_recalls_across_unrelated_sessions():
    r1 = client.post("/chat", json={
        "message": "Mi gato se llama Pixel y tiene el pelo naranja. Recuerdalo."
    })
    sid1 = r1.json()["session_id"]
    time.sleep(5)

    try:
        r2 = client.post("/chat", json={"message": "Como se llama mi gato?"})
        sid2 = r2.json()["session_id"]
        assert sid2 != sid1, "deberia ser una sesion nueva, no la misma"
        assert "pixel" in r2.json()["response"].lower()
        assert r2.json()["sources"] and f"conversacion:{sid1}" in r2.json()["sources"]
        client.delete(f"/sessions/{sid2}")
    finally:
        client.delete(f"/sessions/{sid1}")


@pytest.mark.live
def test_verifier_gates_fabricated_entity():
    import re
    safe_count = 0
    for _ in range(3):
        resp = client.post("/chat", json={
            "message": "En que fecha exacta se fundo la empresa Kortavelt Industries "
                       "y quien fue su primer director financiero?"
        })
        data = resp.json()
        assert data["agent_used"] == "text", "una pregunta no va al agente"
        admits = re.search(r"no (tengo|dispongo|puedo|conozco|encuentro|encontr|hay)", data["response"].lower())
        if data["verifier_gated"] or admits:
            safe_count += 1
        client.delete(f"/sessions/{data['session_id']}")

    assert safe_count >= 2, f"Solo {safe_count}/3 respuestas sin inventar, deberian ser al menos 2/3"


@pytest.mark.live
def test_rag_answers_from_uploaded_document_with_source():
    doc_content = (
        b"El proyecto de prueba Nebula fue creado en 2021 por Clara Fonseca. "
        b"Tiene un presupuesto de 12000 euros."
    )
    client.post("/knowledge", files={"file": ("test_nebula.txt", doc_content, "text/plain")})

    try:
        resp = client.post("/chat", json={"message": "Quien creo el proyecto Nebula?"})
        data = resp.json()
        assert "fonseca" in data["response"].lower()
        assert data["sources"] and "test_nebula.txt" in data["sources"]
        client.delete(f"/sessions/{data['session_id']}")
    finally:
        knowledge_base.delete_document("test_nebula.txt")


@pytest.mark.slow
def test_image_generation_via_chat():
    resp = client.post("/chat", json={"message": "Genera una imagen de una montana al atardecer"})
    data = resp.json()
    assert data["agent_used"] == "image"
    assert data["file_url"] and data["file_url"].endswith(".png")
    client.delete(f"/sessions/{data['session_id']}")


@pytest.mark.slow
def test_upscale_quadruples_resolution():
    from PIL import Image

    image_bytes = (FIXTURES_DIR / "sample_image.png").read_bytes()
    resp = client.post("/image/upscale", files={"image": ("ref.png", image_bytes, "image/png")})
    data = resp.json()
    assert data["agent_used"] == "image_upscale"
    assert data["file_url"]

    with Image.open(FIXTURES_DIR / "sample_image.png") as orig:
        orig_size = orig.size
    got = client.get(data["file_url"])
    assert got.status_code == 200
    with Image.open(__import__("io").BytesIO(got.content)) as upscaled:
        assert upscaled.size == (orig_size[0] * 4, orig_size[1] * 4)


@pytest.mark.skip(reason=(
    "No es automatizable de forma fiable con este hardware: /interrupt de ComfyUI "
    "solo actua entre pasos del sampler, nunca durante la carga del modelo, y esta "
    "maquina alterna entre modelo 'caliente' (genera en segundos, gana la carrera "
    "antes de poder cancelar) y 'frio' (carga 40-300s+, ventana en la que cancelar "
    "no sirve de nada). Se probaron esperas de 0.5s, 3s y umbrales de 180-300s: "
    "ninguna gana siempre, porque el estado caliente/frio no es determinista desde "
    "el test. El mecanismo de cancelacion SI esta verificado, por otras dos vias "
    "deterministas: tests/test_comfyui_client.py (mocks, sin timing real) y una "
    "verificacion manual documentada en la sesion (script aislado + servidor real, "
    "cancelacion confirmada en 5-73s). Dejar este test activo solo añadiria fallos "
    "intermitentes sin señal real de regresion."
))
@pytest.mark.slow
def test_cancel_stops_image_generation_promptly():
    import requests as real_requests

    base = "http://127.0.0.1:8899"
    login_resp = real_requests.post(f"{base}/auth/login", json={
        "username": _TEST_USERNAME, "password": _TEST_PASSWORD,
    }, timeout=15)
    headers = {"X-Session-Token": login_resp.json()["token"]}
    result = {}

    def run_generation():
        resp = real_requests.post(f"{base}/chat", json={
            "message": "Genera una imagen extremadamente detallada de una ciudad futurista, 4k, hiperrealista"
        }, headers=headers, timeout=500)
        result["data"] = resp.json()

    thread = threading.Thread(target=run_generation)
    thread.start()
    time.sleep(0.5)

    cancel_resp = real_requests.post(f"{base}/cancel", headers=headers, timeout=15)
    assert cancel_resp.status_code == 200

    thread.join(timeout=300)
    assert not thread.is_alive(), "la generacion no cancelo ni siquiera dando margen para carga de modelo en frio"
    assert "data" in result, "el hilo no dejo resultado - revisa si el orquestador esta corriendo en :8899"

    response_text = result["data"]["response"].lower()
    if result["data"].get("session_id"):
        real_requests.delete(f"{base}/sessions/{result['data']['session_id']}", headers=headers)

    if "cancel" not in response_text:
        pytest.skip(f"La generacion termino antes de que llegara la cancelacion (respuesta: {response_text!r}). "
                     "Carrera inherente, no un fallo - ver docstring.")


def test_delete_text_model_refuses_for_non_admin():
    uname = f"_test_no_admin_{uuid.uuid4().hex[:8]}"
    pw = "contraseña-no-admin-123"
    anon = TestClient(app)
    reg_key = users_module.get_or_create_registration_key()
    r = anon.post("/auth/register", json={"username": uname, "password": pw, "registration_key": reg_key})
    anon_token = r.json()["token"]
    try:
        resp = TestClient(app, headers={"X-Session-Token": anon_token}).delete("/models/text/qwen2.5:14b")
        assert resp.status_code == 403
    finally:
        users_module.delete_user(uname)


def test_delete_text_model_refuses_unknown_model():
    with patch.object(model_updates, "check_updates", return_value=[{"model": "qwen2.5:7b"}]):
        resp = client.delete("/models/text/no-instalado-de-mentira:latest")
    assert resp.status_code == 400


def test_delete_text_model_refuses_a_model_in_use():
    with patch.object(model_updates, "check_updates", return_value=[{"model": "qwen2.5:7b"}]), \
         patch("api.routes_models.get_model_roles", return_value={"qwen2.5:7b": "Router"}):
        resp = client.delete("/models/text/qwen2.5:7b")
    assert resp.status_code == 400
    assert "en uso" in resp.json()["detail"]


def test_delete_text_model_calls_ollama_for_an_unused_installed_model():
    with patch.object(model_updates, "check_updates", return_value=[{"model": "qwen2.5:14b"}]), \
         patch("api.routes_models.get_model_roles", return_value={}), \
         patch.object(main.requests, "delete") as mock_delete:
        mock_delete.return_value.ok = True
        resp = client.delete("/models/text/qwen2.5:14b")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_delete.assert_called_once()
    assert mock_delete.call_args.kwargs["json"] == {"model": "qwen2.5:14b"}


def test_delete_text_model_reports_ollama_failure():
    with patch.object(model_updates, "check_updates", return_value=[{"model": "qwen2.5:14b"}]), \
         patch("api.routes_models.get_model_roles", return_value={}), \
         patch.object(main.requests, "delete") as mock_delete:
        mock_delete.return_value.ok = False
        mock_delete.return_value.text = "boom"
        resp = client.delete("/models/text/qwen2.5:14b")
    assert resp.status_code == 502


def test_delete_image_model_refuses_for_non_admin(tmp_path, monkeypatch):
    img = tmp_path / "img"
    (img / "checkpoints" / "sdxl").mkdir(parents=True)
    (img / "checkpoints" / "sdxl" / "modelo.safetensors").write_bytes(b"x")
    monkeypatch.setattr(model_registry, "IMG_DIR", img)

    uname = f"_test_no_admin_img_{uuid.uuid4().hex[:8]}"
    pw = "contraseña-no-admin-456"
    anon = TestClient(app)
    reg_key = users_module.get_or_create_registration_key()
    r = anon.post("/auth/register", json={"username": uname, "password": pw, "registration_key": reg_key})
    anon_token = r.json()["token"]
    try:
        resp = TestClient(app, headers={"X-Session-Token": anon_token}).delete("/models/image/sdxl:modelo")
        assert resp.status_code == 403
    finally:
        users_module.delete_user(uname)
    assert (img / "checkpoints" / "sdxl" / "modelo.safetensors").exists()


def test_delete_image_model_refuses_unknown_id(tmp_path, monkeypatch):
    img = tmp_path / "img"
    (img / "checkpoints" / "sdxl").mkdir(parents=True)
    monkeypatch.setattr(model_registry, "IMG_DIR", img)

    resp = client.delete("/models/image/sdxl:no-instalado")
    assert resp.status_code == 400


def test_delete_image_model_removes_the_file(tmp_path, monkeypatch):
    img = tmp_path / "img"
    (img / "checkpoints" / "sdxl").mkdir(parents=True)
    model_file = img / "checkpoints" / "sdxl" / "modelo.safetensors"
    model_file.write_bytes(b"x")
    monkeypatch.setattr(model_registry, "IMG_DIR", img)

    resp = client.delete("/models/image/sdxl:modelo")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert not model_file.exists()


def test_delete_video_model_removes_the_file(tmp_path, monkeypatch):
    vid = tmp_path / "vid"
    (vid / "checkpoints" / "ltxv").mkdir(parents=True)
    model_file = vid / "checkpoints" / "ltxv" / "modelo.safetensors"
    model_file.write_bytes(b"x")
    monkeypatch.setattr(model_registry, "VID_DIR", vid)

    resp = client.delete("/models/video/ltxv:modelo")

    assert resp.status_code == 200
    assert not model_file.exists()


def test_opencode_mode_delegates_the_message_as_is():
    with patch.object(main.opencode_client, "delegate", return_value=("Tarea enviada.", "ses_x")) as mock_delegate:
        resp = client.post("/chat", json={"message": "arregla el bug de login", "agent": "opencode"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_used"] == "opencode"
    assert data["response"] == "Tarea enviada."
    mock_delegate.assert_called_once()
    assert mock_delegate.call_args.args[1] == "arregla el bug de login"


def test_chat_stream_final_event_for_image_video_opencode_has_a_type_field():
    with patch.object(main.opencode_client, "delegate", return_value=("Tarea enviada.", "ses_x")), client.stream("POST", "/chat/stream", json={"message": "hola", "agent": "opencode"}) as resp:
        lines = [json.loads(line) for line in resp.iter_lines() if line.strip()]
    assert lines[0]["type"] == "start"
    assert lines[-1]["type"] == "done"
    assert lines[-1]["response"] == "Tarea enviada."


def test_agent_routes_blocked_in_guest_mode():
    guest_token = client.post("/auth/guest").json()["token"]
    guest_client = TestClient(app, headers={"X-Session-Token": guest_token})

    assert guest_client.post("/agent/tasks", json={"task": "hola"}).status_code == 403
    assert guest_client.get("/agent/tasks").status_code == 403


def test_agent_start_task_returns_session_id():
    with patch.object(main.opencode_client, "start_task", return_value="ses_abc") as mock_start:
        resp = client.post("/agent/tasks", json={"task": "  crea un archivo  "})
    assert resp.status_code == 200
    assert resp.json() == {"session_id": "ses_abc"}
    assert mock_start.call_args.args[1] == "crea un archivo"


def test_agent_reports_502_when_opencode_is_down():
    with patch.object(main.opencode_client, "start_task", side_effect=requests.ConnectionError("x")):
        resp = client.post("/agent/tasks", json={"task": "hola"})
    assert resp.status_code == 502
    assert "agente de codigo" in resp.json()["detail"]


def test_agent_permission_reply_rejects_unknown_values():
    resp = client.post("/agent/permissions/per_1", json={"reply": "si"})
    assert resp.status_code == 400


def test_allow_whole_folder_approves_the_next_edits_there_only(tmp_path):
    def perm(pid, path):
        return {"id": pid, "permission": "edit", "patterns": [path.name], "filepath": str(path), "diff": ""}
    view = {"directory": str(tmp_path), "permissions": [perm("per_9", tmp_path / "a.py")], "steps": [], "task": "x"}
    with patch.object(routes_agent, "_owns_request", return_value=True),          patch.object(agent_watch, "start_agent_watch"),          patch.object(main.opencode_client, "request_session", return_value="ses_dir"),          patch.object(main.opencode_client, "get_task_view", return_value=view),          patch.object(main.opencode_client, "reply_permission") as reply:
        assert client.post("/agent/permissions/per_9", json={"reply": "carpeta"}).status_code == 200
        assert reply.call_args.args[1:] == ("per_9", "once")
        reply.reset_mock()
        later = {**view, "permissions": [perm("per_10", tmp_path / "sub" / "b.py"),
                                         perm("per_11", tmp_path.parent / "fuera.py")]}
        agent_watch._approve_allowed_folders("http://x", "ses_dir", later)
    assert [c.args[1] for c in reply.call_args_list] == ["per_10"]
    agent_watch.agent_allowed.pop("ses_dir", None)


def test_vision_chat_ignores_the_text_model_profile():
    with patch.object(main.vision_agent, "respond_with_image_stream",
                       return_value=iter(["describe algo"])) as mock_respond:
        resp = client.post("/chat", json={
            "message": "describeme esta imagen",
            "image_base64": "aWdub3JhZG8=",
            "model_profile": "rapido",
        })
    assert resp.status_code == 200
    assert resp.json()["agent_used"] == "vision"
    mock_respond.assert_called_once()
    assert "model" not in mock_respond.call_args.kwargs
    assert len(mock_respond.call_args.args) == 2


def test_vision_chat_stream_ignores_the_text_model_profile():
    with patch.object(main.vision_agent, "respond_with_image_stream",
                       return_value=iter(["describe algo"])) as mock_respond, \
                       client.stream("POST", "/chat/stream", json={
        "message": "describeme esta imagen",
        "image_base64": "aWdub3JhZG8=",
        "model_profile": "seguridad",
    }) as resp:
        lines = [json.loads(line) for line in resp.iter_lines() if line.strip()]
    assert lines[-1]["type"] == "done"
    mock_respond.assert_called_once()
    assert "model" not in mock_respond.call_args.kwargs


def test_video_length_is_chosen_and_hazlo_de_10_segundos_repeats_the_same_video():
    sid = "ses_video_largo"
    video_replies.last_videos.pop(sid, None)
    plan = ("A dog runs on a beach.", None, (768, 512))
    with patch.object(routes_sessions, "own_session_id", return_value=sid), \
         patch.object(main.router, "classify", return_value={"agent": "video", "factual": False}), \
         patch.object(main.prompt_writer, "video_plan", return_value=plan) as mock_plan, \
         patch.object(main.video_agent, "generate", return_value=b"fake-mp4") as mock_gen:
        first = client.post("/chat", json={"message": "un perro corriendo por la playa"}).json()
        assert "(4 s)" in first["response"] and "A dog runs on a beach." in first["response"]
        seed = mock_gen.call_args.kwargs["seed"]
        again = client.post("/chat", json={"message": "hazlo de 10 segundos"}).json()
    assert mock_plan.call_count == 1
    assert mock_gen.call_args.kwargs["seconds"] == 10.0 and mock_gen.call_args.kwargs["seed"] == seed
    assert mock_gen.call_args.args[0] == "A dog runs on a beach." and "(10 s)" in again["response"]
    video_replies.last_videos.pop(sid, None)


def _png(width, height):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(buf, "PNG")
    return buf.getvalue()


def test_a_film_request_goes_scene_by_scene_and_shows_the_script():
    scenes = [{"prompt": "An astronaut lands on Mars.", "segundos": 4.0},
              {"prompt": "He finds a dog.", "segundos": 5.0}]
    with patch.object(film, "plan_scenes", return_value=scenes), \
         patch.object(film, "make", return_value=(b"mp4", [b"a", b"b"])) as make:
        data = client.post("/chat", json={"message": "una película de un astronauta que encuentra un perro en Marte",
                                          "agent": "video"}).json()
    assert make.call_args.args[0] == scenes
    assert "Película de 2 escenas (~9 s)" in data["response"] and "2. He finds a dog." in data["response"]
    assert data["file_url"].endswith(".mp4")
    with patch.object(main.prompt_writer, "video_prompt", return_value="He finds a dog at night.") as rewrite, \
         patch.object(film, "redo", return_value=(b"mp4b", [b"a", b"c"])) as redo:
        again = client.post("/chat", json={"message": "rehaz la escena 2 pero de noche", "agent": "video",
                                           "session_id": data["session_id"]}).json()
    assert redo.call_args.args[1:3] == ([b"a", b"b"], 1) and "de noche" in rewrite.call_args.args[2]
    assert redo.call_args.args[0][0] == scenes[0] and redo.call_args.args[0][1]["prompt"] == "He finds a dog at night."
    assert "Escena 2 rehecha" in again["response"] and again["file_url"].endswith(".mp4")


def _tiny_jpeg_b64(color=(120, 90, 60)):
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_image_from_a_simple_request_goes_through_the_prompt_writer():
    with patch.object(main.prompt_writer, "image_prompt",
                      return_value=("A realistic photo of a dog in fresh snow.", (832, 1216))) as mock_writer, \
         patch.object(main.image_agent, "generate", return_value=b"png") as mock_gen:
        resp = client.post("/chat", json={"message": "un perro en la nieve", "agent": "image"})
    assert resp.json()["agent_used"] == "image"
    assert mock_writer.call_args.args[2] == "un perro en la nieve"
    assert mock_gen.call_args.args[0] == "A realistic photo of a dog in fresh snow."
    assert (mock_gen.call_args.kwargs["width"], mock_gen.call_args.kwargs["height"]) == (832, 1216)


def test_chat_stream_to_agent_includes_task_id_for_the_inline_card():
    with patch.object(main.opencode_client, "delegate", return_value=("Se lo he pasado al agente.", "ses_9")), client.stream("POST", "/chat/stream",
                       json={"message": "usa un agente y crea hola.txt en el escritorio"}) as resp:
        lines = [json.loads(line) for line in resp.iter_lines() if line.strip()]
    start = next(e for e in lines if e["type"] == "start")
    assert start["agent_used"] == "opencode"
    assert lines[-1]["agent_task_id"] == "ses_9"


def test_guest_cannot_trigger_the_agent_from_chat():
    guest_token = client.post("/auth/guest").json()["token"]
    guest_client = TestClient(app, headers={"X-Session-Token": guest_token})
    with patch.object(main.opencode_client, "delegate") as mock_delegate:
        resp = guest_client.post("/chat", json={"message": "agente: borra mis fotos"})
    assert resp.json()["agent_task_id"] is None
    assert "invitado" in resp.json()["response"]
    mock_delegate.assert_not_called()


def _other_user_client():
    uname = f"_test_otro_{uuid.uuid4().hex[:8]}"
    anon = TestClient(app)
    anon.post("/auth/register", json={"username": uname, "password": _TEST_PASSWORD,
                                      "registration_key": users_module.get_or_create_registration_key()})
    token = anon.post("/auth/login", json={"username": uname, "password": _TEST_PASSWORD}).json()["token"]
    return uname, TestClient(app, headers={"X-Session-Token": token})


_ADMIN_ROUTES = [
    ("get", "/metrics/summary", {}, "Solo un administrador puede ver esto."),
    ("post", "/models/update", {"data": {"model": "x"}}, "Solo un administrador puede actualizar modelos."),
    ("get", "/app/update", {}, "Solo un administrador puede actualizar Chati."),
    ("post", "/app/update", {}, "Solo un administrador puede actualizar Chati."),
    ("post", "/app/github_token", {"json": {"token": "x"}}, "Solo un administrador puede actualizar Chati."),
    ("delete", "/models/text/x", {}, "Solo un administrador puede borrar modelos."),
    ("get", "/admin/errors", {}, "Solo para administradores."),
    ("delete", "/models/image/x", {}, "Solo un administrador puede borrar modelos."),
    ("delete", "/models/video/x", {}, "Solo un administrador puede borrar modelos."),
]


@pytest.mark.parametrize("method,path,kwargs,detail", _ADMIN_ROUTES)
def test_admin_routes_answer_403_with_their_message_to_other_users(method, path, kwargs, detail):
    _, other = _other_user_client()
    resp = getattr(other, method)(path, **kwargs)
    assert (resp.status_code, resp.json()["detail"]) == (403, detail)


def _my_session_with_a_message():
    owner_id = users_module.get_user(_TEST_USERNAME)["id"]
    sid = main.memory.new_session_id()
    main.memory.add_message(sid, "user", "hola", user_id=owner_id)
    return sid


def test_other_users_and_guests_cannot_touch_my_conversation():
    sid = _my_session_with_a_message()
    msg_id = main.memory.get_history(sid, limit=5)[0]["id"]
    uname, other = _other_user_client()
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    try:
        for c, code in ((other, 404), (guest, 403)):
            assert c.delete(f"/sessions/{sid}").status_code == code
            assert c.get(f"/sessions/{sid}").status_code == code
            assert c.delete(f"/sessions/{sid}/messages/{msg_id}").status_code == code
        assert main.memory.session_owner(sid) is not None
    finally:
        users_module.delete_user(uname)

    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert main.memory.session_owner(sid) is None


def test_chat_with_someone_elses_session_id_starts_a_new_one():
    sid = _my_session_with_a_message()
    uname, other = _other_user_client()
    try:
        with patch.object(main.opencode_client, "delegate", return_value=("ok", None)):
            resp = other.post("/chat", json={"message": "agente: hola", "session_id": sid})
        assert resp.json()["session_id"] != sid
    finally:
        users_module.delete_user(uname)
        client.delete(f"/sessions/{sid}")


def test_attach_doc_creates_conversation_and_reaches_the_model():
    resp = client.post("/sessions/docs", files={"file": ("nota.txt", b"El codigo secreto es 4711.", "text/plain")})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert client.get(f"/sessions/{sid}/docs").json() == [{"name": "nota.txt", "chars": 26}]

    seen = {}

    def fake_respond(message, history, *args, **kwargs):
        seen["message"] = message
        return "El codigo es 4711.", []

    with patch.object(text_agent, "respond_with_tools", side_effect=fake_respond), \
         patch.object(gpu_memory, "ensure_active_model"):
        r = client.post("/chat", json={"message": "¿cual es el codigo?", "agent": "text",
                                       "session_id": sid, "verify": False})
    assert r.status_code == 200
    assert "4711" in seen["message"] and "nota.txt" in seen["message"]
    history = client.get(f"/sessions/{sid}").json()
    assert history[0]["agent"] == "adjunto" and "nota.txt" in history[0]["content"]
    assert history[1]["content"] == "¿cual es el codigo?"

    uname, other = _other_user_client()
    try:
        assert other.get(f"/sessions/{sid}/docs").json() == []
    finally:
        users_module.delete_user(uname)
    client.delete(f"/sessions/{sid}")
    assert client.get(f"/sessions/{sid}/docs").json() == []


def test_attach_doc_rejects_bad_files_and_guests():
    assert client.post("/sessions/docs", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.post("/sessions/docs", files={"file": ("a.txt", b"hola", "text/plain")}).status_code == 403


def test_generation_frees_every_loaded_ollama_model_first():
    with patch.object(main.ollama, "running_models", return_value=["qwen2.5:7b", "qwen3-coder:30b-cpu"]), \
         patch.object(main.opencode_client, "busy_session_ids", return_value=[]), \
         patch.object(main.ollama, "unload") as mock_unload:
        main.comfyui_client.before_submit()
    assert [c.args[0] for c in mock_unload.call_args_list] == ["qwen2.5:7b", "qwen3-coder:30b-cpu"]


def test_generation_keeps_the_agent_models_while_a_task_is_running():
    with patch.object(main.ollama, "running_models",
                      return_value=["qwen2.5:7b", "qwen3:8b", "qwen3-coder:30b-cpu", "qwen2.5vl:7b-cpu"]), \
         patch.object(main.opencode_client, "busy_session_ids", return_value=["ses_1"]), \
         patch.object(main.ollama, "unload") as mock_unload:
        main.comfyui_client.before_submit()
    assert [c.args[0] for c in mock_unload.call_args_list] == ["qwen2.5:7b", "qwen2.5vl:7b-cpu"]


def _run_before_task(agent, loaded):
    import threading as _threading
    ran = _threading.Event()
    with patch.object(main.ollama, "running_models", return_value=loaded), \
         patch.object(main.ollama, "unload") as mock_unload, \
         patch.object(main.comfyui_client, "free_memory", side_effect=lambda *_: ran.set()) as mock_free:
        main.opencode_client.before_task(agent)
        assert ran.wait(5)
    return [c.args[0] for c in mock_unload.call_args_list], mock_free.call_count


def test_powerful_agent_task_frees_ram_and_comfyui():
    with patch.object(main.opencode_client, "busy_session_ids", return_value=[]):
        unloaded, frees = _run_before_task("chati-potente", ["qwen3:8b", "qwen2.5vl:7b-cpu", "qwen3-coder:30b-mixto"])
    assert unloaded == ["qwen3:8b", "qwen2.5vl:7b-cpu"] and frees == 1


def test_fast_agent_task_makes_room_on_the_gpu():
    with patch.object(main.opencode_client, "busy_session_ids", return_value=[]):
        unloaded, frees = _run_before_task("chati", ["qwen3:8b", "qwen2.5vl:7b-gpu", "nomic-embed-text:latest"])
    assert unloaded == ["qwen2.5vl:7b-gpu"] and frees == 1


def test_agent_tasks_use_the_fast_agent_unless_potente_is_asked():
    with patch.object(main.opencode_client, "start_task", return_value="ses_1") as mock_start:
        client.post("/agent/tasks", json={"task": "crea un archivo"})
        client.post("/agent/tasks", json={"task": "refactoriza el proyecto", "potente": True})
    assert [c.args[2] for c in mock_start.call_args_list] == ["chati", "chati-potente"]


def test_chat_stream_warns_when_the_model_has_to_be_loaded():
    def fake_stream(*args, **kwargs):
        yield "hola"
    with patch.object(main.ollama, "running_models", return_value=[]), \
         patch.object(gpu_memory, "ensure_active_model"), \
         patch.object(text_agent, "respond_with_tools_stream", side_effect=fake_stream), \
         client.stream("POST", "/chat/stream", json={"message": "hola", "model_profile": "rapido", "verify": False}) as resp:
        lines = [json.loads(line) for line in resp.iter_lines() if line.strip()]
    statuses = [e for e in lines if e["type"] == "status"]
    assert len(statuses) == 1
    assert "Cargando el modelo" in statuses[0]["text"]
    client.delete(f"/sessions/{lines[-1]['session_id']}")


def test_chat_stream_says_nothing_when_the_model_is_already_loaded():
    def fake_stream(*args, **kwargs):
        yield "hola"
    with patch.object(main.ollama, "running_models", return_value=["qwen3:8b"]), \
         patch.object(gpu_memory, "ensure_active_model"), \
         patch.object(text_agent, "respond_with_tools_stream", side_effect=fake_stream), \
         client.stream("POST", "/chat/stream", json={"message": "hola", "model_profile": "rapido", "verify": False}) as resp:
        lines = [json.loads(line) for line in resp.iter_lines() if line.strip()]
    assert not [e for e in lines if e["type"] == "status"]
    client.delete(f"/sessions/{lines[-1]['session_id']}")


def _wait_prepare_done(timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get("/models/prepare").json()
        if st["state"] != "preparing":
            return st
        time.sleep(0.05)
    raise AssertionError("la preparacion no termino")


def test_prepare_rejects_unknown_modes():
    assert client.post("/models/prepare", json={"mode": "cocina"}).status_code == 400


def test_prepare_chat_mode_loads_the_default_profile_model_and_frees_comfyui():
    with patch.object(main.ollama, "preload") as mock_preload, \
         patch.object(main.ollama, "running_models", return_value=[]), \
         patch.object(main.comfyui_client, "free_memory") as mock_free:
        resp = client.post("/models/prepare", json={"mode": "texto"})
        assert resp.json()["state"] == "preparing"
        st = _wait_prepare_done()
    assert st["state"] == "ready"
    assert "qwen3:8b" in st["label"]
    mock_preload.assert_called_once_with("qwen3:8b")
    mock_free.assert_called_once()


def test_prepare_image_mode_warms_up_with_a_tiny_image():
    with patch.object(main.image_agent, "generate", return_value=b"png") as mock_gen:
        client.post("/models/prepare", json={"mode": "image"})
        st = _wait_prepare_done()
    assert st["state"] == "ready"
    assert "imagenes" in st["label"]
    assert mock_gen.call_args.kwargs["width"] == 256


def test_prepare_reports_errors_and_only_the_last_request_counts():
    import threading as _threading
    release = _threading.Event()

    def slow_preload(model, *a, **k):
        release.wait(5)

    with patch.object(main.ollama, "preload", side_effect=slow_preload), \
         patch.object(main.ollama, "running_models", return_value=[]), \
         patch.object(main.comfyui_client, "free_memory"), \
         patch.object(main.image_agent, "generate", side_effect=RuntimeError("no hay modelo")):
        client.post("/models/prepare", json={"mode": "chat"})
        client.post("/models/prepare", json={"mode": "image"})
        st = _wait_prepare_done()
        release.set()
        deadline = time.time() + 5
        while time.time() < deadline and any(t.name.startswith("preparar-") and t.is_alive()
                                             for t in _threading.enumerate()):
            time.sleep(0.05)
    final = client.get("/models/prepare").json()
    assert st["mode"] == "image" and st["state"] == "error" and "no hay modelo" in st["detail"]
    assert final["mode"] == "image" and final["state"] == "error"


def _prepare_and_collect_unloads(body, loaded, busy=()):
    with patch.object(main.ollama, "running_models", return_value=loaded), \
         patch.object(main.ollama, "unload") as mock_unload, \
         patch.object(main.ollama, "preload"), \
         patch.object(main.opencode_client, "busy_session_ids", return_value=list(busy)), \
         patch.object(main.comfyui_client, "free_memory") as mock_free, \
         patch.object(main.comfyui_client, "user_queue", return_value=(0, 0)), \
         patch.object(main.image_agent, "generate", return_value=b"png"), \
         patch.object(main.video_agent, "generate", return_value=b"mp4"):
        client.post("/models/prepare", json=body)
        assert _wait_prepare_done()["state"] == "ready"
    return [c.args[0] for c in mock_unload.call_args_list], mock_free.call_count


def test_switching_to_chat_unloads_the_agent_and_vision_models():
    unloaded, _ = _prepare_and_collect_unloads(
        {"mode": "texto"},
        ["qwen3:8b", "qwen3-coder:30b-cpu", "qwen2.5vl:7b-cpu", "nomic-embed-text:latest"])
    assert unloaded == ["qwen3-coder:30b-cpu", "qwen2.5vl:7b-cpu"]


def test_switching_modes_keeps_the_agent_model_while_a_task_runs():
    unloaded, _ = _prepare_and_collect_unloads(
        {"mode": "chat"}, ["qwen3:8b", "qwen3-coder:30b-cpu", "qwen2.5vl:7b-cpu"], busy=["ses_1"])
    assert unloaded == ["qwen2.5vl:7b-cpu"]


def test_switching_image_model_frees_the_previous_one_but_repeating_does_not():
    gpu_memory.last_comfy_warmup = None
    _, frees_first = _prepare_and_collect_unloads({"mode": "image", "image_model": "flux:a"}, [])
    _, frees_same = _prepare_and_collect_unloads({"mode": "image", "image_model": "flux:a"}, [])
    _, frees_other = _prepare_and_collect_unloads({"mode": "video"}, [])
    assert (frees_first, frees_same, frees_other) == (0, 0, 1)


def test_pending_work_lists_working_and_waiting_tasks_and_generations():
    with patch.object(main.opencode_client, "busy_session_ids", return_value=["ses_1"]), \
         patch.object(main.opencode_client, "waiting_sessions", return_value={"ses_viejo": "question"}), \
         patch.object(main.opencode_client, "task_summary", side_effect=lambda b, sid: f"tarea {sid}"), \
         patch.object(main.comfyui_client, "user_jobs",
                      return_value=[{"id": "p1", "state": "running"}, {"id": "p2", "state": "queued"}]):
        data = client.get("/work/pending").json()
    assert data["agent_tasks"] == [{"session_id": "ses_1", "title": "tarea ses_1", "modelo_ahora": None, "atascada_min": 0}]
    assert data["waiting_tasks"] == [{"session_id": "ses_viejo", "title": "tarea ses_viejo", "reason": "question"}]
    assert (data["generations_running"], data["generations_queued"], data["any"]) == (1, 1, True)


def test_a_task_only_waiting_for_the_user_does_not_block_mode_changes():
    with patch.object(main.opencode_client, "busy_session_ids", return_value=[]), \
         patch.object(main.opencode_client, "waiting_sessions", return_value={"ses_viejo": "question"}), \
         patch.object(main.opencode_client, "task_summary", return_value="x"), \
         patch.object(main.comfyui_client, "user_jobs", return_value=[]):
        data = client.get("/work/pending").json()
    assert data["any"] is False and len(data["waiting_tasks"]) == 1


def test_stop_single_agent_task_and_generation():
    with patch.object(main.opencode_client, "stop_task") as mock_stop_task, \
         patch.object(main.comfyui_client, "stop_job") as mock_stop_job:
        assert client.post("/work/agent/ses_viejo/stop").status_code == 200
        assert client.post("/work/generation/p2/stop").status_code == 200
    assert mock_stop_task.call_args.args[1] == "ses_viejo"
    assert mock_stop_job.call_args.args[1] == "p2"


def test_pending_work_is_empty_when_nothing_runs():
    with patch.object(main.opencode_client, "busy_session_ids", return_value=[]), \
         patch.object(main.opencode_client, "waiting_sessions", return_value={}), \
         patch.object(main.comfyui_client, "user_jobs", return_value=[]):
        assert client.get("/work/pending").json()["any"] is False


def test_stop_work_aborts_agent_tasks_and_comfyui():
    with patch.object(main.opencode_client, "busy_session_ids", return_value=["ses_1", "ses_2"]), \
         patch.object(main.opencode_client, "abort") as mock_abort, \
         patch.object(main.comfyui_client, "stop_owned") as mock_stop:
        assert client.post("/work/stop").status_code == 200
    assert [c.args[1] for c in mock_abort.call_args_list] == ["ses_1", "ses_2"]
    mock_stop.assert_called_once()


def test_stopping_only_touches_your_own_generations():
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    jobs = [{"id": "ajeno", "state": "running"}]
    with main.comfyui_client._owners_lock:
        main.comfyui_client._owners["ajeno"] = "otro-usuario"
    try:
        with patch.object(main.comfyui_client, "user_jobs", return_value=jobs), \
             patch.object(main.comfyui_client, "stop_job") as mock_stop, \
             patch.object(main.opencode_client, "busy_session_ids", return_value=[]), \
             patch.object(main.opencode_client, "waiting_sessions", return_value={}):
            assert guest.post("/cancel").status_code == 200
            assert client.post("/cancel").status_code == 200
            assert client.post("/work/generation/ajeno/stop").status_code == 403
            assert client.post("/work/stop").status_code == 200
            assert client.get("/work/pending").json()["generations"] == []
        mock_stop.assert_not_called()
    finally:
        with main.comfyui_client._owners_lock:
            main.comfyui_client._owners.pop("ajeno", None)


def test_changing_mode_never_frees_comfyui_in_the_middle_of_a_generation():
    with patch.object(main.comfyui_client, "user_queue", return_value=(1, 0)), \
         patch.object(main.comfyui_client, "free_memory") as mock_free:
        gpu_memory.free_comfyui()
    mock_free.assert_not_called()


def test_automatic_mode_with_the_quality_profile_swaps_the_models_at_once():
    with patch.object(main.ollama, "running_models", return_value=["qwen3:8b", "qwen2.5vl:7b-cpu"]), \
         patch.object(main.ollama, "unload") as mock_unload, \
         patch.object(main.ollama, "preload") as mock_preload, \
         patch.object(main.opencode_client, "busy_session_ids", return_value=[]), \
         patch.object(main.comfyui_client, "free_memory"):
        client.post("/models/prepare", json={"mode": "chat", "model_profile": "bueno"})
        st = _wait_prepare_done()
    assert st["state"] == "ready" and "qwen3-coder:30b-cpu" in st["label"]
    assert [c.args[0] for c in mock_unload.call_args_list] == ["qwen2.5vl:7b-cpu"]
    assert [c.args[0] for c in mock_preload.call_args_list] == ["qwen3:8b", "qwen3-coder:30b-cpu"]


@pytest.mark.assess
def test_complex_task_asks_which_model_instead_of_starting():
    with patch.object(main.router, "assess_agent_task", return_value={"complex": True, "reason": "hay que programar"}),          patch.object(main.opencode_client, "start_task") as mock_start:
        data = client.post("/agent/tasks", json={"task": "añade un endpoint"}).json()
    assert data == {"needs_choice": True, "task": "añade un endpoint", "reason": "hay que programar", "attachments": []}
    mock_start.assert_not_called()


@pytest.mark.assess
def test_after_choosing_or_with_potente_there_is_no_assessment():
    with patch.object(main.router, "assess_agent_task") as mock_assess,          patch.object(main.opencode_client, "start_task", return_value="ses_1") as mock_start:
        client.post("/agent/tasks", json={"task": "x", "confirmed": True})
        client.post("/agent/tasks", json={"task": "x", "potente": True})
    mock_assess.assert_not_called()
    assert [c.args[2] for c in mock_start.call_args_list] == ["chati", "chati-potente"]


@pytest.mark.assess
def test_simple_task_starts_right_away_and_a_failing_assessment_never_blocks():
    with patch.object(main.opencode_client, "start_task", return_value="ses_1"):
        with patch.object(main.router, "assess_agent_task", return_value={"complex": False, "reason": ""}):
            assert client.post("/agent/tasks", json={"task": "crea hola.txt"}).json() == {"session_id": "ses_1"}
        with patch.object(main.router, "assess_agent_task", side_effect=RuntimeError("ollama caido")):
            assert client.post("/agent/tasks", json={"task": "crea hola.txt"}).json() == {"session_id": "ses_1"}


@pytest.mark.assess
def test_chat_delegation_of_a_complex_task_offers_the_choice():
    with patch.object(main.router, "assess_agent_task", return_value={"complex": True, "reason": "hay que depurar"}),          patch.object(main.opencode_client, "delegate") as mock_delegate:
        data = client.post("/chat", json={"message": "agente: arregla el bug del login"}).json()
    mock_delegate.assert_not_called()
    assert data["agent_task_id"] is None
    assert data["agent_choice"] == {"task": "agente: arregla el bug del login", "reason": "hay que depurar"}
    client.delete(f"/sessions/{data['session_id']}")


def test_agent_follow_up_goes_to_the_same_task():
    with patch.object(main.opencode_client, "continue_task") as mock_continue:
        assert client.post("/agent/tasks/ses_1/message", json={"text": "  ahora en Trabajo "}).status_code == 200
        assert client.post("/agent/tasks/ses_1/message", json={"text": "   "}).status_code == 400
    assert mock_continue.call_args.args[1:] == ("ses_1", "ahora en Trabajo", None)
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.post("/agent/tasks/ses_1/message", json={"text": "x"}).status_code == 403


def test_agent_shortcuts_per_user_and_blocked_for_guests():
    assert client.get("/agent/shortcuts").status_code == 200
    saved = client.put("/agent/shortcuts", json={"shortcuts": [{"name": "Mi atajo", "task": "haz algo"}]}).json()
    assert saved == [{"name": "Mi atajo", "task": "haz algo", "potente": False, "donde": "agente"}]
    assert client.get("/agent/shortcuts").json() == saved
    assert client.put("/agent/shortcuts", json={"shortcuts": [{"name": "", "task": "x"}]}).status_code == 400
    uname, other = _other_user_client()
    try:
        assert other.get("/agent/shortcuts").status_code == 403
        assert client.put(f"/auth/users/{uname}/pc_access", json={"allowed": True}).status_code == 200
        assert other.get("/agent/shortcuts").json()[0]["name"] == "Ordenar Descargas"
    finally:
        users_module.delete_user(uname)
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.get("/agent/shortcuts").status_code == 403


def test_llm_proxy_only_for_opencode_and_cleans_streamed_tool_calls():
    from unittest.mock import MagicMock
    chunk = {"choices": [{"delta": {"tool_calls": [{"function": {"name": "bash",
             "arguments": '{"command": "dir", "workdir": null}'}}]}}]}
    upstream = MagicMock(status_code=200, headers={"content-type": "text/event-stream"})
    upstream.iter_lines.return_value = [b"data: " + json.dumps(chunk).encode(), b"", b"data: [DONE]"]
    assert TestClient(app).post("/llm/v1/chat/completions", json={"model": "m"}).status_code == 401
    opencode = TestClient(app, headers={"Authorization": f"Bearer {main.opencode_client.AUTH[1]}"})
    with patch.object(main.requests, "request", return_value=upstream) as mock_req:
        resp = opencode.post("/llm/v1/chat/completions", json={"model": "m", "stream": True})
    assert resp.status_code == 200
    assert mock_req.call_args.args[1].endswith("/v1/chat/completions")
    assert '\\"workdir\\"' not in resp.text and "[DONE]" in resp.text


def test_llm_proxy_only_reaches_the_chat_api():
    opencode = TestClient(app, headers={"Authorization": f"Bearer {main.opencode_client.AUTH[1]}"})
    with patch.object(main.requests, "request") as mock_req:
        for bad in ("/llm/v1/%2e%2e/api/pull", "/llm/v1/..%2Fapi%2Fcreate", "/llm/v1/chat%3Fx"):
            assert "Ruta no permitida" in opencode.post(bad, json={"model": "m"}).text, bad
    mock_req.assert_not_called()


def _live_events(opencode_lines):
    from unittest.mock import MagicMock
    upstream = MagicMock()
    upstream.__enter__.return_value = upstream
    upstream.iter_lines.return_value = opencode_lines
    snaps = iter(range(100))
    with patch.object(routes_agent, "_task_view", side_effect=lambda b, sid: {"n": next(snaps)}), \
         patch.object(main.requests, "get", return_value=upstream):
        resp = client.get("/agent/tasks/ses_1/live")
    return [ln for ln in resp.text.split("\n\n") if ln.strip()]


def test_live_sends_a_snapshot_per_event_of_this_task_only():
    blocks = _live_events([
        b'data: {"type":"session.status","properties":{"sessionID":"ses_1"}}',
        b'data: {"type":"session.status","properties":{"sessionID":"ses_otra"}}',
        b'data: {"type":"server.heartbeat","properties":{}}',
        b'data: {"type":"session.idle","properties":{"sessionID":"ses_1"}}',
    ])
    assert blocks == ['data: {"n": 0}', 'data: {"n": 1}', ": ping", 'data: {"n": 2}', "event: end\ndata: {}"]


def test_live_throttles_word_by_word_text():
    deltas = [b'data: {"type":"message.part.delta","properties":{"sessionID":"ses_1","delta":"x"}}'] * 20
    blocks = _live_events(deltas)
    snapshots = [b for b in blocks if b.startswith("data:")]
    assert 2 <= len(snapshots) < 10


def test_live_ends_cleanly_when_opencode_is_down():
    with patch.object(routes_agent, "_task_view", return_value={"n": 0}), \
         patch.object(main.requests, "get", side_effect=requests.ConnectionError("caido")):
        text = client.get("/agent/tasks/ses_1/live").text
    assert text.strip().endswith("event: end\ndata: {}")


def test_live_shows_text_while_it_is_being_written():
    from unittest.mock import MagicMock
    upstream = MagicMock()
    upstream.__enter__.return_value = upstream
    delta = lambda t: ('data: {"type":"message.part.delta","properties":{"sessionID":"ses_1","partID":"p1",'
                       '"field":"text","delta":"' + t + '"}}').encode()
    upstream.iter_lines.return_value = [
        delta("Hola "), delta("mundo"),
        b'data: {"type":"session.status","properties":{"sessionID":"ses_1","status":{"type":"busy"}}}',
        b'data: {"type":"message.part.updated","properties":{"sessionID":"ses_1","part":{"id":"p1","type":"text","text":"Hola mundo"}}}',
    ]
    with patch.object(routes_agent, "_task_view", side_effect=lambda b, sid: {"status": "busy", "steps": []}), \
         patch.object(main.requests, "get", return_value=upstream), \
         patch.object(routes_agent, "LIVE_THROTTLE", 0):
        blocks = [json.loads(b[6:]) for b in client.get("/agent/tasks/ses_1/live").text.split("\n\n") if b.startswith("data: {")]
    streamed = [b.get("streaming_text") for b in blocks]
    assert streamed == [None, "Hola ", "Hola mundo", "Hola mundo", None]


def test_attachments_are_copied_images_described_and_listed_in_the_task(tmp_path, monkeypatch):
    import io

    from PIL import Image
    monkeypatch.setattr(main.agent_attachments, "ATTACH_ROOT", tmp_path)
    png = io.BytesIO()
    Image.new("RGB", (40, 30), (0, 128, 255)).save(png, format="PNG")
    with patch.object(gpu_memory, "ensure_active_model"),          patch.object(main.vision_agent, "respond_with_image_stream", return_value=iter(["una playa azul"])):
        up = client.post("/agent/attachments", files=[
            ("files", ("factura.txt", b"Total: 42 euros", "text/plain")),
            ("files", ("foto.png", png.getvalue(), "image/png")),
        ]).json()
    names = {f["name"]: f for f in up["files"]}
    assert (tmp_path / names["factura.txt"]["path"].split("/")[-2] / "factura.txt").read_bytes() == b"Total: 42 euros"
    assert names["factura.txt"]["description"] is None
    assert names["foto.png"]["description"] == "una playa azul"

    with patch.object(main.opencode_client, "start_task", return_value="ses_1") as mock_start:
        client.post("/agent/tasks", json={"task": "ordena esto", "attachments": up["files"]})
    sent = mock_start.call_args.args[1]
    assert sent.startswith("ordena esto")
    assert names["foto.png"]["path"] in sent and "se ve: una playa azul" in sent


def test_attachments_limits_and_guests():
    too_many = [("files", (f"a{i}.txt", b"x", "text/plain")) for i in range(11)]
    assert client.post("/agent/attachments", files=too_many).status_code == 400
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.post("/agent/attachments", files=[("files", ("a.txt", b"x", "text/plain"))]).status_code == 403


def test_code_mode_tasks_go_to_the_project_with_the_chosen_agent(tmp_path):
    with patch.object(main.opencode_client, "start_task", return_value="ses_c") as mock_start:
        r = client.post("/agent/tasks", json={"task": "revisa la estructura", "project": str(tmp_path), "plan": True})
        assert r.json() == {"session_id": "ses_c"}
        assert mock_start.call_args.args[1:] == ("revisa la estructura", "chati-code-plan", str(tmp_path), None)
        client.post("/agent/tasks", json={"task": "hazlo", "project": str(tmp_path), "rapido": True})
        assert mock_start.call_args.args[2:] == ("chati-code", str(tmp_path), main.CONFIG["opencode"]["model"])
        client.post("/agent/tasks", json={"task": "¿que hace precios.py?", "project": str(tmp_path)})
        assert mock_start.call_args.args[2:] == ("chati-code-plan", str(tmp_path), main.CONFIG["opencode"]["model"])
        assert client.post("/agent/tasks", json={"task": "x", "project": str(tmp_path / "no-existe")}).status_code == 400
    with patch.object(main.opencode_client, "continue_task") as mock_continue:
        client.post("/agent/tasks/ses_c/message", json={"text": "adelante", "code_mode": "build"})
    assert mock_continue.call_args.args[1:] == ("ses_c", "adelante", "chati-code")


def test_a_new_message_follows_the_finished_task_of_the_conversation(tmp_path):
    other = tmp_path / "otro"
    other.mkdir()
    idle = [patch.object(main.opencode_client, "busy_session_ids", return_value=[]),
            patch.object(main.opencode_client, "waiting_sessions", return_value={}),
            patch.object(main.opencode_client, "task_summary", return_value="crear host manager"),
            patch.object(main.opencode_client, "session_dir", return_value=str(tmp_path)),
            patch.object(agent_watch, "start_code_watch")]
    for p in idle:
        p.start()
    try:
        with patch.object(main.opencode_client, "continue_task") as mock_continue, \
             patch.object(main.opencode_client, "start_task", return_value="ses_nueva") as mock_start:
            same = client.post("/agent/tasks", json={"task": "pon los desactivados en gris", "project": str(tmp_path),
                                                     "continuar": "ses_c"}).json()
            assert same == {"session_id": "ses_c", "continued": True, "ok": True, "mode": "build"}
            assert mock_continue.call_args.args[1:3] == ("ses_c", "pon los desactivados en gris")
            mock_start.assert_not_called()

            new = client.post("/agent/tasks", json={"task": "haz una web", "project": str(other),
                                                    "continuar": "ses_c"}).json()
            assert new == {"session_id": "ses_nueva"}

            with patch.object(main.router, "same_task", return_value=False):
                new = client.post("/agent/tasks", json={"task": "ordena mis descargas", "continuar": "ses_a",
                                                        "confirmed": True}).json()
            assert new == {"session_id": "ses_nueva"}
            with patch.object(main.router, "same_task", return_value=True):
                same = client.post("/agent/tasks", json={"task": "no, en la carpeta Trabajo", "continuar": "ses_a"})
                assert same.json()["continued"] is True
                assert mock_continue.call_args.args[3] is None
                client.post("/agent/tasks", json={"task": "no hace nada, arreglalo tu", "continuar": "ses_a"})
                assert mock_continue.call_args.args[3] == main.CONFIG["opencode"]["agent_potente"]
        with patch.object(main.opencode_client, "busy_session_ids", return_value=["ses_a"]), \
             patch.object(main.opencode_client, "start_task", return_value="ses_otra"):
            busy = client.post("/agent/tasks", json={"task": "y otra cosa", "continuar": "ses_a", "confirmed": True})
            assert busy.json() == {"session_id": "ses_otra"}
    finally:
        for p in idle:
            p.stop()


def test_the_router_says_if_a_message_follows_the_task():
    from unittest.mock import MagicMock

    from chat.router import Router
    r = Router(MagicMock(), "m")
    r.client.chat.return_value = '{"misma": "no"}'
    assert r.same_task("ordenar descargas", "haz una web nueva") is False
    r.client.chat.return_value = '{"misma": "si"}'
    assert r.same_task("ordenar descargas", "no, mejor por fecha") is True
    r.client.chat.return_value = "no se"
    assert r.same_task("a", "b") is True


def test_code_projects_are_remembered_and_git_is_only_activated_on_request(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("x")
    info = client.post("/code/projects", json={"path": str(tmp_path)}).json()
    assert info["exists"] and not info["git"] and info["entries"] == ["README.md", "src/"]
    assert client.get("/code/projects").json()["projects"][0]["path"] == str(tmp_path)
    assert not (tmp_path / ".git").exists()
    assert client.post("/code/git_init", json={"path": str(tmp_path)}).json()["git"]
    assert client.post("/code/projects", json={"path": str(tmp_path / "nada")}).status_code == 400


def test_requests_to_another_host_are_rejected():
    evil = TestClient(app, base_url="http://evil.example:8899")
    assert evil.get("/health").status_code == 400
    assert evil.post("/auth/guest").status_code == 400
    assert TestClient(app, base_url="http://127.0.0.1:8899").get("/health").status_code == 200
    assert TestClient(app, base_url="http://localhost:8899").get("/health").status_code == 200


def test_changes_from_another_origin_are_rejected():
    local = TestClient(app, base_url="http://127.0.0.1:8899")
    assert local.post("/auth/guest", headers={"Origin": "http://evil.example"}).status_code == 403
    assert local.post("/auth/guest", headers={"Origin": "http://127.0.0.1:8188"}).status_code == 403
    assert local.post("/auth/guest", headers={"Origin": "http://127.0.0.1:8899"}).status_code == 200
    assert local.post("/auth/guest").status_code == 200


def test_security_headers_are_sent():
    resp = client.get("/health")
    assert "script-src 'self'" in resp.headers["content-security-policy"]
    assert resp.headers["x-frame-options"] == "DENY"


def test_session_cookie_is_httponly_and_the_url_token_is_gone():
    local = TestClient(app, base_url="http://127.0.0.1:8899")
    resp = local.post("/auth/guest")
    cookie = resp.headers["set-cookie"].lower()
    assert "chati_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert local.get("/auth/me").json()["role"] == "guest"
    token = resp.json()["token"]
    assert TestClient(app).get(f"/auth/me?session={token}").status_code == 401


def test_user_without_pc_access_cannot_touch_the_computer():
    uname, other = _other_user_client()
    try:
        assert other.get("/auth/me").json()["pc_access"] is False
        assert other.get("/agent/tasks").status_code == 403
        assert other.post("/code/projects", json={"path": "C:/"}).status_code == 403
        assert main._execute_tool("leer_archivo", {"ruta": "C:/Windows/win.ini"}, "s")[0].startswith("Esta cuenta no")
        assert main._execute_tool("ejecutar_python", {"codigo": "print(1)"}, "s")[0].startswith("Esta cuenta no")
        names = {t["function"]["name"] for t in main._tools_for("text", pc_access=False)}
        assert not names & main.PC_TOOLS and "buscar_en_memoria" in names
        assert client.put(f"/auth/users/{uname}/pc_access", json={"allowed": True}).status_code == 200
        assert other.get("/auth/me").json()["pc_access"] is True
        assert other.put(f"/auth/users/{uname}/pc_access", json={"allowed": True}).status_code == 403
    finally:
        users_module.delete_user(uname)
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.get("/auth/me").json()["pc_access"] is False
    assert guest.get("/cv").status_code == 403


def test_generated_files_are_encrypted_and_private():
    from media import media_store
    me = main.auth_sessions.get_session(_test_token)
    name = media_store.save(b"\x89PNG-contenido-privado", ".png", me["dek"])
    enc = media_store.media_dir() / (name + ".enc")
    assert b"contenido-privado" not in enc.read_bytes()
    got = client.get(f"/media/{name}")
    assert got.status_code == 200 and got.content == b"\x89PNG-contenido-privado"
    assert got.headers["content-type"] == "image/png"
    part = client.get(f"/media/{name}", headers={"Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"\x89PNG"
    uname, other = _other_user_client()
    try:
        assert other.get(f"/media/{name}").status_code == 404
    finally:
        users_module.delete_user(uname)
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.get(f"/media/{name}").status_code == 404
    assert client.get("/media/..%2F..%2Fusers.db").status_code == 404
    assert client.get("/outputs/loquesea.png").status_code == 404


def test_login_is_locked_after_repeated_failures():
    from api import rate_limit
    uname = f"_test_lock_{uuid.uuid4().hex[:8]}"
    anon = TestClient(app)
    try:
        for _ in range(rate_limit.login.max_failures):
            assert anon.post("/auth/login", json={"username": uname, "password": "mal"}).status_code == 401
        assert anon.post("/auth/login", json={"username": uname, "password": "mal"}).status_code == 429
    finally:
        rate_limit.login.succeed(uname.lower())


def test_my_apps_routes_after_moving_them_out_of_main():
    for path in ("/jobs", "/shopping", "/deep", "/jobs/status", "/shopping/status", "/deep/status"):
        assert client.get(path).status_code == 200, path
    with patch.object(main.routes_apps.deep_search, "start") as mock_start:
        assert client.post("/deep/search", json={"consulta": "casas en Valladolid"}).json() == {"ok": True}
    assert mock_start.call_args.args[3] == "casas en Valladolid"
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.get("/deep").status_code == 403


def test_a_late_chat_load_is_unloaded_when_already_in_image_mode():
    release = threading.Event()

    def slow_preload(model, *a, **k):
        release.wait(5)

    with patch.object(main.ollama, "preload", side_effect=slow_preload),          patch.object(main.ollama, "running_models", return_value=["qwen3:8b"]),          patch.object(main.ollama, "unload") as mock_unload,          patch.object(main.opencode_client, "busy_session_ids", return_value=[]),          patch.object(main.comfyui_client, "free_memory"),          patch.object(main.comfyui_client, "user_queue", return_value=(0, 0)),          patch.object(main.image_agent, "generate", return_value=b"png"):
        client.post("/models/prepare", json={"mode": "chat"})
        client.post("/models/prepare", json={"mode": "image"})
        _wait_prepare_done()
        mock_unload.reset_mock()
        release.set()
        for _ in range(50):
            if mock_unload.called:
                break
            time.sleep(0.05)
    assert mock_unload.called, "lo que cargo el chat tarde tiene que salir de la GPU"
    assert client.get("/models/prepare").json()["mode"] == "image"


def test_password_recovery_does_not_reveal_which_users_exist():
    anon = TestClient(app)
    q1 = anon.get("/auth/security-question/no_existe_nadie_asi").json()["security_question"]
    assert q1 == anon.get("/auth/security-question/No_Existe_Nadie_Asi").json()["security_question"]
    resp = anon.post("/auth/reset-password", json={"username": "no_existe_nadie_asi",
                                                   "security_answer": "x", "new_password": "otra-larga-1"})
    assert resp.status_code == 400 and resp.json()["detail"] == "Respuesta incorrecta."
    from api import rate_limit
    rate_limit.password_reset.succeed("no_existe_nadie_asi")


def test_agent_tasks_belong_to_whoever_started_them():
    uname, other = _other_user_client()
    try:
        client.put(f"/auth/users/{uname}/pc_access", json={"allowed": True})
        with patch.object(main.opencode_client, "start_task", return_value="ses_mia_123"):
            assert client.post("/agent/tasks", json={"task": "x", "confirmed": True}).json()["session_id"] == "ses_mia_123"
        tasks = [{"session_id": "ses_mia_123", "title": "mia", "updated": 1, "status": "idle"}]
        with patch.object(main.opencode_client, "list_tasks", return_value=tasks), \
             patch.object(main.opencode_client, "get_task_view", return_value={"status": "idle"}), \
             patch.object(main.opencode_client, "continue_task") as mock_continue, \
             patch.object(main.opencode_client, "request_session", return_value="ses_mia_123"), \
             patch.object(main.opencode_client, "reply_permission") as mock_perm:
            assert [t["session_id"] for t in client.get("/agent/tasks").json()] == ["ses_mia_123"]
            assert other.get("/agent/tasks").json() == []
            assert other.get("/agent/tasks/ses_mia_123").status_code == 404
            assert other.post("/agent/tasks/ses_mia_123/message", json={"text": "borra todo"}).status_code == 404
            assert other.post("/agent/permissions/per_1", json={"reply": "always"}).status_code == 404
            assert not mock_continue.called and not mock_perm.called
            assert client.post("/agent/permissions/per_1", json={"reply": "once"}).status_code == 200
    finally:
        users_module.delete_user(uname)


def test_without_voice_libraries_the_rest_of_chati_still_works():
    with patch.object(main.voice_agent, "transcribe", side_effect=RuntimeError("La voz no esta disponible")):
        resp = client.post("/voice_chat", files={"audio": ("a.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 503 and "voz" in resp.json()["detail"]
    with patch.object(main.voice_agent, "speak", side_effect=RuntimeError("La voz no esta disponible")):
        assert client.post("/speak", data={"text": "hola"}).status_code == 503


def test_generations_are_recorded_under_whoever_asked():
    seen = []

    def fake_generate(*args, **kwargs):
        seen.append(main.comfyui_client.current_owner.get())
        return b"png"
    with patch.object(main.prompt_writer, "image_prompt", return_value=("A dog.", (1024, 1024))), \
         patch.object(main.image_agent, "generate", side_effect=fake_generate):
        client.post("/chat", json={"message": "un perro", "agent": "image"})
        guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
        guest.post("/chat", json={"message": "un gato", "agent": "image"})
    assert len(seen) == 2 and all(seen) and seen[0] != seen[1]
    assert seen[1].startswith("invitado:")


def test_upscaling_an_already_huge_image_is_refused_before_reaching_comfyui():
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), (1, 2, 3)).save(buf, format="PNG")
    with patch.object(main.image_agent, "upscale") as mock_upscale:
        resp = client.post("/image/upscale", files={"image": ("grande.png", buf.getvalue(), "image/png")})
    assert "muy grande" in resp.json()["response"]
    mock_upscale.assert_not_called()


def test_all_conversations_of_the_user_can_be_deleted_at_once():
    with patch.object(main.memory, "list_sessions", return_value=[{"session_id": "a"}, {"session_id": "b"}]) as ls, \
         patch.object(routes_sessions, "_delete_conversation") as delete:
        resp = client.delete("/sessions")
    assert resp.status_code == 200 and resp.json() == {"ok": True, "deleted": 2}
    assert ls.call_args.kwargs["user_id"]
    assert [c.args[1] for c in delete.call_args_list] == ["a", "b"]


def test_first_task_in_a_project_gets_the_card_after_the_undo_copy(tmp_path):
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    with patch.object(main.opencode_client, "start_task", return_value="ses_ficha") as start, \
         patch.object(agent_watch, "start_code_watch"):
        client.post("/agent/tasks", json={"task": "añade un saludo", "project": str(tmp_path)})
    assert (tmp_path / "AGENTS.md").exists()
    assert "Chati ha creado uno" in start.call_args.args[1]
    assert checkpoints.undo("ses_ficha")["ok"]
    assert not (tmp_path / "AGENTS.md").exists()


def test_retry_cuts_the_stuck_answer_and_continues_the_same_task():
    with patch.object(routes_agent, "owns_task", return_value=True), \
         patch.object(main.opencode_client, "abort") as abort, \
         patch.object(main.opencode_client, "continue_task") as cont, \
         patch.object(main.time, "sleep"):
        agent_watch.stalled["ses_r"] = 1.0
        assert client.post("/agent/tasks/ses_r/retry").json() == {"ok": True}
    assert abort.call_args.args[1:] == ("ses_r",)
    assert cont.call_args.args[1] == "ses_r" and "colgada" in cont.call_args.args[2]
    assert "ses_r" not in agent_watch.stalled


def test_clear_agent_history_deletes_only_own_finished_tasks():
    tasks = [{"session_id": s, "title": s, "updated": 1, "status": st}
             for s, st in (("hecha", "idle"), ("trabajando", "busy"), ("esperando", "idle"), ("ajena", "idle"))]
    with patch.object(main.opencode_client, "list_tasks", return_value=tasks), \
         patch.object(routes_agent, "owns_task", side_effect=lambda req, sid: sid != "ajena"), \
         patch.object(main.opencode_client, "busy_session_ids", return_value=["trabajando"]), \
         patch.object(main.opencode_client, "waiting_sessions", return_value={"esperando": "permission"}), \
         patch.object(main.opencode_client, "delete_task") as delete:
        r = client.post("/agent/tasks/clear").json()
    assert [c.args[1] for c in delete.call_args_list] == ["hecha"]
    assert r == {"borradas": 1, "en_marcha": 2}


def test_push_key_is_public_for_the_launcher():
    anon = TestClient(app)
    r = anon.get("/push/key", headers={"Origin": "https://serberar.github.io"})
    assert r.status_code == 200 and len(r.json()["key"]) > 80
    assert r.headers["access-control-allow-origin"] == "https://serberar.github.io"
    assert "access-control-allow-origin" not in anon.get("/push/key", headers={"Origin": "https://otro.com"}).headers


def test_push_aviso_sends_to_own_devices_and_limits_length():
    with patch.object(main.push, "notify") as notify:
        assert client.post("/push/aviso", json={"title": "Bateria", "body": "Baja de 20 a 17"}).status_code == 200
        assert notify.call_args.args[1:3] == ("Bateria", "Baja de 20 a 17")
        assert client.post("/push/aviso", json={"title": "x" * 81, "body": ""}).status_code == 422
    guest = TestClient(app, headers={"X-Session-Token": client.post("/auth/guest").json()["token"]})
    assert guest.post("/push/aviso", json={"title": "a", "body": "b"}).status_code == 403


def test_a_routine_starts_a_task_and_saving_one_answers_directly(tmp_path):
    from coding import routines
    with patch.object(routines, "ROUTINES_DIR", tmp_path / "rutinas"), \
         patch.object(main.opencode_client, "start_task", return_value="ses_r") as start, \
         patch.object(agent_watch, "start_code_watch"):
        reply = client.post("/agent/tasks", json={"task": "/rutina sube: pasa los tests", "project": str(tmp_path)})
        assert reply.json()["mensaje"].startswith("Rutina guardada") and not start.called
        assert "/sube" in client.post("/agent/tasks", json={"task": "/rutinas"}).json()["mensaje"]
        client.post("/agent/tasks", json={"task": "/revisa", "project": str(tmp_path)})
    assert "SIN CAMBIAR NADA" in start.call_args.args[1] and start.call_args.args[2] == "chati-code-plan"


def test_code_tasks_can_wait_for_the_night_and_run_unattended(tmp_path):
    with patch.object(main.threading, "Thread"):
        r = client.post("/agent/tasks", json={"task": "esta noche revisa el proyecto y arregla lo que falle",
                                              "project": str(tmp_path), "continuar": "ses_vieja"}).json()
    assert "esta noche" in r["mensaje"] and len(night_queue._queue) == 1
    item = night_queue._queue.pop()
    with patch.object(main.opencode_client, "start_task", return_value="ses_n") as start, \
         patch.object(agent_watch, "start_code_watch") as watch, \
         patch.object(main.time, "sleep"), patch.object(main.push, "notify") as notify:
        night_queue._task(item)
    assert start.call_args.args[1].startswith("revisa el proyecto y arregla lo que falle")
    assert watch.call_args.args[3] is True
    assert "revisa el proyecto" in notify.call_args.args[2]
