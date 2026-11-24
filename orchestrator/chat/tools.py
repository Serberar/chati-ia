import datetime
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]

PYTHON_EXEC_TIMEOUT = 10
PYTHON_OUTPUT_LIMIT = 4000

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "fecha_actual",
            "description": (
                "Devuelve la fecha y hora actual real de este ordenador. Usala "
                "siempre que necesites saber que dia, mes o año es, o calcular "
                "cuanto falta o ha pasado desde una fecha, en vez de adivinarlo."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_memoria",
            "description": (
                "Busca en la memoria a largo plazo de conversaciones anteriores y "
                "en los documentos que el usuario ha subido. Usala cuando la "
                "pregunta pueda depender de algo que el usuario te haya contado "
                "antes, o de un documento suyo, y no lo tengas ya en el historial "
                "reciente de este chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {"type": "string", "description": "que buscar, en pocas palabras"},
                },
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_documentos",
            "description": "Lista los nombres de los documentos que el usuario ha subido a la base de conocimiento.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegar_a_agente_de_codigo",
            "description": (
                "Envia una tarea al agente de codigo (OpenCode), que puede leer y "
                "editar archivos reales del proyecto, ejecutar comandos, etc. "
                "Usala SOLO cuando el usuario pida explicitamente crear, modificar "
                "o revisar archivos de un proyecto real - nunca para explicar codigo "
                "o escribir un fragmento de ejemplo, para eso responde tu directamente. "
                "OJO: tarda varios minutos en completarse y no devuelve el resultado "
                "aqui mismo - dile al usuario que se la has pasado al agente y que "
                "vera su progreso justo debajo, no inventes que ya esta hecho."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tarea": {"type": "string", "description": "descripcion clara y completa de que hacer"},
                },
                "required": ["tarea"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_plan",
            "description": (
                "Crea o actualiza la lista de pasos visible para el usuario, para "
                "tareas de mas de 2-3 pasos. Llamala con la lista COMPLETA "
                "actualizada cada vez (no solo el paso que cambia) para que el "
                "usuario vea el progreso real. No la uses para tareas triviales "
                "de un solo paso."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pasos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "texto": {"type": "string"},
                                "estado": {"type": "string", "enum": ["pendiente", "en_progreso", "hecho"]},
                            },
                            "required": ["texto", "estado"],
                        },
                    },
                },
                "required": ["pasos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_archivo",
            "description": (
                "Lee el contenido de un archivo de texto real del usuario. Solo "
                "funciona dentro de su Escritorio o Documentos - si la ruta cae "
                "fuera, se rechaza. Usala cuando el usuario pida leer, resumir o "
                "analizar un archivo suyo concreto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "ruta completa del archivo"},
                },
                "required": ["ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_carpeta",
            "description": (
                "Lista los archivos y subcarpetas de una carpeta del usuario "
                "(solo dentro de su Escritorio o Documentos). Usala para ver que "
                "hay antes de pedir leer_archivo, si no sabes el nombre exacto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "ruta completa de la carpeta"},
                },
                "required": ["ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ejecutar_python",
            "description": (
                "Ejecuta codigo Python de verdad para comprobar un calculo, operacion "
                "matematica, fecha o procesamiento de datos, en vez de calcularlo de "
                "memoria. Usala siempre que la respuesta dependa de un calculo numerico "
                "concreto (sumas, multiplicaciones, porcentajes, estadisticas, "
                "conversiones de unidades) para no arriesgarte a un error de calculo. "
                "El codigo debe usar print() para mostrar el resultado, si no no se ve nada. "
                "Solo biblioteca estandar (math, statistics, fractions, decimal, datetime, "
                "json, re...): sin numpy, sin red y sin archivos del ordenador."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string", "description": "codigo Python a ejecutar; usa print() para el resultado"},
                },
                "required": ["codigo"],
            },
        },
    },
]


def fecha_actual() -> str:
    now = datetime.datetime.now()
    return f"Hoy es {DIAS[now.weekday()]}, {now.day} de {MESES[now.month - 1]} de {now.year}. Hora: {now.strftime('%H:%M')}."


SANDBOX = Path(__file__).with_name("python_sandbox.py")


PYTHON_MEMORY_LIMIT = 512 * 1024 ** 2
_JOB_MEMORY_EXIT = 0xC0000017 - 2 ** 32


def _drain(pipe, buf: bytearray) -> None:
    while chunk := pipe.read(65536):
        if len(buf) < PYTHON_OUTPUT_LIMIT * 4:
            buf.extend(chunk[:PYTHON_OUTPUT_LIMIT * 4 - len(buf)])


def _limit_memory(proc: subprocess.Popen):
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps",
                                                       "ReadBytes", "WriteBytes", "OtherBytes")]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [("Basic", _BasicLimits), ("Io", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        limits = _ExtendedLimits()
        limits.Basic.LimitFlags = 0x100 | 0x2000
        limits.ProcessMemoryLimit = PYTHON_MEMORY_LIMIT
        ok = kernel32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(limits), ctypes.sizeof(limits)) \
            and kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc._handle)))
        if not ok:
            kernel32.CloseHandle(wintypes.HANDLE(job))
            return None
        return job
    except (OSError, AttributeError, ValueError):
        return None


def _close_job(job) -> None:
    if job:
        import ctypes
        from ctypes import wintypes
        ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(job))


def ejecutar_python(codigo: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "snippet.py"
        script_path.write_text(codigo, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "PATH")}
        env.update(TEMP=tmpdir, TMP=tmpdir, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([sys.executable, "-I", "-B", str(SANDBOX), tmpdir], cwd=tmpdir, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        job = _limit_memory(proc)
        out, err = bytearray(), bytearray()
        readers = [threading.Thread(target=_drain, args=(pipe, buf), daemon=True)
                   for pipe, buf in ((proc.stdout, out), (proc.stderr, err))]
        for r in readers:
            r.start()
        try:
            returncode = proc.wait(timeout=PYTHON_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return f"El codigo tardo mas de {PYTHON_EXEC_TIMEOUT}s y se interrumpio (probable bucle infinito)."
        finally:
            for r in readers:
                r.join(timeout=5)
            _close_job(job)

        output = out.decode("utf-8", errors="replace")
        if returncode != 0:
            stderr = err.decode("utf-8", errors="replace")
            if returncode == _JOB_MEMORY_EXIT or "MemoryError" in stderr:
                stderr += f"\n(el codigo pidio mas de {PYTHON_MEMORY_LIMIT // 1024 ** 2} MB de memoria)"
            output += f"\n--- error (codigo {returncode}) ---\n{stderr}"
        if not output.strip():
            output = "(el codigo se ejecuto sin errores pero no imprimio nada - usa print() para ver resultados)"
        if len(output) > PYTHON_OUTPUT_LIMIT:
            output = output[:PYTHON_OUTPUT_LIMIT] + "\n... (salida truncada)"
        return output
