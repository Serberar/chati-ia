TEXT_ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "wan2.2_vae.safetensors"
MAX_FRAMES = 121
STEPS, CFG, SHIFT = 20, 5.0, 8.0
NEGATIVE = ("blurry, low quality, worst quality, static, frozen, distorted, deformed, disfigured, extra limbs, "
            "fused fingers, bad anatomy, watermark, text, subtitles, overexposed")


def frames_for(seconds: float, fps: int = 24) -> int:
    blocks = max(1, -(-round(seconds * fps) // 4))
    return min(4 * blocks + 1, MAX_FRAMES)


def build(prompt: str, unet_path: str, width: int, height: int, frames: int, fps: int, seed: int,
          start_image: str | None = None, steps: int = STEPS, cfg: float = CFG) -> dict:
    wf = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": unet_path, "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
    }
    wf["sampling"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": ["unet", 0], "shift": SHIFT}}
    wf["positive"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}}
    wf["negative"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": NEGATIVE}}
    latent = {"vae": ["vae", 0], "width": width, "height": height, "length": frames, "batch_size": 1}
    if start_image:
        wf["start_image"] = {"class_type": "LoadImage", "inputs": {"image": start_image}}
        latent["start_image"] = ["start_image", 0]
    wf["latent"] = {"class_type": "Wan22ImageToVideoLatent", "inputs": latent}
    wf["sampler"] = {"class_type": "KSampler", "inputs": {
        "model": ["sampling", 0], "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "uni_pc",
        "scheduler": "simple", "positive": ["positive", 0], "negative": ["negative", 0],
        "latent_image": ["latent", 0], "denoise": 1.0}}
    wf["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]}}
    wf["create_video"] = {"class_type": "CreateVideo", "inputs": {"images": ["decode", 0], "fps": fps}}
    wf["save_video"] = {"class_type": "SaveVideo",
                        "inputs": {"video": ["create_video", 0], "filename_prefix": "ia_personal_wan", "format": "auto"}}
    return wf
