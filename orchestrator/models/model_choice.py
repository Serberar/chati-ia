"""Que modelo de chat usar segun el perfil elegido."""
from infra.core import CONFIG


def profile_model(profile: str | None) -> str | None:
    profiles = CONFIG["agents"]["text"].get("profiles", {})
    if profile and profile in profiles:
        return profiles[profile]["model"]
    return None


def profile_think(profile: str | None) -> bool | None:
    profiles = CONFIG["agents"]["text"].get("profiles", {})
    if profile and profile in profiles:
        return profiles[profile].get("think")
    return None
