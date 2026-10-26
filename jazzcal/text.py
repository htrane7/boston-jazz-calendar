"""Text helpers shared by the venue scrapers for writing short event notes."""

import re
from datetime import time as dtime

BULLETS = "–—-•*"
_SENTENCE_END = re.compile(r"[.!?][\"”’]?(?=\s|$)")
_ABBREVIATION = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Jr|Sr|St|vs|feat|No|[A-Z])\.$")
_DATELINE = re.compile(r"^[A-Z][a-z]+(?: [A-Z][a-z]+)*, [A-Z]{2}\b")  # "Boston, MA Friday..."

# Instrument names, for spotting lineup lines like "Tim Ray-piano".
INSTRUMENT = (
    r"(?:(?:solo|tenor|alto|baritone|soprano|upright|electric|acoustic)\s+)?"
    r"(?:piano|keys|keyboards?|organ|bass|drums?(?: set)?|percussion|sax(?:ophone)?s?|trumpet"
    r"|flugelhorn|trombone|guitar|vocals?|voice|vibes|vibraphone|flute|clarinet|violin"
    r"|cello|harmonica|synth(?:esizer)?s?|tenor|alto|baritone|soprano)"
)


def format_time(t: dtime) -> str:
    """7pm, 9:30pm, 11am."""
    hour = t.hour % 12 or 12
    minutes = f":{t.minute:02d}" if t.minute else ""
    return f"{hour}{minutes}{'pm' if t.hour >= 12 else 'am'}"


def first_sentence(paragraphs: list[str]) -> str | None:
    """The first sentence of the first real paragraph, or None if it isn't clear."""
    paragraph = next(
        (p for p in paragraphs if len(p) >= 60 and not p.endswith(":") and p[0] not in BULLETS),
        None,  # skip headings and bullet points
    )
    if paragraph is None or paragraph[0] in "“\"‘'" or _DATELINE.match(paragraph):
        return None  # missing, a review quote, or a press-release header
    for match in _SENTENCE_END.finditer(paragraph):
        sentence = paragraph[: match.end()]
        if _ABBREVIATION.search(sentence.rstrip("\"”’")):
            continue
        return sentence if 30 <= len(sentence) <= 250 else None
    return None
