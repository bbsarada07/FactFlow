"""Minimal CSS resolution for hidden-content detection: inline styles, <style> blocks with
specificity and !important, @media evaluation, presentational attributes, colours and WCAG contrast.

This is not a browser. The page is evaluated as a desktop-width screen (800px) in light mode:
content that is hidden only on phones, only in dark mode, or only when printed is not reported
(known misses, documented in docs/DECISIONS.md and pinned by tests). Only selectors that soupsieve
understands are used; @supports, @font-face and other @-rules are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_IMPORTANT = re.compile(r"\s*!important\s*$", re.IGNORECASE)
_NUMBER = re.compile(r"^(-?\d*\.?\d+)\s*(px|pt|em|rem|%|vw|vh|cm|mm|in)?$")

# CSS named colours most often seen in email HTML (full list not needed for contrast checks).
NAMED_COLOURS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "maroon": (128, 0, 0), "navy": (0, 0, 128), "purple": (128, 0, 128), "teal": (0, 128, 128), "olive": (128, 128, 0),
    "lime": (0, 255, 0), "aqua": (0, 255, 255), "cyan": (0, 255, 255), "fuchsia": (255, 0, 255),
    "magenta": (255, 0, 255), "orange": (255, 165, 0), "whitesmoke": (245, 245, 245), "snow": (255, 250, 250),
    "ivory": (255, 255, 240), "ghostwhite": (248, 248, 255), "floralwhite": (255, 250, 240),
    "seashell": (255, 245, 238), "mintcream": (245, 255, 250), "azure": (240, 255, 255), "aliceblue": (240, 248, 255),
    "honeydew": (240, 255, 240), "linen": (250, 240, 230), "oldlace": (253, 245, 230), "beige": (245, 245, 220),
    "lavenderblush": (255, 240, 245), "cornsilk": (255, 248, 220), "lightyellow": (255, 255, 224),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211), "gainsboro": (220, 220, 220),
    "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169), "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105),
    "darkslategray": (47, 79, 79), "midnightblue": (25, 25, 112), "darkblue": (0, 0, 139),
    "darkred": (139, 0, 0), "darkgreen": (0, 100, 0), "brown": (165, 42, 42), "pink": (255, 192, 203),
    "gold": (255, 215, 0), "coral": (255, 127, 80), "tomato": (255, 99, 71), "crimson": (220, 20, 60),
    "indigo": (75, 0, 130), "violet": (238, 130, 238), "orchid": (218, 112, 214), "salmon": (250, 128, 114),
    "khaki": (240, 230, 140), "tan": (210, 180, 140), "chocolate": (210, 105, 30), "steelblue": (70, 130, 180),
    "royalblue": (65, 105, 225), "dodgerblue": (30, 144, 255), "skyblue": (135, 206, 235),
    "lightblue": (173, 216, 230), "seagreen": (46, 139, 87), "forestgreen": (34, 139, 34),
}

INHERITED = {"color", "font-size", "visibility", "line-height"}
DEFAULT_BACKGROUND = (255, 255, 255)
DEFAULT_COLOUR = (0, 0, 0)
DEFAULT_FONT_PX = 16.0


@dataclass(frozen=True)
class RGBA:
    r: float
    g: float
    b: float
    a: float = 1.0

    def over(self, bg: tuple[float, float, float]) -> tuple[float, float, float]:
        """Alpha-composite this colour over an opaque background."""
        return (
            self.r * self.a + bg[0] * (1 - self.a),
            self.g * self.a + bg[1] * (1 - self.a),
            self.b * self.a + bg[2] * (1 - self.a),
        )


VIEWPORT_WIDTH_PX = 800.0  # desktop email client


def parse_declarations_full(style: str) -> list[tuple[str, str, bool]]:
    """'color: red !important; FONT-SIZE:0' -> [('color', 'red', True), ('font-size', '0', False)]."""
    out: list[tuple[str, str, bool]] = []
    for decl in _COMMENT.sub("", style or "").split(";"):
        if ":" not in decl:
            continue
        prop, _, value = decl.partition(":")
        prop, raw = prop.strip().lower(), value.strip()
        important = bool(_IMPORTANT.search(raw))
        value = _IMPORTANT.sub("", raw).lower()
        if prop and value:
            out.append((prop, value, important))
    return out


def parse_declarations(style: str) -> dict[str, str]:
    """'color: red; FONT-SIZE:0' -> {'color': 'red', 'font-size': '0'} (lowercased, !important dropped)."""
    return {p: v for p, v, _ in parse_declarations_full(style)}


# ------------------------------------------------------------------------------ @media


def _media_feature(feature: str, width: float) -> bool:
    name, _, value = feature.partition(":")
    name, value = name.strip(), value.strip()
    if name in ("max-width", "max-device-width"):
        px = length_px(value)
        return px is not None and width <= px
    if name in ("min-width", "min-device-width"):
        px = length_px(value)
        return px is not None and width >= px
    if name == "prefers-color-scheme":
        return value == "light"
    if name == "orientation":
        return value == "landscape"
    return False  # unknown features are treated as not matching


def media_matches(query: str, width: float = VIEWPORT_WIDTH_PX) -> bool:
    """Whether an @media query applies to a desktop screen of `width` px in light mode."""
    query = (query or "").strip().lower()
    if not query:
        return True
    for part in query.split(","):
        part = part.strip()
        negate = part.startswith("not ")
        part = part[4:] if negate else part[5:] if part.startswith("only ") else part
        ok = True
        for term in re.split(r"\s+and\s+", part):
            term = term.strip()
            if not term:
                continue
            if term.startswith("("):
                ok = ok and _media_feature(term.strip("() "), width)
            else:
                ok = ok and term in ("all", "screen")
        if ok != negate:
            return True
    return False


def _split_rules(css: str) -> list[tuple[str, str]]:
    """'selector { declarations }' pairs in order, including rules inside matching @media blocks.
    Other @-rules (@supports, @font-face, @keyframes, @import ...) are skipped."""
    css = _COMMENT.sub("", css or "")
    rules: list[tuple[str, str]] = []
    i, n = 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace == -1:
            break
        selector = css[i:brace].strip()
        if ";" in selector and selector.lstrip().startswith("@"):  # @import/@charset statements before a rule
            selector = selector.rsplit(";", 1)[1].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1 : j - 1]
        if selector.lower().startswith("@media"):
            if media_matches(selector[6:]):
                rules.extend(_split_rules(body))
        elif selector and not selector.startswith("@") and "{" not in body:
            rules.append((selector, body))
        i = j
    return rules


# --------------------------------------------------------------------------- specificity

_STRINGS = re.compile(r"\"[^\"]*\"|'[^']*'")


def specificity(selector: str) -> tuple[int, int, int]:
    """CSS specificity (ids, classes/attributes/pseudo-classes, types/pseudo-elements). :where()
    counts zero; :not(), :is() and :has() count their arguments."""
    s = _STRINGS.sub("", selector)
    s = re.sub(r":where\([^)]*\)", "", s)
    s = re.sub(r":(?:not|is|has)\(", " ", s).replace(")", " ")
    ids = len(re.findall(r"#[\w-]+", s))
    classes = (len(re.findall(r"\.[\w-]+", s)) + len(re.findall(r"\[[^\]]*\]", s))
               + len(re.findall(r"(?<!:):(?!:)[\w-]+", s)))
    s_no_attr = re.sub(r"\[[^\]]*\]", " ", s)
    types = len(re.findall(r"(?:^|[\s>+~,])([a-zA-Z][\w-]*)", s_no_attr)) + len(re.findall(r"::[\w-]+", s))
    return ids, classes, types


@dataclass(frozen=True)
class SheetDecl:
    prop: str
    value: str
    important: bool
    specificity: tuple[int, int, int]
    order: int


def stylesheet_map(soup: BeautifulSoup) -> dict[int, list[SheetDecl]]:
    """Declarations from <style> blocks per element (keyed by id(element)), with the specificity
    and source order needed for the cascade."""
    applied: dict[int, list[SheetDecl]] = {}
    order = 0
    for style_tag in soup.find_all("style"):
        for selector, body in _split_rules(style_tag.get_text()):
            decls = parse_declarations_full(body)
            if not decls:
                continue
            for sel in selector.split(","):
                sel = sel.strip()
                if not sel:
                    continue
                try:
                    matches = soup.select(sel)
                except Exception:  # noqa: BLE001 - selectors soupsieve can't handle are skipped
                    continue
                spec = specificity(sel)
                for prop, value, important in decls:
                    order += 1
                    for el in matches:
                        applied.setdefault(id(el), []).append(SheetDecl(prop, value, important, spec, order))
    return applied


def element_style(el: Tag, sheet: dict[int, list[SheetDecl]]) -> dict[str, str]:
    """Own declared style of an element. Cascade, lowest to highest: presentational attributes,
    <style> rules (by specificity, then order), inline style, !important <style> rules,
    !important inline style."""
    style: dict[str, str] = {}
    if el.name == "font" and el.get("color"):
        style["color"] = str(el["color"]).lower()
    if el.get("bgcolor"):
        style["background-color"] = str(el["bgcolor"]).lower()
    for attr in ("width", "height"):
        if el.get(attr) is not None and el.name in ("table", "td", "div", "img", "span", "p"):
            style[attr] = str(el[attr]).lower()
    rules = sorted(sheet.get(id(el), []), key=lambda d: (d.specificity, d.order))
    inline = parse_declarations_full(str(el.get("style") or ""))
    for d in rules:
        if not d.important:
            style[d.prop] = d.value
    for prop, value, important in inline:
        if not important:
            style[prop] = value
    for d in rules:
        if d.important:
            style[d.prop] = d.value
    for prop, value, important in inline:
        if important:
            style[prop] = value
    return style


def _channel(v: str) -> float:
    v = v.strip()
    if v.endswith("%"):
        return max(0.0, min(255.0, float(v[:-1]) * 2.55))
    return max(0.0, min(255.0, float(v)))


def parse_colour(value: str | None) -> RGBA | None:
    """Parse #rgb, #rgba, #rrggbb, #rrggbbaa, rgb(), rgba(), 'transparent' and named colours."""
    if not value:
        return None
    v = value.strip().lower()
    if v == "transparent":
        return RGBA(0, 0, 0, 0.0)
    if v in NAMED_COLOURS:
        return RGBA(*NAMED_COLOURS[v])
    if v.startswith("#"):
        h = v[1:]
        try:
            if len(h) in (3, 4):
                parts = [int(c * 2, 16) for c in h]
            elif len(h) in (6, 8):
                parts = [int(h[i : i + 2], 16) for i in range(0, len(h), 2)]
            else:
                return None
        except ValueError:
            return None
        alpha = parts[3] / 255 if len(parts) == 4 else 1.0
        return RGBA(parts[0], parts[1], parts[2], alpha)
    m = re.match(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
        try:
            if len(parts) < 3:
                return None
            r, g, b = (_channel(p) for p in parts[:3])
            a = 1.0
            if len(parts) >= 4:
                a = float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3])
            return RGBA(r, g, b, max(0.0, min(1.0, a)))
        except ValueError:
            return None
    return None


def background_from(style: dict[str, str]) -> RGBA | None:
    """Background colour declared by `background-color` or a colour inside `background`."""
    if "background-color" in style:
        return parse_colour(style["background-color"])
    if "background" in style:
        for token in re.split(r"\s+(?![^(]*\))", style["background"]):
            c = parse_colour(token)
            if c is not None:
                return c
    return None


def _luminance(rgb: tuple[float, float, float]) -> float:
    def lin(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    """WCAG 2.x contrast ratio between two opaque colours (1.0 = identical, 21 = black on white)."""
    l1, l2 = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def length_px(value: str | None, parent_font_px: float = DEFAULT_FONT_PX) -> float | None:
    """Convert a CSS length to pixels; None if it is not a plain length."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("0", "0.0"):
        return 0.0
    m = _NUMBER.match(v)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2) or "px"
    factor = {
        "px": 1.0, "pt": 4 / 3, "em": parent_font_px, "rem": DEFAULT_FONT_PX, "%": parent_font_px / 100,
        "cm": 37.8, "mm": 3.78, "in": 96.0, "vw": 0.0, "vh": 0.0,
    }[unit]
    return num * factor


def font_size_px(value: str | None, parent_px: float) -> float | None:
    """Font size in px, resolving keywords and relative units against the parent size."""
    if value is None:
        return None
    keywords = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24, "xx-large": 32}
    if value in keywords:
        return float(keywords[value])
    if value == "smaller":
        return parent_px / 1.2
    if value == "larger":
        return parent_px * 1.2
    return length_px(value, parent_px)
