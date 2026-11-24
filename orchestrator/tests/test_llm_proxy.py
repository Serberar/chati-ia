import json

from models import llm_proxy


def test_strip_null_arguments_removes_only_nulls():
    out = json.loads(llm_proxy.strip_null_arguments('{"command": "dir", "workdir": null, "timeout": null, "n": 0}'))
    assert out == {"command": "dir", "n": 0}


def test_strip_null_arguments_leaves_garbage_alone():
    assert llm_proxy.strip_null_arguments("no es json") == "no es json"
    assert llm_proxy.strip_null_arguments("[1, null]") == "[1, null]"


def test_clean_stream_line_rewrites_tool_calls_and_passes_everything_else():
    chunk = {"choices": [{"delta": {"tool_calls": [{"function": {"name": "bash",
             "arguments": '{"command": "Get-ChildItem", "workdir": null}'}}]}}]}
    cleaned = llm_proxy.clean_stream_line(b"data: " + json.dumps(chunk).encode())
    args = json.loads(json.loads(cleaned[6:])["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"])
    assert args == {"command": "Get-ChildItem"}
    for line in (b"data: [DONE]", b'data: {"choices": [{"delta": {"content": "hola"}}]}', b""):
        assert llm_proxy.clean_stream_line(line) == line


def test_clean_completion_non_streaming():
    body = {"choices": [{"message": {"tool_calls": [{"function": {"arguments": '{"a": 1, "b": null}'}}]}}]}
    assert json.loads(llm_proxy.clean_completion(body)["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == {"a": 1}


def test_disable_thinking_only_for_listed_models_and_respects_explicit_values():
    body = json.dumps({"model": "qwen3:8b", "messages": []}).encode()
    assert json.loads(llm_proxy.disable_thinking(body, {"qwen3:8b"}))["reasoning_effort"] == "none"
    assert llm_proxy.disable_thinking(body, {"otro"}) == body
    explicit = json.dumps({"model": "qwen3:8b", "reasoning_effort": "high"}).encode()
    assert llm_proxy.disable_thinking(explicit, {"qwen3:8b"}) == explicit
    assert llm_proxy.disable_thinking(b"", {"qwen3:8b"}) == b""


def _chunk(content=None, finish=None):
    delta = {"content": content} if content is not None else {}
    return b"data: " + json.dumps({"id": "c1", "model": "qwen3-coder:30b-mixto",
                                   "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}).encode()


def _run(lines):
    fixer = llm_proxy.TextToolCalls()
    out = [o for line in lines for o in fixer.feed(line)] + fixer.finish()
    return [json.loads(o[6:]) for o in out if o.startswith(b"data: {")], out


def test_a_tool_call_written_as_text_becomes_a_real_tool_call():
    text = ("Primero, voy a probarlo.\n\n<function=chati_probar_programa>\n<parameter=ruta>\n"
            "C:/Users/S B/Desktop/pruebas/facturas/calcular_total.py\n</parameter>\n<parameter=segundos>\n8\n"
            "</parameter>\n</function>\n</tool_call>")
    pieces = [text[i:i + 7] for i in range(0, len(text), 7)]
    chunks, raw = _run([_chunk(p) for p in pieces] + [_chunk("", "stop"), b"data: [DONE]"])
    said = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert said.startswith("Primero, voy a probarlo.") and "parameter" not in said
    calls = [c["choices"][0]["delta"]["tool_calls"][0] for c in chunks if c["choices"][0]["delta"].get("tool_calls")]
    assert calls[0]["function"]["name"] == "chati_probar_programa"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "ruta": "C:/Users/S B/Desktop/pruebas/facturas/calcular_total.py", "segundos": 8}
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert raw[-1] == b"data: [DONE]"


def test_normal_answers_and_text_that_only_looks_like_a_call_pass_unchanged():
    lines = [_chunk("Hola"), _chunk(", ya esta."), _chunk("", "stop"), b"data: [DONE]"]
    assert _run(lines)[1] == lines
    chunks, _ = _run([_chunk("usa <function=x> asi"), _chunk("", "stop"), b"data: [DONE]"])
    said = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert said == "usa <function=x> asi" and chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_powershell_and_becomes_if_success():
    assert llm_proxy.powershell_and("cd C:/p && python a.py && echo ok") == \
        "cd C:/p; if ($?) { python a.py; if ($?) { echo ok } }"
    assert llm_proxy.powershell_and('echo "a && b"') == 'echo "a && b"'
    assert llm_proxy.powershell_and("Get-ChildItem") == "Get-ChildItem"


def test_running_a_window_program_with_bash_becomes_probar_programa(tmp_path):
    gui = tmp_path / "contador.py"
    gui.write_text("import tkinter as tk\ntk.Tk().mainloop()\n", encoding="utf-8")
    console = tmp_path / "total.py"
    console.write_text("print(1)\n", encoding="utf-8")
    calls = [{"function": {"name": "bash", "arguments": json.dumps({"command": f'python "{gui.as_posix()}"'})}},
             {"function": {"name": "bash", "arguments": json.dumps({"command": f"python {console.as_posix()}",
                                                                    "timeout": None})}},
             {"function": {"name": "bash", "arguments": json.dumps({"command": "git status && git log"})}}]
    assert llm_proxy._clean_tool_calls(calls)
    assert calls[0]["function"] == {"name": "chati_probar_programa",
                                    "arguments": json.dumps({"ruta": gui.as_posix()})}
    assert json.loads(calls[1]["function"]["arguments"]) == {"command": f"python {console.as_posix()}"}
    assert json.loads(calls[2]["function"]["arguments"])["command"] == "git status; if ($?) { git log }"


def test_secrets_never_reach_the_model_but_code_stays_readable():
    text = ('DB_PASSWORD=hunter22\nDEBUG=true\npassword = "abc12345"\nclave = input("Clave: ")\n'
            'token: "ghp_' + "a" * 36 + '"\nconfig = {"api_key": "zzzz9999"}\n')
    hidden = llm_proxy.hide_secret_text(text)
    for secret in ("hunter22", "abc12345", "a" * 36, "zzzz9999"):
        assert secret not in hidden
    assert "DEBUG=true" in hidden and 'clave = input("Clave: ")' in hidden
    body = json.dumps({"model": "m", "messages": [{"role": "tool", "content": text},
                                                  {"role": "user", "content": [{"type": "text", "text": text}]}]})
    out = json.loads(llm_proxy.hide_secrets(body.encode()))
    assert "hunter22" not in json.dumps(out) and out["model"] == "m"
    same = json.dumps({"messages": [{"role": "user", "content": "hola"}]}).encode()
    assert llm_proxy.hide_secrets(same) is same
