"""Turn URL and image inputs into analysable text."""
import asyncio
import base64
import io
import shutil
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from config import settings
from models.gemini_client import read_screenshot, vision_available
from models.groq_client import call_vision
from models.vision_output import parse_vision_output

USER_AGENT = "Mozilla/5.0 (compatible; NemesisAI/1.0; +https://github.com/nemesisai)"
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class InputError(ValueError):
    pass


async def fetch_url_text(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as http:
            resp = await http.get(url)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise InputError(f"Could not fetch URL: {exc}") from exc

    if "html" not in resp.headers.get("content-type", "html"):
        raise InputError("URL does not point to an HTML page")

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    description = (meta.get("content") or "").strip() if meta else ""
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    body = " ".join(p for p in paragraphs if len(p) > 40)
    text = "\n".join(x for x in (title, description, body) if x)
    if len(text) < 20:
        raise InputError("No readable article text found at URL")
    return text[:4000]


async def download_image(url: str) -> tuple[str, str]:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as http:
            resp = await http.get(url)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise InputError(f"Could not download image: {exc}") from exc
    if len(resp.content) > MAX_IMAGE_BYTES:
        raise InputError("Image is larger than 8 MB")
    mime = resp.headers.get("content-type", "image/png").split(";")[0]
    return base64.b64encode(resp.content).decode(), mime


def split_data_url(data: str) -> tuple[str, str]:
    if data.startswith("data:"):
        header, _, payload = data.partition(",")
        mime = header[5:].split(";")[0] or "image/png"
        return payload, mime
    return data, "image/png"


def _tesseract_available() -> bool:
    return bool(settings.TESSERACT_CMD) or shutil.which("tesseract") is not None


def _ocr_sync(image_b64: str) -> str:
    import pytesseract
    from PIL import Image

    if settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
    img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
    img = img.convert("L")
    if img.width < 1000:
        img = img.resize((img.width * 2, img.height * 2))
    langs = "eng"
    try:
        available = set(pytesseract.get_languages(config=""))
        extra = [lang for lang in ("hin", "mar", "tam", "tel", "ben") if lang in available]
        langs = "+".join(["eng", *extra])
    except Exception:  # noqa: BLE001
        pass
    return pytesseract.image_to_string(img, lang=langs).strip()


GEMMA_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}
READER_LABELS = {"gemma": "Text read by Gemma 4", "tesseract": "Image read without AI"}


@dataclass
class ImageRead:
    """Result of reading a screenshot: text for the reasoning pipeline, cues for display only."""

    text: str
    reader: str  # gemma | tesseract | vision
    label: str
    cues: list[str] = field(default_factory=list)


async def _tesseract(image_b64: str, min_chars: int) -> str:
    if not _tesseract_available():
        return ""
    try:
        text = (await asyncio.to_thread(_ocr_sync, image_b64)).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Tesseract OCR failed: {type(exc).__name__}")
        return ""
    return text if len(text) >= min_chars else ""


async def read_image(image_b64: str, mime: str) -> ImageRead:
    """Read a screenshot. Vision models only transcribe; they never judge the claim.

    VISION_PROVIDER gemini (with a key): PNG/JPG up to GEMMA_MAX_IMAGE_BYTES go to Gemma 4 with
    the shared VISION_PROMPT; Tesseract is the fallback. VISION_PROVIDER groq: Tesseract, then
    the Groq vision model. VISION_PROVIDER none: Tesseract only.
    """
    size = len(image_b64) * 3 / 4
    if size > MAX_IMAGE_BYTES:
        raise InputError("Image is larger than 8 MB")
    if vision_available() and mime.lower() in GEMMA_IMAGE_TYPES and size <= settings.GEMMA_MAX_IMAGE_BYTES:
        try:
            read = await read_screenshot(image_b64, mime)
            if len(read.text) >= 5:
                return ImageRead(read.text, "gemma", READER_LABELS["gemma"], read.cues)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Gemma image reading failed; falling back to Tesseract ({type(exc).__name__})")

    if settings.VISION_PROVIDER == "groq":
        text = await _tesseract(image_b64, min_chars=25)
        if text:
            return ImageRead(text, "tesseract", READER_LABELS["tesseract"])
        try:
            text, cues = parse_vision_output(await call_vision(image_b64, mime))
        except Exception as exc:  # noqa: BLE001
            raise InputError(f"Could not read text from image: {exc}") from exc
        if len(text) < 5:
            raise InputError("No readable text found in image")
        return ImageRead(text, "vision", f"Text read by {settings.VISION_MODEL}", cues)

    text = await _tesseract(image_b64, min_chars=5)
    if not text:
        raise InputError("No readable text found in image")
    return ImageRead(text, "tesseract", READER_LABELS["tesseract"])


async def image_to_text(image_b64: str, mime: str) -> tuple[str, str]:
    """Returns (text, reader). Thin wrapper over read_image for callers that need only the text."""
    read = await read_image(image_b64, mime)
    return read.text, read.reader
