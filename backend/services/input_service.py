"""Turn URL and image inputs into analysable text."""
import asyncio
import base64
import io
import shutil

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from config import settings
from models.gemini_client import call_gemma_vision, provider
from models.groq_client import VISION_PROMPT, call_vision

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


async def image_to_text(image_b64: str, mime: str) -> tuple[str, str]:
    """Returns (text, method).

    Provider gemini: PNG/JPG up to GEMMA_MAX_IMAGE_BYTES go to Gemma 4 first with the shared
    claim-extraction instruction; if Gemma fails, Tesseract, then the Groq vision model.
    Provider groq: Tesseract first, then the Groq vision model (unchanged).
    """
    size = len(image_b64) * 3 / 4
    if size > MAX_IMAGE_BYTES:
        raise InputError("Image is larger than 8 MB")
    if provider() == "gemini" and mime.lower() in GEMMA_IMAGE_TYPES and size <= settings.GEMMA_MAX_IMAGE_BYTES:
        try:
            text = await call_gemma_vision(image_b64, mime, VISION_PROMPT)
            if len(text) >= 5:
                return text, "gemma"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Gemma image extraction failed; falling back to Tesseract ({type(exc).__name__})")
    if _tesseract_available():
        try:
            text = await asyncio.to_thread(_ocr_sync, image_b64)
            if len(text) >= 25:
                return text, "tesseract"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Tesseract OCR failed: {exc}")
    try:
        text = await call_vision(image_b64, mime)
    except Exception as exc:  # noqa: BLE001
        raise InputError(f"Could not read text from image: {exc}") from exc
    if len(text) < 5:
        raise InputError("No readable text found in image")
    return text, "vision"
