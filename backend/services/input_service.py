"""Turn URL and image inputs into analysable text."""
import asyncio
import base64
import io
import shutil
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from loguru import logger

from config import settings
from models.gemini_client import read_screenshot, vision_available
from models.groq_client import call_vision
from models.vision_output import parse_vision_output
from services.safe_fetch import FetchBlocked, FetchError, SafeResponse, safe_request
from shield.hidden_content import scan_html
from shield.textnorm import strip_invisible

MAX_IMAGE_BYTES = 8 * 1024 * 1024
HIDDEN_TEXT_IDS = {"HC-01", "HC-02", "HC-03", "HC-04", "HC-05", "HC-06", "HC-08"}


class InputError(ValueError):
    pass


class PageText(str):
    """Visible text of a fetched page. `hidden_findings` lists text on the page that a reader would
    not see (hidden with CSS, comments, metadata...). That text is never passed on to the agents."""

    hidden_findings: list = []
    hidden_instructions: bool = False


async def _fetch(url: str, max_bytes: int, timeout: float, accept: str) -> SafeResponse:
    try:
        resp = await safe_request(url, max_bytes=max_bytes, timeout=timeout, accept=accept)
    except FetchBlocked as exc:
        raise InputError(f"This URL cannot be fetched: {exc}") from exc
    except FetchError as exc:
        raise InputError(f"Could not fetch URL: {exc}") from exc
    if resp.status >= 400:
        raise InputError(f"Could not fetch URL: the site answered {resp.status}")
    return resp


async def fetch_url_text(url: str) -> PageText:
    """Fetch an article through the SSRF guard and return only the text a reader would see.

    The page is rendered by the Shield's hidden-content scanner: text hidden with CSS, comments,
    alt text and metadata are dropped (and reported in `hidden_findings`), so hidden instructions
    on a page can never reach a model.
    """
    resp = await _fetch(url, max_bytes=2_000_000, timeout=12, accept="text/html,application/xhtml+xml")
    if "html" not in (resp.content_type or "html"):
        raise InputError("URL does not point to an HTML page")

    soup = BeautifulSoup(resp.body, "lxml")
    for tag in soup(["nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    scan = scan_html(str(soup))
    visible = strip_invisible(scan.visible_text)
    title = strip_invisible((soup.title.string or "").strip()) if soup.title and soup.title.string else ""
    text = "\n".join(x for x in (title, visible) if x)
    if len(text) < 20:
        raise InputError("No readable article text found at URL")
    out = PageText(text[:4000])
    out.hidden_findings = [f for f in scan.findings if f.id in HIDDEN_TEXT_IDS]
    out.hidden_instructions = any(f.instruction_like for f in scan.findings)
    return out


async def download_image(url: str) -> tuple[str, str]:
    resp = await _fetch(url, max_bytes=MAX_IMAGE_BYTES, timeout=15, accept="image/png,image/jpeg")
    if resp.truncated:
        raise InputError("Image is larger than 8 MB")
    mime = screenshot_type(resp.body)
    return base64.b64encode(resp.body).decode(), mime


SCREENSHOT_RULE = "Only PNG or JPG screenshots up to 5 MB are supported."
NO_TEXT_FOUND = "No text found in this image."
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))


def screenshot_type(raw: bytes) -> str:
    """Mime type of a PNG/JPG screenshot up to GEMMA_MAX_IMAGE_BYTES, judged by its bytes (not its
    declared type). Anything else raises InputError(SCREENSHOT_RULE)."""
    if not raw or len(raw) > settings.GEMMA_MAX_IMAGE_BYTES:
        raise InputError(SCREENSHOT_RULE)
    for magic, mime in _MAGIC:
        if raw.startswith(magic):
            return mime
    raise InputError(SCREENSHOT_RULE)


def validate_screenshot(data: str) -> tuple[str, str]:
    """Check an uploaded screenshot (data URL or bare base64). Returns (base64, mime)."""
    payload, _declared = split_data_url(data)
    if len(payload) * 3 / 4 > settings.GEMMA_MAX_IMAGE_BYTES + 3:
        raise InputError(SCREENSHOT_RULE)
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as exc:
        raise InputError(SCREENSHOT_RULE) from exc
    return payload, screenshot_type(raw)


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
            raise InputError(NO_TEXT_FOUND)
        return ImageRead(text, "vision", f"Text read by {settings.VISION_MODEL}", cues)

    text = await _tesseract(image_b64, min_chars=5)
    if not text:
        raise InputError(NO_TEXT_FOUND)
    return ImageRead(text, "tesseract", READER_LABELS["tesseract"])


async def image_to_text(image_b64: str, mime: str) -> tuple[str, str]:
    """Returns (text, reader). Thin wrapper over read_image for callers that need only the text."""
    read = await read_image(image_b64, mime)
    return read.text, read.reader
