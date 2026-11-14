"""Local AI vision models for product photos: product segmentation (background removal) and 4x
super-resolution. They run on CPU through OpenCV DNN, per image, and never generate or alter product
content. Every model is optional: without OpenCV or a model file the callers fall back to classic
image processing."""
import hashlib
import logging
import os
import threading
import urllib.request
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

BUNDLED = Path(__file__).with_name("vision_models_data")
CACHE = Path(os.environ.get("TENALI_MODEL_CACHE") or Path.home() / ".cache" / "tenali" / "models")
REMBG = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
# name: (file, sha256, download URL or None when bundled)
MODELS = {
    "edsr": ("EDSR_x4.pb", "dd35ce3cae53ecee2d16045e08a932c3e7242d641bb65cb971d123e06904347f",
             "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x4.pb"),
    "fsrcnn": ("FSRCNN_x4.pb", "5c68d18db561aed8ead4ffedf1b897ea615baaf60ebf6c35f8e641f8fa4a21bf", None),
    "isnet": ("isnet-general-use.onnx", "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
              REMBG + "isnet-general-use.onnx"),
    "u2netp": ("u2netp.onnx", "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8", None),
}
# Segmentation input size and normalization (ISNet: 1024, mean 0.5; U2-Net: 320, ImageNet statistics).
SEGMENTERS = (("isnet", 1024, (0.5, 0.5, 0.5), (1.0, 1.0, 1.0)),
              ("u2netp", 320, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)))
EDSR_MAX_PIXELS = 60_000
FSRCNN_MAX_PIXELS = 400_000
_lock = threading.Lock()
_nets = {}
_failed = set()


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def model_path(name: str, download: bool = True) -> Path | None:
    """Verified model file: bundled, cached, or downloaded once into the cache."""
    filename, sha256, url = MODELS[name]
    for path in (BUNDLED / filename, CACHE / filename):
        if path.is_file() and _digest(path) == sha256:
            return path
    if not url or not download:
        return None
    target = CACHE / filename
    partial = target.with_suffix(".part")
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
        if _digest(partial) != sha256:
            raise ValueError("checksum mismatch")
        partial.replace(target)
        return target
    except Exception as error:  # noqa: BLE001 - optional enhancement must never break image upload
        logger.warning("Vision model %s unavailable: %s", filename, error)
        partial.unlink(missing_ok=True)
        return None


def _net(name: str):
    if name in _nets or name in _failed:
        return _nets.get(name)
    try:
        import cv2
    except ImportError:
        _failed.add(name)
        return None
    path = model_path(name)
    try:
        if path is None:
            raise FileNotFoundError(MODELS[name][0])
        if name in {"edsr", "fsrcnn"}:
            net = cv2.dnn_superres.DnnSuperResImpl_create()
            net.readModel(str(path))
            net.setModel(name, 4)
        else:
            net = cv2.dnn.readNetFromONNX(str(path))
    except Exception as error:  # noqa: BLE001
        logger.warning("Vision model %s could not be loaded: %s", name, error)
        _failed.add(name)
        return None
    _nets[name] = net
    return net


def upscale(image: Image.Image) -> Image.Image | None:
    """4x learned upscale of an RGB image, or None when it is too large or no model is available."""
    pixels = image.width * image.height
    names = [name for name, limit in (("edsr", EDSR_MAX_PIXELS), ("fsrcnn", FSRCNN_MAX_PIXELS)) if pixels <= limit]
    if not names:
        return None
    try:
        import numpy
    except ImportError:
        return None
    with _lock:
        for name in names:
            net = _net(name)
            if net is None:
                continue
            try:
                result = net.upsample(numpy.asarray(image.convert("RGB"))[:, :, ::-1].copy())
            except Exception as error:  # noqa: BLE001
                logger.warning("Super-resolution with %s failed: %s", name, error)
                continue
            return Image.fromarray(result[:, :, ::-1].copy())
    return None


def product_mask(image: Image.Image) -> Image.Image | None:
    """Soft "L" mask of the main product (255 = product), or None when no model is available or the photo
    has no clearly separable product (for example a close-up that fills the frame)."""
    try:
        import cv2
        import numpy
    except ImportError:
        return None
    rgb = numpy.asarray(image.convert("RGB")).astype(numpy.float32) / 255
    with _lock:
        for name, size, mean, std in SEGMENTERS:
            net = _net(name)
            if net is None:
                continue
            try:
                tensor = (cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA if min(image.size) > size
                                     else cv2.INTER_CUBIC) - numpy.array(mean, numpy.float32)) / numpy.array(std, numpy.float32)
                net.setInput(tensor.transpose(2, 0, 1)[None].astype(numpy.float32))
                output = numpy.clip(net.forward().reshape(size, size), 0, 1)
            except Exception as error:  # noqa: BLE001
                logger.warning("Product segmentation with %s failed: %s", name, error)
                continue
            product, unsure = float((output > 0.5).mean()), float(((output > 0.15) & (output < 0.85)).mean())
            if not 0.02 <= product <= 0.97 or unsure > 0.12:
                return None
            mask = Image.fromarray((output * 255).round().astype(numpy.uint8), "L")
            return mask.resize(image.size, Image.BICUBIC)
    return None


if __name__ == "__main__":
    # Deployment prefetch: python -m app.services.vision_models
    for key in MODELS:
        print(key, model_path(key) or "unavailable")
