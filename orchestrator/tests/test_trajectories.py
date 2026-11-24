import json
import time
from unittest.mock import patch

from coding import trajectories


def test_each_finished_task_is_saved_whole_and_old_ones_are_pruned(tmp_path):
    view = {"session_id": "ses_1", "task": "arregla x.py", "error": None,
            "steps": [{"kind": "tool", "tool": "bash", "detail": "python x.py"}, {"kind": "text", "text": "Hecho"}]}
    with patch.object(trajectories, "TRAJECTORIES_DIR", tmp_path), patch.object(trajectories, "MAX_FILES", 2), \
         patch.object(trajectories, "INDEX_FILE", tmp_path / "indice.jsonl"):
        for name in ("20200101-000000_a.json", "20200101-000001_b.json"):
            (tmp_path / name).write_text("{}", encoding="utf-8")
        trajectories.save(view, "agente", time.time() - 90, "✓ Lo ha probado")
        files = sorted(p.name for p in tmp_path.glob("*.json"))
        assert "arregla x.py" in (tmp_path / "indice.jsonl").read_text(encoding="utf-8")
    assert len(files) == 2 and files[0] == "20200101-000001_b.json"
    saved = json.loads((tmp_path / files[1]).read_text(encoding="utf-8"))
    assert saved["tarea"] == "arregla x.py" and saved["herramientas"] == 1 and 89 <= saved["segundos"] <= 92


def test_estimate_uses_similar_past_tasks_of_the_same_mode(tmp_path):
    rows = [{"modo": "agente", "tarea": "el contador con ventana no suma al pulsar el boton", "segundos": s,
             "error": None, "verificacion": v} for s, v in ((240, ""), (360, "✗ no probado"), (300, ""))]
    rows.append({"modo": "codigo", "tarea": "el contador con ventana no suma al pulsar el boton", "segundos": 9000})
    index = tmp_path / "i.jsonl"
    index.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    with patch.object(trajectories, "INDEX_FILE", index):
        assert trajectories.estimate("mi contador de ventana no suma con el boton", "agente") == \
            "tareas parecidas: ~5 min, 2 de 3 bien"
        assert trajectories.estimate("ordena las fotos por fecha", "agente") == ""
