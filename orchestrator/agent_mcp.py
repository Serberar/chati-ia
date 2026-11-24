import json
import sys
import traceback

from coding import agent_tools as t

PROTOCOL = "2024-11-05"


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


_STR = {"type": "string"}
TOOLS = [
    {"name": "memoria_guardar", "fn": lambda a: t.memory_save(a["titulo"], a["contenido"], a.get("tipo", "proyecto"),
                                                              a.get("proyecto", ""), a.get("resumen", "")),
     "description": "Guarda algo que convenga recordar en futuras conversaciones: preferencias del usuario, "
                    "como se compila o se prueba un proyecto, decisiones tomadas, errores ya resueltos y su causa. "
                    "Si ya hay un recuerdo con ese titulo, lo actualiza. No guardes lo que ya esta en el codigo o "
                    "en git, ni secretos (contraseñas, claves).",
     "inputSchema": _schema({"titulo": _STR, "contenido": _STR,
                             "tipo": {"type": "string", "enum": list(t.MEMORY_TYPES)},
                             "proyecto": {"type": "string", "description": "Carpeta del proyecto, si es de uno"},
                             "resumen": {"type": "string", "description": "Una linea para el indice"}},
                            ["titulo", "contenido"])},
    {"name": "memoria_leer", "fn": lambda a: t.memory_read(a["nombre"]),
     "description": "Lee entero un recuerdo del indice de memoria (por su nombre).",
     "inputSchema": _schema({"nombre": _STR}, ["nombre"])},
    {"name": "memoria_buscar", "fn": lambda a: t.memory_search(a["texto"]),
     "description": "Busca en la memoria recuerdos sobre un tema.",
     "inputSchema": _schema({"texto": _STR}, ["texto"])},
    {"name": "memoria_borrar", "fn": lambda a: t.memory_delete(a["nombre"]),
     "description": "Borra un recuerdo que ya no es cierto o que el usuario pide olvidar.",
     "inputSchema": _schema({"nombre": _STR}, ["nombre"])},
    {"name": "buscar_web", "fn": lambda a: t.web_search(a["consulta"], int(a.get("cantidad", 8))),
     "description": "Busca en internet (documentacion, errores, ejemplos, novedades). Devuelve titulo, direccion "
                    "y resumen de cada resultado; para leer uno, usa leer_web.",
     "inputSchema": _schema({"consulta": _STR, "cantidad": {"type": "integer"}}, ["consulta"])},
    {"name": "leer_web", "fn": lambda a: t.web_read(a["url"], int(a.get("desde", 0))),
     "description": "Lee el texto de una pagina publica de internet (documentacion, issues, articulos). Si es "
                    "larga, dice como pedir el trozo siguiente.",
     "inputSchema": _schema({"url": _STR, "desde": {"type": "integer"}}, ["url"])},
    {"name": "info_paquete", "fn": lambda a: t.package_info(a["nombre"], a.get("ecosistema", "python")),
     "description": "Comprueba si existe una libreria (PyPI o npm) y da su ultima version, fecha, descripcion y "
                    "licencia. Usala SIEMPRE antes de proponer o instalar una libreria que no este ya en el "
                    "proyecto: no te inventes librerias.",
     "inputSchema": _schema({"nombre": _STR, "ecosistema": {"type": "string", "enum": ["python", "npm"]}},
                            ["nombre"])},
    {"name": "docs", "fn": lambda a: t.library_docs(a["nombre"], a.get("carpeta", "")),
     "description": "Documentacion de una funcion, clase o modulo de Python tal como esta en la version INSTALADA "
                    "en el proyecto (sin internet): parametros exactos y para que sirve. Usala antes de usar una "
                    "funcion de la que no estes seguro (pandas.DataFrame.merge, openpyxl.load_workbook, "
                    "tkinter.ttk.Treeview...). Si no existe, dice los nombres parecidos que si existen.",
     "inputSchema": _schema({"nombre": {"type": "string", "description": "Nombre completo con puntos"},
                             "carpeta": {"type": "string", "description": "Carpeta del proyecto (usa su venv)"}},
                            ["nombre"])},
    {"name": "revisar_actualizaciones", "fn": lambda a: t.check_updates(a["carpeta"]),
     "description": "Compara las dependencias de un proyecto (requirements*.txt, pyproject.toml, package.json) con "
                    "la ultima version publicada de cada una.",
     "inputSchema": _schema({"carpeta": _STR}, ["carpeta"])},
    {"name": "buscar_codigo", "fn": lambda a: t.code_search(a["carpeta"], a["consulta"], int(a.get("cantidad", 6))),
     "description": "Busca en el codigo de un proyecto por SIGNIFICADO, no por palabras exactas (\"donde se valida "
                    "el login\", \"que calcula los descuentos\"). Devuelve archivo, lineas y el principio de cada "
                    "trozo. Usala para encontrar donde esta algo antes de abrir archivos; para un nombre exacto, grep "
                    "es mejor. La primera vez en un proyecto grande tarda unos minutos en prepararse.",
     "inputSchema": _schema({"carpeta": _STR, "consulta": _STR, "cantidad": {"type": "integer"}},
                            ["carpeta", "consulta"])},
    {"name": "ver_web", "fn": lambda a: t.look_at_local_page(a["url"], a.get("pregunta", "")),
     "description": "Abre en un navegador la web que estas desarrollando (solo de este ordenador: "
                    "http://localhost:PUERTO), hace una captura y te dice lo que se ve y los errores de la consola de "
                    "JavaScript. Usala para comprobar como queda una pagina o por que falla. El servidor de desarrollo "
                    "tiene que estar arrancado. Tarda 1-2 minutos.",
     "inputSchema": _schema({"url": _STR, "pregunta": {"type": "string", "description": "Algo concreto que mirar"}},
                            ["url"])},
    {"name": "ver_imagen", "fn": lambda a: t.look_at_image(a["ruta"], a.get("pregunta", "")),
     "description": "Describe una imagen o captura de pantalla (la ruta de un archivo), por ejemplo una que te pase "
                    "el usuario para enseñarte un error. Tarda 1-2 minutos.",
     "inputSchema": _schema({"ruta": _STR, "pregunta": {"type": "string"}}, ["ruta"])},
    {"name": "leer_repo", "fn": lambda a: t.read_repo(a["url"]),
     "description": "Descarga (o actualiza) un repositorio git publico, por ejemplo de GitHub, y dice en que "
                    "carpeta queda, sus carpetas y el README. Despues se lee con read, grep y glob.",
     "inputSchema": _schema({"url": _STR}, ["url"])},
    {"name": "ver_nombre", "fn": lambda a: t.find_symbol(a["carpeta"], a["viejo"]),
     "description": "Antes de renombrar: dice en que archivos y lineas aparece un nombre (funcion, clase, variable) "
                    "como palabra completa en todo el proyecto. No cambia nada.",
     "inputSchema": _schema({"carpeta": _STR, "viejo": _STR}, ["carpeta", "viejo"])},
    {"name": "renombrar", "fn": lambda a: t.rename_symbol(a["carpeta"], a["viejo"], a["nuevo"], apply=True),
     "description": "Renombra una funcion, clase o variable en TODO el proyecto de una vez (solo palabras completas, "
                    "sin tocar venv ni node_modules). Mira antes con ver_nombre. Usala en vez de bash o de editar "
                    "archivo por archivo.",
     "inputSchema": _schema({"carpeta": _STR, "viejo": _STR, "nuevo": _STR}, ["carpeta", "viejo", "nuevo"])},
    {"name": "editar_bloque", "fn": lambda a: t.replace_block(a["ruta"], a["nombre"], a["codigo"]),
     "description": "Sustituye ENTERA una funcion o clase de un archivo .py por su nombre (\"precio_final\", o "
                    "\"Carrito.total\" para un metodo), con el codigo nuevo completo (def/class incluido). Mas "
                    "seguro que edit para cambiar una funcion entera: no hace falta copiar el texto viejo exacto. Si "
                    "el resultado no es Python valido, no cambia nada.",
     "inputSchema": _schema({"ruta": _STR, "nombre": _STR, "codigo": _STR}, ["ruta", "nombre", "codigo"])},
    {"name": "entorno_python", "fn": lambda a: t.python_env(a["carpeta"], a.get("paquetes") or []),
     "description": "Crea (si no lo tiene) el entorno de Python del proyecto, carpeta/.venv, e instala en el los "
                    "paquetes que hagan falta. Dice que python usar para ejecutarlo. Usala en vez de pip install, que "
                    "instalaria en el Python del sistema que usan todos los programas del usuario.",
     "inputSchema": _schema({"carpeta": _STR, "paquetes": {"type": "array", "items": _STR}}, ["carpeta"])},
    {"name": "mapa_proyecto", "fn": lambda a: t.project_map(a["carpeta"]),
     "description": "Mapa del proyecto: cada archivo de codigo con sus clases, metodos y funciones (y cuantas lineas "
                    "tiene). Usalo al empezar en un proyecto que no conoces para saber donde mirar sin leer archivos "
                    "enteros.",
     "inputSchema": _schema({"carpeta": _STR}, ["carpeta"])},
    {"name": "plantilla", "fn": lambda a: t.make_from_template(a["tipo"], a["carpeta"], a["nombre"]),
     "description": "Crea un programa NUEVO a partir de una plantilla que ya funciona, para adaptarla despues con "
                    "edit: ventana (tkinter), menu (consola con datos en JSON), flask (web), fastapi (API), "
                    "tarea_programada (script para el Programador de tareas), leer_datos (CSV o Excel). Usala en vez de escribir un programa entero de cero. No sobrescribe archivos.",
     "inputSchema": _schema({"tipo": {"type": "string", "enum": ["ventana", "menu", "flask", "fastapi", "tarea_programada", "leer_datos"]},
                             "carpeta": _STR, "nombre": {"type": "string", "description": "Sin .py"}},
                            ["tipo", "carpeta", "nombre"])},
    {"name": "definicion", "fn": lambda a: t.find_definition(a["carpeta"], a["nombre"]),
     "description": "Donde esta definida una funcion, clase o variable del proyecto, con su firma (parametros) y "
                    "su descripcion. Como 'ir a la definicion' de un editor de codigo.",
     "inputSchema": _schema({"carpeta": _STR, "nombre": _STR}, ["carpeta", "nombre"])},
    {"name": "usos", "fn": lambda a: t.find_usages(a["carpeta"], a["nombre"]),
     "description": "En que archivos y lineas se usa una funcion, clase o variable (imports incluidos). Usala antes "
                    "de cambiar algo para saber a que afecta.",
     "inputSchema": _schema({"carpeta": _STR, "nombre": _STR}, ["carpeta", "nombre"])},
    {"name": "usar_web",
     "fn": lambda a: t.use_local_page(a["url"], a.get("pasos") or [], a.get("pregunta", "")),
     "description": "Usa la web que estas desarrollando (solo http://localhost) como lo haria una persona y dice que "
                    "pasa: pasos en orden, cada uno {accion, en, texto/opcion/tecla/ms/url}. Acciones: clic (en: texto "
                    "del boton o enlace), escribir (en: etiqueta o texto de ayuda del campo, texto), elegir (en: el "
                    "desplegable, opcion), tecla (tecla: Enter...), esperar (ms), ir (url). Devuelve el resultado de "
                    "cada paso, errores de la consola, botones y campos visibles y el texto de la pagina. Sin pasos, "
                    "solo la abre y dice que hay. Con pregunta, ademas describe la captura (1-2 min).",
     "inputSchema": _schema({"url": _STR,
                             "pasos": {"type": "array", "items": {"type": "object"},
                                       "description": "[{\"accion\": \"escribir\", \"en\": \"Nombre\", "
                                                      "\"texto\": \"Ana\"}, {\"accion\": \"clic\", "
                                                      "\"en\": \"Enviar\"}]"},
                             "pregunta": {"type": "string"}}, ["url"])},
    {"name": "github", "fn": lambda a: t.github_read(a["repo"], a.get("que", "issues"), a.get("numero")),
     "description": "Lee de un repositorio de GitHub (usuario/proyecto): issues, prs, issue o pr con numero (con "
                    "comentarios y, en un pr, sus cambios), commits, acciones (estado de los tests en GitHub) o "
                    "readme. Solo leer.",
     "inputSchema": _schema({"repo": _STR, "que": {"type": "string",
                                                    "enum": ["issues", "prs", "issue", "pr", "commits", "acciones",
                                                             "readme"]},
                             "numero": {"type": "integer"}}, ["repo"])},
    {"name": "consultar_bd", "fn": lambda a: t.query_database(a["origen"], a.get("sql", "")),
     "description": "Consulta de SOLO LECTURA a una base de datos de este ordenador: un archivo SQLite (ruta al "
                    ".db/.sqlite) o SQL Server local (\"sqlserver:NOMBRE_BASE\"). Sin sql, lista las tablas. Solo "
                    "SELECT/WITH (y PRAGMA en SQLite); para cambiar datos, hazlo desde el codigo del proyecto.",
     "inputSchema": _schema({"origen": _STR, "sql": {"type": "string"}}, ["origen"])},
    {"name": "lanzar_programa", "fn": lambda a: t.start_program(a["carpeta"], a["comando"], int(a.get("espera", 8))),
     "description": "Arranca un programa que se queda abierto (un servidor web, una app, npm run dev...) en la carpeta "
                    "del proyecto, SIN esperar a que termine, y devuelve lo que escribe en los primeros segundos. "
                    "Usalo tambien para lo que tarda mas de 1-2 minutos (pip install grande, npm install, "
                    "compilar, tests muy largos): sigue con otra cosa y mira despues con ver_salida si ha "
                    "terminado y con que codigo. Para comandos cortos usa bash. Paralo con parar_programa al terminar.",
     "inputSchema": _schema({"carpeta": _STR, "comando": _STR,
                             "espera": {"type": "integer", "description": "Segundos a esperar antes de leer (8)"}},
                            ["carpeta", "comando"])},
    {"name": "ver_salida", "fn": lambda a: t.program_output(a["id"], int(a.get("lineas", 80))),
     "description": "Lo ultimo que ha escrito un programa arrancado con lanzar_programa (errores incluidos) y si "
                    "sigue en marcha.",
     "inputSchema": _schema({"id": _STR, "lineas": {"type": "integer"}}, ["id"])},
    {"name": "parar_programa", "fn": lambda a: t.stop_program(a["id"]),
     "description": "Para un programa arrancado con lanzar_programa.",
     "inputSchema": _schema({"id": _STR}, ["id"])},
    {"name": "probar_programa", "fn": lambda a: t.try_program(a["ruta"], int(a.get("segundos", 6))),
     "description": "Abre un programa (.py, .pyw o .exe) como si el usuario le diera doble clic, espera unos "
                    "segundos y dice si se ha cerrado con un error (y cual), si abre una ventana o si se queda sin "
                    "ventana; despues lo cierra. Usalo SIEMPRE para comprobar si un programa funciona, en vez de "
                    "lanzarlo con bash (con bash se queda esperando a que alguien cierre la ventana).",
     "inputSchema": _schema({"ruta": _STR, "segundos": {"type": "integer", "description": "Espera (6)"}},
                            ["ruta"])},
    {"name": "ver_ventana", "fn": lambda a: t.look_at_program(a["ruta"], a.get("pregunta", ""),
                                                                int(a.get("segundos", 6))),
     "description": "Como probar_programa, pero ademas hace una captura de la ventana y te dice lo que se ve (textos, "
                    "botones, numeros, errores). Usala para comprobar que la ventana muestra lo que debe, no solo que "
                    "abre. Tarda 1-2 minutos.",
     "inputSchema": _schema({"ruta": _STR, "pregunta": {"type": "string", "description": "Algo concreto que mirar"},
                             "segundos": {"type": "integer"}}, ["ruta"])},
    {"name": "compilar_exe", "fn": lambda a: t.build_exe(a["script"], bool(a.get("administrador", False))),
     "description": "Crea el .exe de un programa .py con PyInstaller (con ventana o de consola, segun el codigo), "
                    "lo pone en la carpeta del .py sustituyendo el .exe que hubiera, y lo prueba. Usalo en vez de "
                    "lanzar pyinstaller con bash. administrador=true si necesita permisos (p.ej. cambia el archivo "
                    "hosts): Windows los pedira al abrirlo.",
     "inputSchema": _schema({"script": _STR, "administrador": {"type": "boolean"}}, ["script"])},
]
_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def handle(msg: dict) -> dict | None:
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "chati", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [{k: v for k, v in tool.items() if k != "fn"} for tool in TOOLS]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        tool = _BY_NAME.get(params.get("name"))
        if tool is None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32602, "message": f"Herramienta desconocida: {params.get('name')}"}}
        try:
            text, failed = tool["fn"](params.get("arguments") or {}), False
        except KeyError as exc:
            text, failed = f"Falta el parametro {exc}.", True
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            text, failed = f"Error: {exc}", True
        result = {"content": [{"type": "text", "text": text}], "isError": failed}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Metodo no soportado: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON no valido"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    finally:
        t.stop_all_programs()
