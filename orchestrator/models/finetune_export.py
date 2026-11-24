import json
from pathlib import Path

from chat import memory


def export_user_conversations_chatml(user_id: str, dek: bytes, key_generation: int,
                                      out_path: Path, min_turns: int = 2) -> int:
    sessions = memory.list_sessions(limit=100000, user_id=user_id)
    exported = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for session in sessions:
            history = memory.get_history(session["session_id"], limit=10000,
                                          dek=dek, key_generation=key_generation)
            messages = [
                {"role": m["role"], "content": m["content"]}
                for m in history
                if m["role"] in ("user", "assistant") and m["content"]
                and m["content"] != memory.ORPHANED_PLACEHOLDER
            ]
            while messages and messages[-1]["role"] == "user":
                messages.pop()
            if len(messages) < min_turns:
                continue
            f.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
            exported += 1
    return exported
