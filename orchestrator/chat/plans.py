VALID_STATES = {"pendiente", "en_progreso", "hecho"}
MAX_STEPS = 30
MAX_STEP_CHARS = 300

_plans: dict[str, list[dict]] = {}


def set_plan(session_id: str, pasos: list[dict]) -> None:
    limpios = []
    for p in pasos[:MAX_STEPS]:
        if not isinstance(p, dict):
            continue
        texto = str(p.get("texto", "")).strip()[:MAX_STEP_CHARS]
        estado = p.get("estado", "pendiente")
        if estado not in VALID_STATES:
            estado = "pendiente"
        if texto:
            limpios.append({"texto": texto, "estado": estado})
    _plans[session_id] = limpios


def get_plan(session_id: str) -> list[dict]:
    return _plans.get(session_id, [])
