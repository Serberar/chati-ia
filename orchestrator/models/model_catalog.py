from dataclasses import dataclass, replace


@dataclass
class CatalogEntry:
    id: str
    modality: str
    label: str
    description: str
    ollama_model: str | None = None
    architecture: str | None = None
    download_url: str | None = None
    filename: str | None = None
    recommended_by_default: bool = True
    extra_files: tuple[tuple[str, str, str], ...] = ()
    sha256: str | None = None


_CLIP_L = ("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5/clip_l.safetensors",
           "text_encoders/clip_l.safetensors",
           "660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd")
_T5XXL = ("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5/t5xxl_fp8_e4m3fn.safetensors",
          "text_encoders/t5xxl_fp8_e4m3fn.safetensors",
          "7d330da4816157540d6bb7838bf63a0f02f573fc48ca4d8de34bb0cbfd514f09")
_FLUX_VAE = ("https://huggingface.co/Kijai/flux-fp8/resolve/2ef6f85f9f4b94634f995ba0bfa84fd3ab865c1d/flux-vae-bf16.safetensors",
             "vae/flux-vae-bf16.safetensors",
             "0c0c8ac49850d6bd174107d4001685f4f6c876768a1c84dde751f2aed69f46ce")
_REALESRGAN = ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
               "upscale_models/RealESRGAN_x4plus.pth",
               "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1")


_BASE_CATALOG: list[CatalogEntry] = [
    CatalogEntry(
        id="texto-rapido", modality="texto", label="Chat rapido",
        description="Respuestas breves, conversacion general - el modelo por defecto del router.",
        ollama_model="qwen3:8b",
    ),
    CatalogEntry(
        id="texto-calidad", recommended_by_default=False, modality="texto", label="Chat de mejor calidad",
        description="Mas lento, menos probable que invente datos - programacion y respuestas mas elaboradas.",
        ollama_model="qwen3-coder:30b-cpu",
    ),
    CatalogEntry(
        id="texto-vision", recommended_by_default=False, modality="texto", label="Vision (comentar fotos)",
        description="Necesario para poder subir una foto en el chat y que la describa.",
        ollama_model="qwen2.5vl:7b-gpu",
    ),
    CatalogEntry(
        id="agente-rapido", modality="texto", label="Agente (tareas en el ordenador)",
        description="El modelo del modo Agente: crea, mueve, ordena y renombra archivos por ti.",
        ollama_model="qwen3:8b",
    ),
    CatalogEntry(
        id="memoria", modality="texto", label="Memoria y documentos",
        description="Necesario para que Chati recuerde conversaciones y busque en tus documentos.",
        ollama_model="nomic-embed-text",
    ),
    CatalogEntry(
        id="imagen-flux", recommended_by_default=False, modality="imagen", label="FLUX (rapido, buena calidad general)",
        description="El generador de imagen recomendado por defecto.",
        architecture="flux",
        download_url="https://huggingface.co/city96/FLUX.1-schnell-gguf/resolve/f495746ed9c5efcf4661f53ef05401dceadc17d2/flux1-schnell-Q4_K_S.gguf",
        filename="flux1-schnell-Q4_K_S.gguf",
        sha256="4fd16477b3a5296d0cf722c4b92a9fd7f30d09ac7495826e4465d8de9c9fd973",
        extra_files=(_CLIP_L, _T5XXL, _FLUX_VAE, _REALESRGAN),
    ),
    CatalogEntry(
        id="imagen-sdxl", recommended_by_default=False, modality="imagen", label="SDXL base",
        description="Otro generador de imagen, con mas estilos disponibles.",
        architecture="sdxl",
        download_url="https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/462165984030d82259a11f4367a4eed129e94a7b/sd_xl_base_1.0.safetensors",
        filename="sd_xl_base_1.0.safetensors",
        sha256="31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b",
    ),
    CatalogEntry(
        id="video-ltxv", recommended_by_default=False, modality="video", label="LTX-Video (2B, destilado)",
        description="El generador de video recomendado por defecto - rapido para su tamaño.",
        architecture="ltxv",
        download_url="https://huggingface.co/Lightricks/LTX-Video/resolve/8984fa25007f376c1a299016d0957a37a2f797bb/ltxv-2b-0.9.8-distilled-fp8.safetensors",
        filename="ltxv-2b-0.9.8-distilled-fp8.safetensors",
        sha256="d6d8fa8ed3a98346787c2503ac80fb5d7cebcf80e356b79a2ba361fbadf97e15",
        extra_files=(_T5XXL,),
    ),
    CatalogEntry(
        id="voz-piper", modality="voz", label="Voz en español (Piper)",
        description="Necesario para que Chati responda hablando.",
        download_url="https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx",
        filename="es_ES-davefx-medium.onnx",
        sha256="6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917",
    ),
]


GPU_SUFFIX = "-gpu"
_CPU_ONLY_EXCLUDED_MODALITIES = {"video"}


def catalog_for_tier(tier: str) -> list[CatalogEntry]:
    if tier == "cpu_only":
        return [replace(e, ollama_model=e.ollama_model.removesuffix(GPU_SUFFIX) + "-cpu")
                if e.ollama_model and e.ollama_model.endswith(GPU_SUFFIX) else e
                for e in _BASE_CATALOG if e.modality not in _CPU_ONLY_EXCLUDED_MODALITIES]
    return list(_BASE_CATALOG)
