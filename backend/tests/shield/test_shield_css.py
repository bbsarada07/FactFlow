"""CSS cascade used by the hidden-content detectors: specificity, !important, @media, and the
documented known misses (content hidden only on phones, only in dark mode, or inside @supports)."""
import pytest

from shield import css
from shield import hidden_content as hc

TEXT = "this sentence is the one under test"


def hidden(style: str, attrs: str = 'class="a" id="b"') -> bool:
    html = f"<html><head><style>{style}</style></head><body><p>Hello.</p><div {attrs}>{TEXT}</div></body></html>"
    scan = hc.scan_html(html)
    return TEXT not in scan.visible_text


@pytest.mark.parametrize("selector, expected", [
    ("div", (0, 0, 1)),
    (".a", (0, 1, 0)),
    ("#b", (1, 0, 0)),
    ("div.a#b", (1, 1, 1)),
    ("body > div.a span", (0, 1, 3)),
    ("a[href$='.pdf']:hover", (0, 2, 1)),
    ("p::first-line", (0, 0, 2)),
    (":not(.a) div", (0, 1, 1)),
    (":where(.a) div", (0, 0, 1)),
])
def test_specificity(selector, expected):
    assert css.specificity(selector) == expected


def test_id_beats_class_whatever_the_order():
    assert hidden(".a{display:none} #b{display:block}") is False
    assert hidden("#b{display:none} .a{display:block}") is True


def test_later_rule_wins_at_equal_specificity():
    assert hidden(".a{display:block} .a{display:none}") is True
    assert hidden(".a{display:none} .a{display:block}") is False


def test_inline_beats_stylesheet_but_not_important():
    assert hidden(".a{display:none}", 'class="a" style="display:block"') is False
    assert hidden(".a{display:none !important}", 'class="a" style="display:block"') is True
    assert hidden(".a{display:block !important}", 'class="a" style="display:none !important"') is True


@pytest.mark.parametrize("style", [
    "@media screen { .a { display:none } }",
    "@media all and (min-width: 600px) { .a { display:none } }",
    "@media only screen and (max-width: 1200px) { .a { display:none } }",
    "@media print, screen { .a { display:none } }",
    "@media (prefers-color-scheme: light) { .a { display:none } }",
])
def test_media_rules_that_apply_on_a_desktop_screen(style):
    assert hidden(style) is True


@pytest.mark.parametrize("style", [
    "@media print { .a { display:none } }",
    "@media not screen { .a { display:none } }",
])
def test_media_rules_that_do_not_apply(style):
    assert hidden(style) is False


def test_rules_after_an_at_media_block_still_apply():
    assert hidden("@media print { .x { color:red } } .a { display:none }") is True


# Known misses. These pass because the scanner evaluates a desktop screen in light mode only;
# they document behaviour that a person on a phone or in dark mode could see differently.

def test_known_miss_hidden_only_on_phones_is_not_reported():
    assert hidden("@media (max-width: 600px) { .a { display:none } }") is False


def test_known_miss_dark_mode_only_tricks_are_not_reported():
    assert hidden("@media (prefers-color-scheme: dark) { .a { display:none } }") is False


def test_known_miss_rules_inside_supports_are_ignored():
    assert hidden("@supports (display:grid) { .a { display:none } }") is False


def test_media_matches_unit():
    assert css.media_matches("") and css.media_matches("screen")
    assert not css.media_matches("print") and not css.media_matches("(max-width: 480px)")
    assert css.media_matches("(min-width: 480px) and (max-width: 1024px)")
    assert not css.media_matches("(hover: hover)")  # unknown features do not match
