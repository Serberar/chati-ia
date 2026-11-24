"""Modelos de peticion y respuesta del chat, compartidos por las rutas."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(max_length=100_000)
    agent: str | None = None
    session_id: str | None = None
    model_profile: str | None = None
    image_base64: str | None = Field(None, max_length=35_000_000)
    verify: bool = True
    image_model: str | None = None
    video_model: str | None = None


class ChatResponse(BaseModel):
    agent_used: str
    response: str
    verifier_gated: bool
    verifier_reason: str | None = None
    file_path: str | None = None
    file_url: str | None = None
    session_id: str | None = None
    sources: list[str] | None = None
    agent_task_id: str | None = None
    agent_choice: dict | None = None
