import os
import sys
from pathlib import Path

# carpeta orchestrator/ (este archivo esta en orchestrator/infra/)
ORCH_DIR = Path(__file__).resolve().parent.parent
if getattr(sys, "frozen", False):
    CODE_ROOT = Path(sys.executable).resolve().parent.parent
else:
    CODE_ROOT = ORCH_DIR.parent


def _user_env_from_registry(name: str) -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, name)[0] or None
    except (ImportError, OSError):
        return None


_data_root_override = os.environ.get("CHATI_DATA_ROOT") or _user_env_from_registry("CHATI_DATA_ROOT")
if _data_root_override:
    _installed_root = Path(_data_root_override)
elif os.environ.get("LOCALAPPDATA"):
    _installed_root = Path(os.environ["LOCALAPPDATA"]) / "ChatiIA"
else:
    _installed_root = CODE_ROOT

DEV_CHECKOUT = (CODE_ROOT / ".git").exists()
DATA_ROOT = CODE_ROOT if DEV_CHECKOUT else _installed_root

DATA_DIR = DATA_ROOT / "data"
MODELS_DIR = (_installed_root / "models" if DEV_CHECKOUT and (_installed_root / "models").is_dir()
              else DATA_ROOT / "models")
OUTPUT_DIR = DATA_ROOT / "outputs"
