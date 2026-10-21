"""Parse a screenshot-reading reply into (text, cues) and nothing else.

Vision models only read screenshots. Whatever else a reply contains (a verdict, a confidence,
a correction) is discarded here, so it can never reach the record or the reasoning models.
"""
import json
import re

MAX_CUES = 4
MAX_CUE_CHARS = 80
_SECTION = re.compile(r"^\s*(TEXT|CUES)\s*:\s*$", re.IGNORECASE | re.MULTILINE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_TEXT_KEYS = ("text", "extracted_text", "transcription")


def _clean_cues(items) -> list[str]:
    cues = []
    for item in items if isinstance(items, list) else []:
        cue = re.sub(r"^\s*[-*•]\s*", "", str(item)).strip()
        if cue and cue.lower() not in ("none", "n/a"):
            cues.append(cue[:MAX_CUE_CHARS])
    return cues[:MAX_CUES]


def parse_vision_output(raw: str) -> tuple[str, list[str]]:
    """Return (extracted text, visible cues). Accepts the TEXT:/CUES: format from VISION_PROMPT,
    a JSON object, or plain text (treated as text only)."""
    raw = (raw or "").strip()
    unfenced = _FENCE.sub("", raw).strip()
    if unfenced.startswith("{"):
        try:
            obj = json.loads(unfenced)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            text = next((str(obj[k]) for k in _TEXT_KEYS if obj.get(k)), "")
            return text.strip(), _clean_cues(obj.get("cues"))

    parts = _SECTION.split(raw)
    if len(parts) > 1:
        sections = {parts[i].upper(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}
        text = sections.get("TEXT", "").strip()
        cues = _clean_cues(sections.get("CUES", "").splitlines())
        return text, cues
    return raw, []
