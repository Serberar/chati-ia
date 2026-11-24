import json
import re
from pathlib import Path

from coding import agent_feedback
from coding.agent_tools import GUI_IMPORT


def strip_null_arguments(arguments: str) -> str:
    try:
        data = json.loads(arguments)
    except (TypeError, ValueError):
        return arguments
    if not isinstance(data, dict):
        return arguments
    return json.dumps({k: v for k, v in data.items() if v is not None}, ensure_ascii=False)


def powershell_and(command: str) -> str:
    if "&&" not in command:
        return command
    parts = [p.strip() for p in re.split(r"\s*&&\s*", command)]
    if any(p.count('"') % 2 or p.count("'") % 2 for p in parts) or not all(parts):
        return command
    out = parts[-1]
    for part in reversed(parts[:-1]):
        out = f"{part}; if ($?) {{ {out} }}"
    return out


_RUN_PY = re.compile(r'^\s*(?:&\s*)?(?:python|pythonw|py)(?:\.exe)?\s+["\']?([^"\']+?\.pyw?)["\']?\s*$', re.IGNORECASE)


def gui_script(command: str) -> str | None:
    match = _RUN_PY.match(command)
    if not match or not Path(match.group(1)).is_absolute():
        return None
    try:
        source = Path(match.group(1)).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return match.group(1) if GUI_IMPORT.search(source) else None


def _fix_bash(fn: dict) -> bool:
    try:
        args = json.loads(fn["arguments"])
        command = args["command"]
    except (ValueError, KeyError, TypeError):
        return False
    if not isinstance(command, str):
        return False
    script = gui_script(command)
    if script:
        fn["name"] = "chati_probar_programa"
        fn["arguments"] = json.dumps({"ruta": script}, ensure_ascii=False)
        return True
    fixed = powershell_and(command)
    if fixed == command:
        return False
    fn["arguments"] = json.dumps({**args, "command": fixed}, ensure_ascii=False)
    return True


def _clean_tool_calls(tool_calls: list) -> bool:
    changed = False
    for call in tool_calls or []:
        fn = call.get("function") or {}
        if isinstance(fn.get("arguments"), str):
            cleaned = strip_null_arguments(fn["arguments"])
            if cleaned != fn["arguments"]:
                fn["arguments"] = cleaned
                changed = True
            if fn.get("name") == "bash":
                changed |= _fix_bash(fn)
    return changed


def disable_thinking(body: bytes, models: set[str]) -> bytes:
    if not models or not body:
        return body
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if not isinstance(data, dict) or data.get("model") not in models or "reasoning_effort" in data:
        return body
    data["reasoning_effort"] = "none"
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def clean_completion(body: dict) -> dict:
    for choice in body.get("choices", []):
        _clean_tool_calls((choice.get("message") or {}).get("tool_calls"))
    return body


def clean_stream_line(line: bytes) -> bytes:
    if not line.startswith(b"data: {") or b"tool_calls" not in line:
        return line
    try:
        chunk = json.loads(line[6:])
    except ValueError:
        return line
    changed = False
    for choice in chunk.get("choices", []):
        changed |= _clean_tool_calls((choice.get("delta") or {}).get("tool_calls"))
    if not changed:
        return line
    return b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8")


_FUNCTION_RE = re.compile(r"<function=([\w.-]+)>(.*?)</function>", re.DOTALL)
_PARAM_RE = re.compile(r"<parameter=([\w.-]+)>\s*(.*?)\s*</parameter>", re.DOTALL)
_MARK = "<function="


def _argument(value: str):
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    return parsed if isinstance(parsed, (int, float, bool)) else value


class TextToolCalls:

    def __init__(self):
        self.text = ""
        self.held = None
        self.last = None

    def feed(self, line: bytes) -> list[bytes]:
        if line.startswith(b"data: [DONE]"):
            return self.finish() + [line]
        if not line.startswith(b"data: {"):
            return [line]
        try:
            chunk = json.loads(line[6:])
        except ValueError:
            return [line]
        self.last = chunk
        choice = (chunk.get("choices") or [{}])[0]
        content = (choice.get("delta") or {}).get("content") or ""
        if self.held is not None:
            self.held += content
            return []
        start = len(self.text)
        self.text += content
        mark = self.text.find(_MARK)
        if mark == -1:
            return [line]
        self.held = self.text[mark:]
        before = self.text[start:mark] if mark >= start else ""
        if not before:
            return []
        choice["delta"]["content"] = before
        choice["finish_reason"] = None
        return [b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8")]

    def finish(self) -> list[bytes]:
        if self.held is None or self.last is None:
            return []
        held, self.held = self.held, None
        match = _FUNCTION_RE.search(held)
        base = {k: v for k, v in self.last.items() if k != "choices"}
        if match:
            args = {k: _argument(v) for k, v in _PARAM_RE.findall(match.group(2))}
            call = {"index": 0, "id": f"call_{abs(hash(held)) % 10**8}", "type": "function",
                    "function": {"name": match.group(1), "arguments": json.dumps(args, ensure_ascii=False)}}
            _clean_tool_calls([call])
            chunks = [{"delta": {"tool_calls": [call]}, "finish_reason": None},
                      {"delta": {}, "finish_reason": "tool_calls"}]
        else:
            chunks = [{"delta": {"content": held}, "finish_reason": None}, {"delta": {}, "finish_reason": "stop"}]
        return [b"data: " + json.dumps({**base, "choices": [{"index": 0, **c}]}, ensure_ascii=False).encode("utf-8")
                for c in chunks]


HIDDEN = "[oculto por Chati]"
_SECRET_NAME = r"\w*(?:password|passwd|pwd|secret|token|api_?key|apikey|clave|contrase(?:ñ|n)a)\w*"
_SECRETS = [
    (re.compile(rf"(?i)(\b{_SECRET_NAME}[\"']?\s*[:=]\s*)([\"'])([^\"'\n]{{4,}})\2"), rf"\1\2{HIDDEN}\2"),
    (re.compile(rf"(?im)^(\s*(?:export\s+)?{_SECRET_NAME}=)([^\s\"'#()]{{4,}})[ \t]*$"), rf"\1{HIDDEN}"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}|\bsk-[A-Za-z0-9_\-]{20,}"
                r"|\bAKIA[0-9A-Z]{16}\b|\bxox[abpr]-[A-Za-z0-9\-]{10,}"), HIDDEN),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), HIDDEN),
]


def hide_secret_text(text: str) -> str:
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text


def hide_secrets(body: bytes) -> bytes:
    if not body:
        return body
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return body
    changed = False
    for msg in data["messages"]:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            hidden = hide_secret_text(content)
            changed |= hidden != content
            msg["content"] = hidden
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    hidden = hide_secret_text(part["text"])
                    changed |= hidden != part["text"]
                    part["text"] = hidden
    return json.dumps(data, ensure_ascii=False).encode("utf-8") if changed else body


_notes: dict[str, str] = {}
MAX_NOTES = 20000


def annotate_tool_results(body: bytes) -> bytes:
    if not body or b'"tool"' not in body:
        return body
    try:
        data = json.loads(body)
    except ValueError:
        return body
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list):
        return body
    calls = {c.get("id"): c.get("function") or {} for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
             for c in m.get("tool_calls") or [] if isinstance(c, dict)}
    if len(_notes) > MAX_NOTES:
        _notes.clear()
    changed = False
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "tool" or not isinstance(msg.get("content"), str):
            continue
        cid = msg.get("tool_call_id") or ""
        if cid not in _notes:
            fn = calls.get(cid) or {}
            _notes[cid] = agent_feedback.note_for(fn.get("name"), fn.get("arguments"), msg["content"])
        if _notes[cid]:
            msg["content"] += "\n\n" + _notes[cid]
            changed = True
    return json.dumps(data, ensure_ascii=False).encode("utf-8") if changed else body


MIXED_SUFFIX = "-mixto"


def cpu_when_gpu_busy(body: bytes, gpu_busy: bool) -> bytes:
    if not gpu_busy or not body:
        return body
    try:
        data = json.loads(body)
    except ValueError:
        return body
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, str) or not model.endswith(MIXED_SUFFIX):
        return body
    data["model"] = model.removesuffix(MIXED_SUFFIX) + "-cpu"
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def model_of(body: bytes) -> str | None:
    try:
        data = json.loads(body) if body else None
    except ValueError:
        return None
    model = data.get("model") if isinstance(data, dict) else None
    return model if isinstance(model, str) else None
