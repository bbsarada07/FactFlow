"""'What you see' vs 'what an AI would read' (master prompt section 4.3).

visible_view: text a person sees in an email app (hidden elements, comments and invisible
              characters removed).
raw_view:     text a naive AI summariser would ingest (all text nodes, comments, image
              descriptions, metadata, decoded Unicode Tags, and the plain-text part when it
              differs from the HTML).
diff:         the pieces of raw_view that are not in visible_view, each tagged with the HC-ID
              that explains why.

All three are plain strings: the frontend must show them as escaped text, never as HTML.
"""
from __future__ import annotations

from shield.hidden_content import HtmlScan, Segment, _join
from shield.schemas import DiffSegment, VisibleVsRaw
from shield.textnorm import invisible_runs, strip_invisible

MAX_VIEW_CHARS = 200_000


def plain_segments(text: str) -> list[Segment]:
    """Segments for a plain-text body: visible text, plus decoded Unicode Tags as HC-06."""
    segs = [Segment(strip_invisible(text or ""))]
    for run in invisible_runs(text or ""):
        if run.decoded.strip():
            segs.append(Segment(run.decoded, "HC-06"))
    return segs


def build(scan: HtmlScan | None, plain: str | None, plain_differs: bool) -> VisibleVsRaw:
    """Combine the HTML scan (if any) and the plain-text part into the two views and their diff.

    With an HTML part, the views follow the HTML (what an email app renders). If the plain part
    differs materially (HC-12), it is added to raw_view, because many AI tools read text/plain.
    Without an HTML part, the plain text is the message.
    """
    if scan is not None:
        segments = list(scan.segments)
        if plain and plain_differs:
            segments.append(Segment(strip_invisible(plain), "HC-12"))
    else:
        segments = plain_segments(plain or "")
    visible = _join(s.text for s in segments if s.hc_id is None)[:MAX_VIEW_CHARS]
    raw = _join(s.text for s in segments)[:MAX_VIEW_CHARS]
    diff: list[DiffSegment] = []
    for s in segments:
        text = " ".join(s.text.split())
        if s.hc_id and text:
            if diff and diff[-1].hc_id == s.hc_id:
                diff[-1] = DiffSegment(text=f"{diff[-1].text} {text}"[:2000], hc_id=s.hc_id)
            else:
                diff.append(DiffSegment(text=text[:2000], hc_id=s.hc_id))
    return VisibleVsRaw(visible_text=visible, raw_text=raw, diff=diff)
