import subprocess
import sys

from coding import agent_tools


def test_every_template_is_valid_python_and_is_not_overwritten(tmp_path):
    for kind in agent_tools.TEMPLATES:
        assert agent_tools.make_from_template(kind, str(tmp_path), f"prueba_{kind}").startswith("Creado")
        compile((tmp_path / f"prueba_{kind}.py").read_text(encoding="utf-8"), kind, "exec")
    assert "__NOMBRE__" not in (tmp_path / "prueba_ventana.py").read_text(encoding="utf-8")
    assert agent_tools.make_from_template("ventana", str(tmp_path), "prueba_ventana").startswith("Ya existe")
    assert "Hay:" in agent_tools.make_from_template("juego", str(tmp_path), "x")


def test_data_template_reads_spanish_numbers_and_menu_runs(tmp_path):
    agent_tools.make_from_template("leer_datos", str(tmp_path), "resumen")
    (tmp_path / "f.csv").write_text("cliente;importe\nA;12,50\nB;1.200,00\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(tmp_path / "resumen.py"), str(tmp_path / "f.csv"), "importe"],
                         capture_output=True, text=True, timeout=60, check=False)
    assert "Total: 1212.50" in out.stdout, out.stderr
    agent_tools.make_from_template("menu", str(tmp_path), "agenda")
    out = subprocess.run([sys.executable, str(tmp_path / "agenda.py")], input="2\nhola\n1\n4\n",
                         capture_output=True, text=True, timeout=60, check=False)
    assert "1 hola" in out.stdout, out.stderr


def test_scheduled_task_template_logs_next_to_itself_even_from_another_folder(tmp_path):
    agent_tools.make_from_template("tarea_programada", str(tmp_path), "limpieza")
    out = subprocess.run([sys.executable, str(tmp_path / "limpieza.py")], capture_output=True, text=True,
                         timeout=60, check=False, cwd=tmp_path.parent)
    assert out.returncode == 0, out.stderr
    assert "Hecho:" in (tmp_path / "limpieza.py.log").read_text(encoding="utf-8")


def test_fastapi_template_creates_and_reads_items(tmp_path):
    import importlib.util

    from fastapi.testclient import TestClient
    agent_tools.make_from_template("fastapi", str(tmp_path), "tienda_api")
    spec = importlib.util.spec_from_file_location("tienda_api", tmp_path / "tienda_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = TestClient(module.app)
    assert client.post("/elementos", json={"nombre": "pan", "precio": 1.2}).json()["id"] == 1
    assert client.get("/elementos/1").json()["nombre"] == "pan"
    assert client.get("/elementos/9").status_code == 404
