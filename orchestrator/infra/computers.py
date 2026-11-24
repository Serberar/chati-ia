import json
import subprocess
import threading
import time
from pathlib import Path

import requests

TAILSCALE = Path(r"C:\Program Files\Tailscale\tailscale.exe")
CACHE_SECONDS = 20

_cache: dict = {"at": 0.0, "items": []}
_lock = threading.Lock()


def _status() -> dict | None:
    if not TAILSCALE.exists():
        return None
    try:
        out = subprocess.run([str(TAILSCALE), "status", "--json"], capture_output=True, check=False, text=True, timeout=8,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _host(node: dict) -> str:
    return str(node.get("DNSName", "")).rstrip(".")


def _has_chati(host: str) -> bool:
    try:
        return requests.get(f"https://{host}/health", timeout=4).json().get("status") == "ok"
    except (requests.RequestException, ValueError, AttributeError):
        return False


def this_host() -> str | None:
    status = _status()
    host = _host(status.get("Self", {})) if status else ""
    return host.lower() or None


def list_computers() -> list[dict]:
    with _lock:
        if time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["items"]
    status = _status()
    items = []
    if status:
        me = status.get("Self", {})
        host = _host(me)
        items.append({"name": host.split(".")[0], "url": f"https://{host}/", "this": True,
                      "online": True, "chati": True})
        for peer in (status.get("Peer") or {}).values():
            if str(peer.get("OS", "")).lower() != "windows":
                continue
            host = _host(peer)
            online = bool(peer.get("Online"))
            items.append({"name": host.split(".")[0], "url": f"https://{host}/", "this": False,
                          "online": online, "chati": online and _has_chati(host)})
    with _lock:
        _cache.update(at=time.time(), items=items)
    return items
