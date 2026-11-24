import io

from PIL import Image, ImageDraw



def _sample_image_bytes() -> bytes:
    img = Image.new("RGB", (200, 200), color="black")
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 150, 150], fill="white")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
