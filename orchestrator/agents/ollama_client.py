import json
from collections.abc import Callable, Iterator

import requests

DEFAULT_KEEP_ALIVE = "30m"


def _raise_with_body(resp: requests.Response) -> None:
    if resp.ok:
        return
    try:
        detail = resp.json().get("error")
    except (ValueError, AttributeError):
        detail = None
    if not detail:
        detail = resp.text.strip()
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        if detail:
            raise requests.HTTPError(f"{exc} - Ollama dice: {detail}", response=resp) from None
        raise


NO_THINK_MODELS: set[str] = set()


def _think(model: str, think: bool | None) -> bool | None:
    return False if think is None and model in NO_THINK_MODELS else think


def _comfyui_generating() -> bool:
    from agents import comfyui_client
    return comfyui_client.gpu_busy("http://127.0.0.1:8188")


class OllamaClient:
    gpu_busy: Callable[[], bool] | None = staticmethod(_comfyui_generating)

    def _gpu_options(self, options: dict) -> dict:
        if self.gpu_busy is not None and self.gpu_busy():
            options["num_gpu"] = 0
        return options

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def chat(self, model: str, messages: list[dict], temperature: float = 0.7,
              keep_alive: str = DEFAULT_KEEP_ALIVE, think: bool | None = None,
              num_ctx: int | None = None, num_predict: int | None = None) -> str:
        options = {"temperature": temperature}
        if num_ctx:
            options["num_ctx"] = num_ctx
        if num_predict:
            options["num_predict"] = num_predict
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": self._gpu_options(options),
            "keep_alive": keep_alive,
        }
        think = _think(model, think)
        if think is not None:
            payload["think"] = think
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=180)
        _raise_with_body(resp)
        return resp.json()["message"]["content"]

    def chat_stream(self, model: str, messages: list[dict], temperature: float = 0.7,
                     keep_alive: str = DEFAULT_KEEP_ALIVE, think: bool | None = None) -> Iterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": self._gpu_options({"temperature": temperature}),
            "keep_alive": keep_alive,
        }
        think = _think(model, think)
        if think is not None:
            payload["think"] = think
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=180, stream=True)
        _raise_with_body(resp)
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            if content:
                yield content
            if data.get("done"):
                break

    def chat_with_tools(self, model: str, messages: list[dict], tools: list[dict],
                         temperature: float = 0.7, keep_alive: str = DEFAULT_KEEP_ALIVE,
                         think: bool | None = None) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": self._gpu_options({"temperature": temperature}),
            "keep_alive": keep_alive,
        }
        think = _think(model, think)
        if think is not None:
            payload["think"] = think
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=180)
        _raise_with_body(resp)
        return resp.json()["message"]

    def unload(self, model: str) -> None:
        try:
            requests.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=30,
            )
        except requests.RequestException:
            pass

    def chat_with_tools_stream(self, model: str, messages: list[dict], tools: list[dict],
                                temperature: float = 0.7, keep_alive: str = DEFAULT_KEEP_ALIVE,
                                think: bool | None = None) -> Iterator[tuple[str, object]]:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": True,
            "options": self._gpu_options({"temperature": temperature}),
            "keep_alive": keep_alive,
        }
        think = _think(model, think)
        if think is not None:
            payload["think"] = think
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=180, stream=True)
        _raise_with_body(resp)
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            message = data.get("message", {})
            if message.get("content"):
                yield "text", message["content"]
            if message.get("tool_calls"):
                yield "tool_calls", message["tool_calls"]
            if data.get("done"):
                break

    def preload(self, model: str, keep_alive: str = DEFAULT_KEEP_ALIVE) -> None:
        if self.gpu_busy is not None and self.gpu_busy():
            return
        resp = requests.post(f"{self.base_url}/api/generate",
                             json={"model": model, "keep_alive": keep_alive}, timeout=900)
        _raise_with_body(resp)

    def installed_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except (requests.RequestException, ValueError, KeyError):
            return []

    def running_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/ps", timeout=10)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except (requests.RequestException, ValueError, KeyError):
            return []

    def gpu_share(self, model: str) -> float | None:
        try:
            resp = requests.get(f"{self.base_url}/api/ps", timeout=10)
            resp.raise_for_status()
            for m in resp.json().get("models", []):
                if m.get("name") == model and m.get("size"):
                    return m.get("size_vram", 0) / m["size"]
        except (requests.RequestException, ValueError, KeyError):
            pass
        return None

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        resp = requests.post(
            f"{self.base_url}/api/embed",
            json={"model": model, "input": texts},
            timeout=60,
        )
        _raise_with_body(resp)
        return resp.json()["embeddings"]
