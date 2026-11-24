import re
import subprocess
import time
import unicodedata
from pathlib import Path

PREFIX = "chati/"


def _git(folder: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=False,
                          timeout=120, encoding="utf-8", errors="replace")


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", plain)[:6]
    return "-".join(words) or "encargo"


def start_branch(folder: Path, task: str) -> str | None:
    try:
        if not (folder / ".git").exists():
            return None
        current = _git(folder, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if current.startswith(PREFIX):
            return current
        status = _git(folder, "status", "--porcelain")
        if status.returncode != 0 or status.stdout.strip() or current in ("", "HEAD"):
            return None
        branch = f"{PREFIX}{_slug(task)}-{time.strftime('%m%d-%H%M')}"
        return branch if _git(folder, "switch", "-c", branch).returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def commit(folder: Path, branch: str, task: str) -> str | None:
    try:
        if _git(folder, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != branch:
            return None
        if _git(folder, "add", "-A").returncode != 0 or not _git(folder, "status", "--porcelain").stdout.strip():
            return None
        title = " ".join(task.split())
        message = f"Chati: {title[:68]}" + (f"\n\n{task.strip()[:2000]}" if len(title) > 68 else "")
        if _git(folder, "commit", "-q", "-m", message).returncode != 0:
            return None
        return _git(folder, "rev-parse", "--short", "HEAD").stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
