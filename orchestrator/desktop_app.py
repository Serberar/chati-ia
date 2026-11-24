import logging
import socket
import subprocess
import threading
import time
import webbrowser

import pystray
import requests
import webview
from PIL import Image

from infra.paths import CODE_ROOT, DATA_DIR

URL = "http://127.0.0.1:8899"
ICON_PATH = str(CODE_ROOT / "icono.ico")
START_SCRIPT = CODE_ROOT / "setup" / "start_all.ps1"
STOP_SCRIPT = CODE_ROOT / "setup" / "stop_chati.ps1"
INSTANCE_PORT = 8897
LOG_PATH = DATA_DIR / "arranque.log"
BACKEND_TIMEOUT = 180

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
  body {{ margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #14161a; color: #e8e9ec; font-family: "Segoe UI", system-ui, sans-serif; }}
  .box {{ text-align: center; max-width: 520px; padding: 24px; }}
  h1 {{ font-size: 22px; font-weight: 600; margin: 0 0 10px; }}
  p {{ color: #9099a8; font-size: 14px; line-height: 1.5; margin: 0; }}
  .spin {{ width: 34px; height: 34px; margin: 0 auto 22px; border-radius: 50%;
    border: 3px solid #333844; border-top-color: #5b8cff; animation: s 0.9s linear infinite; }}
  @keyframes s {{ to {{ transform: rotate(360deg); }} }}
</style></head><body><div class="box">{body}</div></body></html>"""

LOADING_HTML = _PAGE.format(body=(
    '<div class="spin"></div><h1>Arrancando Chati IA</h1>'
    "<p>Preparando los modelos locales. La primera vez tras encender el equipo "
    "puede tardar hasta un minuto.</p>"))


def _error_html(msg: str) -> str:
    return _PAGE.format(body=(
        f"<h1>No se pudo arrancar Chati IA</h1><p>{msg}</p>"
        f"<p style='margin-top:14px'>Detalles en: {LOG_PATH}</p>"))


def _backend_up() -> bool:
    try:
        return requests.get(f"{URL}/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


def _start_services() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8", errors="replace") as log:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", str(START_SCRIPT), "-Stay"],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


class _WebViewFailure(logging.Handler):

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.failed = threading.Event()

    def emit(self, record):
        if "WebView2 initialization failed" in record.getMessage():
            self.failed.set()


_webview_failure = _WebViewFailure()
logging.getLogger("pywebview").addHandler(_webview_failure)


def _fallback_to_browser(window) -> None:
    if not _webview_failure.failed.wait(timeout=BACKEND_TIMEOUT + 30):
        return
    deadline = time.time() + BACKEND_TIMEOUT
    while not _backend_up() and time.time() < deadline:
        time.sleep(2)
    webbrowser.open(URL)
    _quitting.set()
    window.destroy()


_quitting = threading.Event()


def _show(window) -> None:
    window.show()
    window.restore()


def _on_closing(window) -> bool:
    if _quitting.is_set():
        return True
    threading.Thread(target=window.hide, daemon=True).start()
    return False


def _quit(icon, window) -> None:
    _quitting.set()
    icon.stop()
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(STOP_SCRIPT),
         "-AiRoot", str(CODE_ROOT), "-All"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    window.destroy()


def _tray_icon(window) -> pystray.Icon:
    icon = pystray.Icon("ChatiIA", Image.open(ICON_PATH), "Chati IA")
    icon.menu = pystray.Menu(
        pystray.MenuItem("Abrir Chati", lambda: _show(window), default=True),
        pystray.MenuItem("Cerrar Chati", lambda: _quit(icon, window)),
    )
    return icon


def _claim_single_instance() -> socket.socket | None:
    srv = socket.socket()
    try:
        srv.bind(("127.0.0.1", INSTANCE_PORT))
    except OSError:
        try:
            socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=3).close()
        except OSError:
            pass
        return None
    srv.listen()
    return srv


def _show_on_request(srv: socket.socket, window) -> None:
    while True:
        conn, _ = srv.accept()
        conn.close()
        _show(window)


def _boot(window) -> None:
    threading.Thread(target=_fallback_to_browser, args=(window,), daemon=True).start()
    if not _backend_up():
        try:
            _start_services()
        except OSError as exc:
            window.load_html(_error_html(f"Fallo al lanzar los servicios: {exc}"))
            return
        deadline = time.time() + BACKEND_TIMEOUT
        while not _backend_up():
            if time.time() > deadline:
                window.load_html(_error_html("El orquestador no respondio a tiempo."))
                return
            time.sleep(2)
    window.load_url(URL)


def _set_taskbar_identity() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SergioBernabe.ChatiIA")
    except (AttributeError, OSError):
        pass


class DesktopApi:

    def open_in_browser(self) -> None:
        webbrowser.open(URL)


def main() -> None:
    instance = _claim_single_instance()
    if instance is None:
        return
    _set_taskbar_identity()
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window("Chati IA", html=LOADING_HTML, width=1280, height=800,
                                   min_size=(360, 480), background_color="#14161a", text_select=True,
                                   js_api=DesktopApi())
    window.events.closing += _on_closing
    tray = _tray_icon(window)
    threading.Thread(target=tray.run, daemon=True).start()
    threading.Thread(target=_show_on_request, args=(instance, window), daemon=True).start()
    webview.start(lambda: threading.Thread(target=_boot, args=(window,), daemon=True).start(),
                  icon=ICON_PATH,
                  private_mode=False, storage_path=str(DATA_DIR / "webview"))
    tray.stop()


if __name__ == "__main__":
    main()
