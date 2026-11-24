"""Tamaños y duracion de los videos."""
import io

from chat import prompt_writer

VIDEO_DEFAULT_SECONDS = 4


def video_size_like(image_bytes: bytes) -> tuple[int, int]:
    from PIL import Image, UnidentifiedImageError
    try:
        width, height = Image.open(io.BytesIO(image_bytes)).size
    except (UnidentifiedImageError, OSError):
        return prompt_writer.VIDEO_SIZES["horizontal"]
    kind = "vertical" if height > width * 1.15 else "horizontal" if width > height * 1.15 else "cuadrado"
    return prompt_writer.VIDEO_SIZES[kind]
