"""Private-person and self-harm rule.

Runs before any search, model call or public write. When it triggers, the claim is stored
privately under a generic label (none of the input text is kept) and the caller receives the
fixed PRIVATE_PERSON_MESSAGE. The check is a deliberately conservative keyword list, not a
classifier: it can miss phrasings it does not know, and it withholds some claims it did not
need to (for example a public figure's suicide). See the README limitations.

Triggers:
  * suicide / self-harm, in English, Hindi or Telugu;
  * sexual violence;
  * a crime, death or harm story about an identifiable private individual: a personal name or
    an age descriptor ("19-year-old"), with no public office or public role mentioned.
"""
import re

PRIVATE_PERSON_MESSAGE = (
    "This story involves a private individual. We do not publish verdicts on these. "
    "If you are struggling, contact Tele-MANAS at 14416."
)
WITHHELD_LABEL = "[withheld under the private-person and self-harm rule]"

_SELF_HARM = re.compile(
    r"\b(?:suicid\w*|self[- ]?harm\w*|kill(?:ed|s|ing)?\s+(?:him|her|them)sel(?:f|ves)"
    r"|took\s+(?:his|her|their)\s+own\s+li(?:fe|ves)|hang(?:ed|s)?\s+(?:him|her)self)\b"
    r"|आत्महत्या|ఆత్మహత్య",
    re.IGNORECASE,
)
_SEXUAL_VIOLENCE = re.compile(
    r"\b(?:rap(?:e|ed|es|ing|ist)|gang[- ]?rap\w*|molest\w*|pocso"
    r"|sexual(?:ly)?\s+(?:assault\w*|abus\w*|harass\w*|violence))\b|बलात्कार",
    re.IGNORECASE,
)
_HARM_EVENT = re.compile(
    r"\b(?:died|dies|dead|death|killed|murder\w*|stabbed|shot|assault\w*|attacked|beaten"
    r"|lynch\w*|kidnap\w*|abduct\w*|missing|arrested|accident|injured|fell|drowned|burn(?:ed|t))\b",
    re.IGNORECASE,
)
_AGE = re.compile(r"\b\d{1,2}[- ]?(?:year|yr)s?[- ]?old\b", re.IGNORECASE)
_PUBLIC_ROLE = re.compile(
    r"\b(?:minister|mp|mla|mlc|pm|cm|prime minister|chief minister|president|governor|speaker|mayor"
    r"|collector|commissioner|judge|justice|actor|actress|cricketer|celebrity|singer|filmmaker"
    r"|director|ceo|chairman|chairperson|spokesperson|senator|ambassador|party leader|leader of)\b",
    re.IGNORECASE,
)
_NAME_PAIR = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")
# Capitalised words that start sentences or name places, institutions and events, not people.
_NOT_A_NAME = {
    "the", "this", "that", "these", "there", "two", "three", "four", "five", "one", "alert", "breaking",
    "forward", "share", "watch", "video", "photo", "news", "india", "indian", "union", "government",
    "pradesh", "nadu", "bengal", "delhi", "new", "uttar", "andhra", "madhya", "himachal", "tamil", "west",
    "east", "north", "south", "arunachal", "high", "supreme", "court", "police", "station", "university",
    "college", "school", "hospital", "district", "city", "council", "ministry", "bank", "reserve", "world",
    "cup", "lok", "sabha", "rajya", "assembly", "party", "congress", "janata", "national", "state",
    "central", "railway", "airport", "road", "nagar", "colony", "village", "town", "temple", "mosque",
    "church", "festival", "day", "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "ganesh", "lord", "shri", "sri",
}


def _has_personal_name(text: str) -> bool:
    for first, second in _NAME_PAIR.findall(text):
        if first.lower() not in _NOT_A_NAME and second.lower() not in _NOT_A_NAME:
            return True
    return False


def check_sensitive(text: str) -> str | None:
    """Return the trigger reason ('self_harm', 'sexual_violence', 'private_individual') or None.

    Never returns or logs any part of the input text.
    """
    if not text:
        return None
    if _SELF_HARM.search(text):
        return "self_harm"
    if _SEXUAL_VIOLENCE.search(text):
        return "sexual_violence"
    if _HARM_EVENT.search(text) and (_AGE.search(text) or _has_personal_name(text)) and not _PUBLIC_ROLE.search(text):
        return "private_individual"
    return None
