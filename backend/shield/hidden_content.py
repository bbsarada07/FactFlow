"""Hidden-content detectors HC-01..HC-12 (master prompt section 4.2).

`scan_html` walks the HTML once and records, for every piece of text, whether a person would see
it and, if not, which detector explains why. The same walk produces the segments that views.py
turns into "what you see" vs "what an AI would read". Detectors are heuristic: they find the
common hiding techniques, not every possible one (see docs/DECISIONS.md).

Severity of a hidden-text finding depends on what the text says: critical if it reads as an
instruction to an AI, medium if it is a sentence or more of prose, low otherwise (a marketing
preheader hidden with display:none is low).
"""
from __future__ import annotations

import base64
import binascii
import codecs
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from bs4.element import CData, Declaration, Doctype, ProcessingInstruction

from shield import css, domains, settings
from shield.injection import is_instruction_like
from shield.schemas import HiddenFinding
from shield.textnorm import invisible_runs, script_of, strip_invisible

# ---------------------------------------------------------------------------------- helpers

EXPLANATIONS = {
    "HC-01": "This text is switched off with CSS (display:none, visibility:hidden, opacity:0 or the hidden attribute), so you never see it, but an AI reading the email does.",
    "HC-02": "This text is shrunk to nothing (font size of 2px or less, or a box with zero size), so you cannot see it.",
    "HC-03": "This text is the same colour as its background (for example white on white), so it is invisible to you.",
    "HC-04": "This text is pushed off the screen or clipped away, so it is never shown to you.",
    "HC-05": "This text is inside an HTML comment, which email apps never show but an AI reading the source can.",
    "HC-06": "Invisible Unicode characters are hidden in this text; some of them can carry a secret message.",
    "HC-07": "This text mixes letters from different alphabets that look alike, a trick used to imitate real names.",
    "HC-08": "This text sits in a hidden part of the email (image description, tooltip, metadata or hidden field) that you would not normally see.",
    "HC-09": "An attachment contains text that tries to give instructions to an AI.",
    "HC-10": "This text is encoded so that it looks like random characters, but it decodes to instructions.",
    "HC-11": "This link shows one address but actually goes somewhere else.",
    "HC-12": "The plain-text and formatted versions of this email say different things, so an AI may read a message you never see.",
}
TYPES = {
    "HC-01": "css_hidden", "HC-02": "tiny_or_zero_size", "HC-03": "low_contrast", "HC-04": "offscreen_or_clipped",
    "HC-05": "html_comment", "HC-06": "invisible_unicode", "HC-07": "homoglyph", "HC-08": "hidden_carrier",
    "HC-09": "attachment_text", "HC-10": "encoded_payload", "HC-11": "link_mismatch", "HC-12": "alternative_mismatch",
}

_SKIP_TEXT_IN = {"script", "style", "head", "title", "meta", "template", "noscript", "xml"}
_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_CONDITIONAL_COMMENT = re.compile(r"^\s*\[(if|endif)|<!\[endif\]|^\s*<!\[if", re.IGNORECASE)
_OFFSCREEN_LIMIT = -999.0
_FARAWAY_LIMIT = 5000.0
_CLIP_ZERO = re.compile(r"rect\(\s*(0|1px)[\s,]+(0|1px)[\s,]+(0|1px)[\s,]+(0|1px)\s*\)")
_CLIP_PATH_ZERO = re.compile(r"inset\(\s*(50|100)%|circle\(\s*0|polygon\(\s*0[^,]*\)")
_SCALE_ZERO = re.compile(r"scale[xy]?\(\s*0(\.0+)?\s*[,)]")
_CSS_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)
_JS_STRING_OR_COMMENT = re.compile(r"//([^\n]*)|/\*(.*?)\*/|\"([^\"\n]{20,})\"|'([^'\n]{20,})'", re.DOTALL)


def words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def is_prose(text: str, min_chars: int = 40, min_words: int = 6) -> bool:
    """Reads as natural language: long enough, mostly letters, several words."""
    t = (text or "").strip()
    if len(t) < min_chars:
        return False
    letters = sum(1 for c in t if c.isalpha())
    return letters / max(1, len(t)) > 0.5 and len(words(t)) >= min_words


def _natural_language(text: str, min_chars: int) -> bool:
    t = (text or "").strip()
    letters = sum(1 for c in t if c.isalpha())
    return len(t) > min_chars and letters / max(1, len(t)) > 0.5 and len(words(t)) >= 4


def text_severity(text: str) -> tuple[str, bool]:
    """(severity, instruction_like) for a piece of hidden text."""
    if is_instruction_like(text):
        return "critical", True
    if is_prose(text):
        return "medium", False
    return "low", False


def css_path(el: Tag) -> str:
    """Readable CSS path of an element, e.g. 'body > div:nth-of-type(2) > span'."""
    parts = []
    node = el
    while isinstance(node, Tag) and node.name not in ("[document]", "html"):
        siblings = [s for s in node.parent.find_all(node.name, recursive=False)] if node.parent else [node]
        idx = next((i for i, s in enumerate(siblings, 1) if s is node), 1)
        parts.append(node.name if len(siblings) == 1 else f"{node.name}:nth-of-type({idx})")
        node = node.parent
    return " > ".join(reversed(parts)) or "document"


def _clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ------------------------------------------------------------------------------ data model


@dataclass
class Segment:
    """A run of text in document order. hc_id None means a person sees it."""

    text: str
    hc_id: str | None = None


@dataclass
class LinkRef:
    href: str
    anchor_text: str
    location: str


@dataclass
class HtmlScan:
    segments: list[Segment] = field(default_factory=list)
    findings: list[HiddenFinding] = field(default_factory=list)
    links: list[LinkRef] = field(default_factory=list)
    image_srcs: list[str] = field(default_factory=list)

    @property
    def visible_text(self) -> str:
        return _join(s.text for s in self.segments if s.hc_id is None)

    @property
    def raw_text(self) -> str:
        return _join(s.text for s in self.segments)


def _join(parts) -> str:
    out = " ".join(p.strip() for p in parts if p and p.strip())
    return re.sub(r"[ \t]+", " ", out).strip()


@dataclass
class _Ctx:
    """Rendering state inherited down the tree."""

    display_none: Tag | None = None
    visibility_hidden: Tag | None = None
    opacity: float = 1.0
    opacity_el: Tag | None = None
    offscreen: Tag | None = None
    clipped: Tag | None = None
    colour: css.RGBA = field(default_factory=lambda: css.RGBA(*css.DEFAULT_COLOUR))
    colour_el: Tag | None = None
    background: tuple[float, float, float] = css.DEFAULT_BACKGROUND
    background_el: Tag | None = None
    font_px: float = css.DEFAULT_FONT_PX
    font_el: Tag | None = None

    def child(self) -> "_Ctx":
        return _Ctx(**self.__dict__)


# ------------------------------------------------------------------------------ the walker


class _Walker:
    def __init__(self, soup: BeautifulSoup) -> None:
        self.soup = soup
        self.sheet = css.stylesheet_map(soup)
        self.segments: list[Segment] = []
        self.hidden_groups: dict[tuple[str, int], tuple[Tag, list[str]]] = {}
        self.findings: list[HiddenFinding] = []
        self.links: list[LinkRef] = []
        self.image_srcs: list[str] = []
        self.carriers: list[tuple[str, str]] = []  # (location, text)
        self.unicode_sources: list[tuple[str, str]] = []  # (location, raw text) for HC-06

    # -- per element ------------------------------------------------------------------
    def _apply(self, el: Tag, ctx: _Ctx) -> _Ctx:
        st = css.element_style(el, self.sheet)
        c = ctx.child()
        if c.display_none is None and (
            st.get("display") == "none" or el.has_attr("hidden") or st.get("mso-hide") == "all"
        ):
            c.display_none = el
        vis = st.get("visibility")
        if vis in ("hidden", "collapse"):
            c.visibility_hidden = el
        elif vis == "visible":
            c.visibility_hidden = None
        try:
            if "opacity" in st:
                c.opacity *= max(0.0, min(1.0, float(st["opacity"].rstrip("%")) / (100 if st["opacity"].endswith("%") else 1)))
                if c.opacity <= 0.02 and c.opacity_el is None:
                    c.opacity_el = el
        except ValueError:
            pass
        if c.offscreen is None and self._is_offscreen(st):
            c.offscreen = el
        if c.clipped is None and self._is_clipped(st, ctx.font_px):
            c.clipped = el
        if "color" in st:
            colour = css.parse_colour(st["color"])
            if colour is not None:
                c.colour, c.colour_el = colour, el
        bg = css.background_from(st)
        if bg is not None and bg.a > 0:
            c.background, c.background_el = bg.over(ctx.background), el
        if "font-size" in st:
            px = css.font_size_px(st["font-size"], ctx.font_px)
            if px is not None:
                c.font_px, c.font_el = px, el
        return c

    @staticmethod
    def _is_offscreen(st: dict[str, str]) -> bool:
        for prop in ("left", "top", "text-indent", "margin-left", "margin-top", "right"):
            px = css.length_px(st.get(prop))
            if px is not None and px <= _OFFSCREEN_LIMIT:
                return True
        if st.get("position") in ("absolute", "fixed"):
            for prop in ("left", "top"):
                px = css.length_px(st.get(prop))
                if px is not None and px >= _FARAWAY_LIMIT:
                    return True
        if _CLIP_ZERO.search(st.get("clip", "")) or _CLIP_PATH_ZERO.search(st.get("clip-path", "")):
            return True
        return bool(_SCALE_ZERO.search(st.get("transform", "")))

    @staticmethod
    def _is_clipped(st: dict[str, str], font_px: float) -> bool:
        overflow_hidden = st.get("overflow") in ("hidden", "clip") or st.get("overflow-y") in ("hidden", "clip")
        if not overflow_hidden:
            return False
        for prop in ("max-height", "height", "max-width", "width", "line-height"):
            px = css.length_px(st.get(prop), font_px)
            if px is not None and px <= 1.0:
                return True
        return False

    # -- per text node ----------------------------------------------------------------
    def _hidden_reason(self, ctx: _Ctx) -> tuple[str, Tag] | None:
        if ctx.display_none is not None:
            return "HC-01", ctx.display_none
        if ctx.visibility_hidden is not None:
            return "HC-01", ctx.visibility_hidden
        if ctx.opacity <= 0.02 and ctx.opacity_el is not None:
            return "HC-01", ctx.opacity_el
        if ctx.offscreen is not None:
            return "HC-04", ctx.offscreen
        if ctx.clipped is not None:
            return "HC-02", ctx.clipped
        if ctx.font_px <= 2.0:
            return "HC-02", ctx.font_el or self.soup
        fg = ctx.colour.over(ctx.background)
        if ctx.colour.a <= 0.05 or css.contrast_ratio(fg, ctx.background) < 1.2:
            culprit = ctx.colour_el or ctx.background_el or self.soup
            return "HC-03", culprit
        return None

    def _text(self, node: NavigableString, ctx: _Ctx) -> None:
        raw = str(node)
        if not raw.strip():
            return
        parent = node.parent if isinstance(node.parent, Tag) else self.soup
        self.unicode_sources.append((css_path(parent), raw))
        reason = self._hidden_reason(ctx)
        visible = strip_invisible(raw)
        if reason is None:
            self.segments.append(Segment(visible))
        else:
            hc, culprit = reason
            self.segments.append(Segment(visible, hc))
            key = (hc, id(culprit))
            if key not in self.hidden_groups:
                self.hidden_groups[key] = (culprit, [])
            self.hidden_groups[key][1].append(raw)  # evidence keeps control characters (shown escaped)
        for run in invisible_runs(raw):
            if run.decoded.strip():
                self.segments.append(Segment(run.decoded, "HC-06"))

    def _comment(self, node: Comment) -> None:
        text = str(node).strip()
        if _CONDITIONAL_COMMENT.search(text) or not _natural_language(text, 20):
            return
        self.segments.append(Segment(text, "HC-05"))
        sev, instr = text_severity(text)
        parent = node.parent if isinstance(node.parent, Tag) else self.soup
        self.findings.append(_finding("HC-05", sev, css_path(parent) + " (comment)", text, instr))

    def _carrier_attrs(self, el: Tag) -> None:
        path = css_path(el)
        for attr in ("alt", "title", "aria-label", "placeholder"):
            if el.get(attr):
                self.carriers.append((f"{path} @{attr}", str(el[attr])))
        for name, value in el.attrs.items():
            if name.startswith("data-") and isinstance(value, str) and value.strip():
                self.carriers.append((f"{path} @{name}", value))
        if el.name == "input" and str(el.get("type", "")).lower() == "hidden" and el.get("value"):
            self.carriers.append((f"{path} @value", str(el["value"])))
        if el.name == "meta" and el.get("content"):
            self.carriers.append((f"{path} @content", str(el["content"])))

    def walk(self, node: Tag, ctx: _Ctx) -> None:
        for child in node.children:
            if isinstance(child, (Doctype, Declaration, ProcessingInstruction, CData)):
                continue
            if isinstance(child, Comment):
                self._comment(child)
                continue
            if isinstance(child, NavigableString):
                if not (isinstance(node, Tag) and node.name in _SKIP_TEXT_IN):
                    self._text(child, ctx)
                continue
            if not isinstance(child, Tag):
                continue
            self._carrier_attrs(child)
            name = child.name
            if name in ("a", "area") and child.get("href"):
                self.links.append(LinkRef(str(child["href"]), _clean_space(child.get_text(" ")), css_path(child)))
            if name == "img" and child.get("src"):
                self.image_srcs.append(str(child["src"]))
            if name in ("script", "style"):
                self._code_block(child)
                continue
            if name in ("template", "noscript", "title"):
                text = _clean_space(child.get_text(" "))
                if text:
                    self.carriers.append((f"{css_path(child)} (<{name}>)", text))
                continue
            self.walk(child, self._apply(child, ctx))

    def _code_block(self, el: Tag) -> None:
        source = el.get_text()
        pattern = _CSS_COMMENT if el.name == "style" else _JS_STRING_OR_COMMENT
        for m in pattern.finditer(source):
            text = _clean_space(next((g for g in m.groups() if g), ""))
            if text and (is_instruction_like(text) or (el.name == "style" and is_prose(text))):
                self.carriers.append((f"{css_path(el)} (<{el.name}> text)", text))

    # -- finish ----------------------------------------------------------------------
    def finish(self) -> None:
        for (hc, _), (culprit, texts) in self.hidden_groups.items():
            text = _clean_space(" ".join(texts))
            if not text:
                continue
            sev, instr = text_severity(text)
            self.findings.append(_finding(hc, sev, css_path(culprit) if isinstance(culprit, Tag) else "document", text, instr))
        for location, text in self.carriers:
            text = _clean_space(text)
            if len(text) < 3:
                continue
            self.segments.append(Segment(text, "HC-08"))
            instr = is_instruction_like(text)
            if instr or is_prose(text):
                self.findings.append(_finding("HC-08", "critical" if instr else "low", location, text, instr))
        for location, raw in self.unicode_sources:
            self.findings.extend(unicode_findings(raw, location))


def _finding(hc: str, severity: str, location: str, text: str, instruction_like: bool = False,
             explanation: str | None = None) -> HiddenFinding:
    return HiddenFinding(
        id=hc, type=TYPES[hc], severity=severity, location=location, hidden_text=text,
        explanation_en=explanation or EXPLANATIONS[hc], instruction_like=instruction_like,
    )


def scan_html(html: str) -> HtmlScan:
    """Run HC-01..HC-08 and HC-11 over an HTML body (HC-06 also covers attribute-free text)."""
    soup = BeautifulSoup(html or "", "lxml")
    walker = _Walker(soup)
    walker.walk(soup, _Ctx())
    walker.finish()
    scan = HtmlScan(walker.segments, walker.findings, walker.links, walker.image_srcs)
    scan.findings.extend(link_mismatch_findings(scan.links))
    scan.findings.extend(homoglyph_findings(scan.visible_text, "body"))
    return scan


# ------------------------------------------------------------------------- HC-06 unicode


def unicode_findings(text: str, location: str) -> list[HiddenFinding]:
    """HC-06: zero-width, bidi-control and Unicode Tags characters not explained by normal use."""
    runs = invisible_runs(text)
    if not runs:
        return []
    out: list[HiddenFinding] = []
    decoded = "".join(r.decoded for r in runs if r.decoded).strip()
    if decoded:
        instr = is_instruction_like(decoded)
        sev = "critical" if instr else "high" if len(decoded) >= 4 else "medium"
        out.append(_finding("HC-06", sev, location, decoded, instr,
                            "Invisible Unicode 'tag' characters spell out a hidden message here (decoded text shown)."))
    zero = sum(r.end - r.start for r in runs if "zero_width" in r.kinds)
    if zero:
        visible = strip_invisible(text)
        instr = is_instruction_like(visible)
        sev = "high" if instr else "medium" if zero >= 3 else "low"
        out.append(_finding("HC-06", sev, location, f"{zero} zero-width character(s) in: {visible[:200]}", instr,
                            "Zero-width characters are hidden inside this text; they are often used to slip words past filters."))
    bidi = sum(r.end - r.start for r in runs if "bidi" in r.kinds)
    if bidi:
        rtl = any(unicodedata.bidirectional(c) in ("R", "AL") for c in text)
        out.append(_finding("HC-06", "low" if rtl else "medium", location, f"{bidi} text-direction control character(s)",
                            False, "Text-direction control characters can make text display in a different order than it is read."))
    return out


# ------------------------------------------------------------------------ HC-07 homoglyph


def homoglyph_findings(text: str, location: str, severity: str = "medium") -> list[HiddenFinding]:
    """HC-07: words mixing Latin with Cyrillic/Greek letters, or Cyrillic/Greek words that only
    use Latin-lookalike letters inside otherwise Latin text."""
    from shield.textnorm import CONFUSABLES

    tokens = re.findall(r"[^\W\d_]+", text or "")
    latin_words = sum(1 for t in tokens if {script_of(c) for c in t} == {"latin"})
    suspicious = []
    for tok in tokens:
        scripts = {script_of(c) for c in tok} - {None}
        if "latin" in scripts and scripts & {"cyrillic", "greek"}:
            suspicious.append(tok)
        elif scripts and scripts <= {"cyrillic", "greek"} and len(tok) >= 3 and latin_words >= 3 \
                and all(c in CONFUSABLES for c in tok):
            suspicious.append(tok)
    if not suspicious:
        return []
    uniq = list(dict.fromkeys(suspicious))[:10]
    return [_finding("HC-07", severity, location, ", ".join(uniq), False)]


# --------------------------------------------------------------------- HC-11 link mismatch


def link_mismatch_findings(links: list[LinkRef]) -> list[HiddenFinding]:
    """HC-11: link text that shows one domain while the link goes to another; javascript:/data: links."""
    trackers = tuple(settings.load("brands").get("link_trackers", []))
    out = []
    for link in links:
        href = link.href.strip()
        scheme = href.split(":", 1)[0].lower() if ":" in href[:12] else ""
        if scheme in ("javascript", "data", "vbscript"):
            out.append(_finding("HC-11", "high", link.location, f"{link.anchor_text[:120]} -> {href[:120]}", False,
                                f"This link runs a '{scheme}:' address instead of opening a web page."))
            continue
        shown = domains.domains_in_text(link.anchor_text)
        target = domains.host_of(href)
        if not shown or not target or href.lower().startswith("mailto:"):
            continue
        target_reg = domains.registrable(target)
        shown_regs = {domains.registrable(d) for d in shown}
        if target_reg in shown_regs:
            continue
        via_tracker = any(target == t or target.endswith("." + t) for t in trackers)
        sev = "medium" if via_tracker else "high"
        expl = (f"The link shows {shown[0]} but goes through {target}"
                + (", an email click-tracking service." if via_tracker else ", a different site."))
        out.append(_finding("HC-11", sev, link.location, f"shows {shown[0]} -> goes to {target}", False, expl))
    return out


# --------------------------------------------------------------------- HC-10 encoded text

_B64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")
_HEX = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{2}){12,}(?![0-9a-fA-F])")
_PCT = re.compile(r"(?:%[0-9a-fA-F]{2}){4,}[^\s]*")
MAX_DECODE_BYTES = 10 * 1024


def _printable(s: str) -> bool:
    return bool(s) and sum(1 for c in s if c.isprintable() or c in "\n\t") / len(s) > 0.9 and \
        sum(1 for c in s if c.isalpha()) / len(s) > 0.5


def _decode_once(token: str) -> list[tuple[str, str]]:
    """Possible decodings of one token as (encoding, text)."""
    out = []
    if len(token) > MAX_DECODE_BYTES:
        return out
    if _B64.fullmatch(token):
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=False)
            s = raw.decode("utf-8")
            if _printable(s):
                out.append(("base64", s))
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass
    if _HEX.fullmatch(token):
        try:
            s = bytes.fromhex(token).decode("utf-8")
            if _printable(s):
                out.append(("hex", s))
        except (ValueError, UnicodeDecodeError):
            pass
    if "%" in token:
        s = unquote(token)
        if s != token and _printable(s):
            out.append(("percent-encoding", s))
    return out


def encoded_findings(text: str, location: str) -> list[HiddenFinding]:
    """HC-10: base64 / hex / percent-encoded / rot13 text that decodes to instructions (max 2 layers)."""
    out: list[HiddenFinding] = []
    seen: set[str] = set()
    candidates = set(_B64.findall(text or "")) | set(_HEX.findall(text or "")) | set(_PCT.findall(text or ""))
    for token in list(candidates)[:200]:
        layer = [(token, [])]
        for _depth in range(2):
            nxt = []
            for value, chain in layer:
                for enc, decoded in _decode_once(value):
                    path = chain + [enc]
                    if decoded not in seen and is_instruction_like(decoded):
                        seen.add(decoded)
                        out.append(_finding("HC-10", "critical", location, decoded, True,
                                            f"This text is {' then '.join(path)} encoded; decoded, it gives instructions to an AI."))
                    nxt.append((decoded.strip(), path))
            layer = nxt
    # rot13: look for sentences that only read as instructions after rotation
    for sentence in re.split(r"(?<=[.!?\n])\s+", text or ""):
        if len(words(sentence)) < 4 or len(sentence) > 2000:
            continue
        rotated = codecs.decode(sentence, "rot13")
        if rotated not in seen and is_instruction_like(rotated) and not is_instruction_like(sentence):
            seen.add(rotated)
            out.append(_finding("HC-10", "critical", location, rotated, True,
                                "This text is scrambled with ROT13; unscrambled, it gives instructions to an AI."))
    return out


# ------------------------------------------------------------------- HC-12 alternative parts

# Combining marks (Unicode category M) are not \w, so without them Hindi and Telugu words split at every
# vowel sign or virama ("धन्यवाद" became "धन" + "यव").
_MARKS = "".join(re.escape(chr(c)) for c in range(0x300, 0x10000) if unicodedata.category(chr(c)).startswith("M"))
_TOKEN = re.compile(rf"(?:[^\W_]|[{_MARKS}]){{2,}}", re.UNICODE)
_URLISH = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _token_set(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", _URLISH.sub(" ", strip_invisible(text or ""))).casefold()
    return set(_TOKEN.findall(text))


def alternative_mismatch(plain: str, html_visible: str) -> HiddenFinding | None:
    """HC-12: text/plain and text/html parts that differ materially (token-set Jaccard < 0.5)."""
    a, b = _token_set(plain), _token_set(html_visible)
    if len(a) < 5 or len(b) < 5:
        return None
    jaccard = len(a & b) / len(a | b)
    if jaccard >= 0.5:
        return None
    plain_only = [w for w in re.findall(r"\S+", plain) if _token_set(w) and not (_token_set(w) & b)]
    sample = " ".join(plain_only)[:300]
    instr = is_instruction_like(plain) and not is_instruction_like(html_visible)
    sev = "critical" if instr else "medium"
    return _finding("HC-12", sev, "text/plain vs text/html", sample, instr,
                    f"The plain-text version shares only {jaccard:.0%} of its words with the version you see.")


# --------------------------------------------------------------------- HC-09 attachments


def attachment_findings(name: str, text: str, metadata: dict[str, str] | None = None) -> list[HiddenFinding]:
    """HC-09: instruction-like text inside an attachment, and prose hidden in PDF metadata."""
    out = []
    location = f"attachment {name}"
    if text and is_instruction_like(text):
        out.append(_finding("HC-09", "critical", location, text[:300], True))
    for key, value in (metadata or {}).items():
        value = _clean_space(str(value))
        if not value:
            continue
        instr = is_instruction_like(value)
        if instr or is_prose(value):
            out.append(_finding("HC-09", "critical" if instr else "low", f"{location} metadata {key}", value, instr,
                                "The attachment's hidden metadata contains text that reads like a message."))
    return out
