import hashlib
import io
import re
import threading
import warnings
from collections import OrderedDict

from fastapi import HTTPException
from PIL import Image, ImageChops, ImageColor, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

DISPLAY_SIZE = 1000
MAX_PIXELS = 16_000_000
# A product photo inside a bill uploaded to the AI assistant: the private attachment and a 0-1000 "x0,y0,x1,y1" region.
PHOTO_REFERENCE = re.compile(r"^ai-photo:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/"
                             r"(\d{1,4}(?:\.\d{1,3})?(?:,\d{1,4}(?:\.\d{1,3})?){3})$")
# AI rendering takes tens of seconds, so results are reused by photo content: callers render before taking
# database locks (see warm_display_images) and the locked save then only uploads.
RENDER_CACHE_SIZE = 32
_rendered: OrderedDict = OrderedDict()
_rendered_lock = threading.Lock()


def normalize_background(background: str) -> str:
    if isinstance(background, str):
        value = background.strip().lower().replace(" ", "")
        if value in ImageColor.colormap or re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            red, green, blue = ImageColor.getrgb(value)
            return f"#{red:02x}{green:02x}{blue:02x}"
    raise HTTPException(422, "Use a colour name such as white, black or light blue (a six-digit hex colour also works).")


def background_name(background: str) -> str:
    value = normalize_background(background)
    rgb = ImageColor.getrgb(value)
    return next((name for name in ImageColor.colormap if ImageColor.getrgb(name) == rgb), value)


def display_image(content: bytes, size: int = DISPLAY_SIZE, *, background: str = "#ffffff") -> bytes:
    background = normalize_background(background)
    key = (hashlib.sha256(content).hexdigest(), size, background)
    with _rendered_lock:
        if key in _rendered:
            _rendered.move_to_end(key)
            return _rendered[key]
    result = _render(content, size, background)
    with _rendered_lock:
        _rendered[key] = result
        while len(_rendered) > RENDER_CACHE_SIZE:
            _rendered.popitem(last=False)
    return result


def _render(content: bytes, size: int, background: str) -> bytes:
    """Website display version of a product photo as a square WebP. When AI segmentation (or the photo's
    own transparency) isolates the product, only the product is kept, on pure white with a soft contact
    shadow. Otherwise the whole photo fits on white without stretching, cropping or duplicating it.
    Small photos are AI super-resolved; all get tone, clarity, colour and sharpening."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > MAX_PIXELS:
                    raise HTTPException(422, "Product image must have at most 16 million pixels.")
                source.load()
                image = ImageOps.exif_transpose(source)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HTTPException(422, "Product image could not be read. Use a valid PNG, JPEG or WebP photo.") from error
    from app.services import vision_models
    mask = None
    if image.mode in {"RGBA", "LA", "P", "PA"}:
        rgba = image.convert("RGBA")
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
        if rgba.getchannel("A").getextrema()[0] < 250:
            mask = rgba.getchannel("A")
    image = image.convert("RGB")
    if mask is None:
        mask = vision_models.product_mask(image)
    box = mask.point(lambda value: 255 if value > 40 else 0).getbbox() if mask is not None else None
    canvas = Image.new("RGB", (size, size), background)
    if box:
        margin = max(2, round(max(box[2] - box[0], box[3] - box[1]) * 0.01))
        box = (max(0, box[0] - margin), max(0, box[1] - margin), min(image.width, box[2] + margin), min(image.height, box[3] + margin))
        image, mask = image.crop(box), mask.crop(box)
        image = _enhance(image, round(size * 0.84), vision_models)
        mask = mask.resize(image.size, Image.BICUBIC)
        image, mask = _fit(image, round(size * 0.84)), _fit(mask, round(size * 0.84))
        # Tighten the soft model edge so no backdrop halo remains around the product.
        mask = mask.point(lambda value: 0 if value < 24 else 255 if value > 232 else round((value - 24) * 255 / 208))
        left, top = (size - image.width) // 2, (size - image.height) // 2
        shadow = mask.resize((image.width, max(1, image.height // 9)), Image.BILINEAR).point(lambda value: round(value * 0.2))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(4, image.width // 40)))
        layer = Image.new("L", (size, size), 0)
        layer.paste(shadow, (left, min(size - shadow.height, top + image.height - shadow.height // 2)))
        canvas.paste((60, 60, 60), mask=layer.filter(ImageFilter.GaussianBlur(max(6, image.width // 30))))
        canvas.paste(image, (left, top), mask)
    else:
        if background != "#ffffff":
            raise HTTPException(422, "The product background could not be isolated. Use a transparent image, enable AI segmentation, or choose white.")
        image = _enhance(trim_background(image), size, vision_models)
        image = _fit(image, round(size * 0.84))
        canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    output = io.BytesIO()
    canvas.save(output, format="WEBP", quality=88, method=6)
    return output.getvalue()


def _fit(image: Image.Image, side: int) -> Image.Image:
    scale = min(side / image.width, side / image.height)
    resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
    return resized.filter(ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=2)) if resized.mode == "RGB" else resized


def _enhance(image: Image.Image, side: int, vision_models) -> Image.Image:
    if min(side / image.width, side / image.height) > 1.25:
        # Small photos (such as a product cut out of a bill) get learned detail instead of a blurry stretch.
        image = vision_models.upscale(image) or image
    # Half-strength auto-contrast lifts dull photos without over-stretching close-ups of one colour.
    image = Image.blend(image, ImageOps.autocontrast(image, cutoff=0.5, preserve_tone=True), 0.5)
    image = image.filter(ImageFilter.UnsharpMask(radius=max(4, round(max(image.size) / 40)), percent=22, threshold=0))
    return ImageEnhance.Color(image).enhance(1.1)


def edge_colour(image: Image.Image) -> tuple:
    width, height = image.size
    edge = [image.getpixel((x, y)) for x in range(0, width, max(1, width // 20)) for y in (0, height - 1)]
    edge += [image.getpixel((x, y)) for y in range(0, height, max(1, height // 20)) for x in (0, width - 1)]
    return tuple(sorted(channel)[len(channel) // 2] for channel in zip(*edge))


def trim_background(image: Image.Image, threshold: int = 24) -> Image.Image:
    """Crop the backdrop around the product, ignoring thin lines such as bill table rules, and lift an
    off-white backdrop to pure white so it blends with the display canvas."""
    width, height = image.size
    background = edge_colour(image)
    mask = ImageChops.difference(image, Image.new("RGB", image.size, background)).convert("L").point(
        lambda value: 255 if value > threshold else 0)
    stroke = max(3, (min(width, height) // 60) | 1)
    box = mask.filter(ImageFilter.MinFilter(stroke)).filter(ImageFilter.MaxFilter(stroke)).getbbox()
    if box and (box[2] - box[0]) * (box[3] - box[1]) >= 0.05 * width * height:
        # Crop tight: the display canvas supplies the white margin, and a margin here could keep table rules.
        image = image.crop(box)
        background = edge_colour(image)
    if min(background) >= 225:
        image = Image.merge("RGB", [band.point(lambda value, level=level: min(255, round(value * 255 / level)))
                                    for band, level in zip(image.split(), background)])
    return image
