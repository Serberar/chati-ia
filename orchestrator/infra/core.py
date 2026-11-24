"""Configuracion, registro y clientes de modelos compartidos por todo el orquestador."""
import yaml

from accounts import users
from agents import ollama_client as ollama_client_module
from agents.image_agent import ImageAgent
from agents.llm_agent import LLMAgent
from agents.ollama_client import OllamaClient
from agents.video_agent import VideoAgent
from agents.voice_agent import VoiceAgent
from chat.rag import KnowledgeBase
from chat.router import Router
from chat.verifier import Verifier
from infra import logging_setup
from infra.paths import ORCH_DIR
from models import model_updates

log = logging_setup.setup()

with open(ORCH_DIR / "config.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

users.get_or_create_registration_key()

ollama = OllamaClient(CONFIG["ollama"]["base_url"])
ollama_client_module.NO_THINK_MODELS.update(CONFIG["opencode"].get("no_think_models", []))

text_agent = LLMAgent("text", CONFIG["agents"]["text"]["model"], ollama)
code_agent = LLMAgent("code", CONFIG["agents"]["code"]["model"], ollama)


def _vision_model() -> str:
    cfg = CONFIG["agents"]["vision"]
    gpu = cfg.get("gpu_model")
    if gpu and model_updates.is_installed(*gpu.split(":", 1)):
        return gpu
    return cfg["model"]


vision_agent = LLMAgent("vision", _vision_model(), ollama)
image_agent = ImageAgent(CONFIG["comfyui"]["base_url"])
video_agent = VideoAgent(CONFIG["comfyui"]["base_url"])
voice_agent = VoiceAgent()
router = Router(ollama, routing_model=CONFIG["router"]["model"])
verifier = Verifier(
    ollama,
    model=CONFIG["verifier"]["model"],
    strict=CONFIG["verifier"]["strict"],
)
knowledge_base = KnowledgeBase(ollama)

AGENTS = {"text": text_agent, "code": code_agent}
