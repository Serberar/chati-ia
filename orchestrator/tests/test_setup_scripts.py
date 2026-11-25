"""El instalador no puede tocar lo que ya tenga el usuario."""
import re
from pathlib import Path

SETUP = Path(__file__).resolve().parents[2] / "setup"


def _read(name: str) -> str:
    return (SETUP / name).read_text(encoding="utf-8-sig")


def test_opencode_config_of_the_user_is_never_written():
    for script in SETUP.glob("*.ps1"):
        assert r".config\opencode" not in script.read_text(encoding="utf-8-sig"), script.name


def test_global_variables_are_only_set_for_chati_or_its_own_ollama():
    text = _read("install.ps1")
    assert 'setx HF_HOME' not in text
    for line in (ln for ln in text.splitlines() if "setx OLLAMA" in ln or "setx HIP" in ln):
        assert line.startswith("    "), f"fuera de un bloque condicional: {line}"


def test_tailscale_and_images_are_opt_in():
    text = _read("install.ps1")
    assert re.search(r'\$Tailscale = "no"', text)
    assert text.index('$Tailscale -ne "si"') < text.index("serve --bg")
    assert "-Tailscale {code:TailscaleArg} -ConImagen {code:ImagenArg}" in _read("chati_installer.iss")
