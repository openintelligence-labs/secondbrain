"""OCR text hygiene for the memory pipeline.

Apple Vision OCRs the entire screen, so `strip_chrome` removes UI scaffolding
and `looks_substantive` gates what's left. Both are deliberately conservative:
a slightly noisy memory beats a missing one.
"""

from __future__ import annotations

import re

_MENU_BAR_TOKENS = {
    "File",
    "Edit",
    "View",
    "Window",
    "Help",
    "Format",
    "Bookmarks",
    "History",
    "Profiles",
    "Tab",
    "Selection",
    "Find",
    "Go",
    "Develop",
    "Debug",
    "Tools",
    "Insert",
    "Table",
    "Image",
    "Object",
    "Arrange",
    "Modify",
    "Animation",
    "Recording",
    "Playback",
}

# SecondBrain's own UI labels, stripped in case the daemon captures its own
# window despite the deny-list.
_SB_CHROME = re.compile(
    r"\b("
    r"Timeline|Search|Digest|Commitments|People|Settings|"
    r"DENSITY PER HOUR|DRAG TO SCOPE|DOUBLE.CLICK TO RESET|"
    r"LOCAL.FIRST|MEMORY \d+:\d\d|"
    r"OPEN|DONE|BROKEN|"
    r"filter today|themes|broken promises|follow.ups"
    r")\b",
    re.IGNORECASE,
)

# Clock-style timestamps the OS draws in the menu bar.
_CLOCK_LINE = re.compile(
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+"
    r"\d{1,2}:\d{2}\s*(AM|PM)?",
    re.IGNORECASE,
)

# OCR garbage runs: glyph stretches with no alphabetic neighbors, e.g.
# "Q 8 • Md •| * |• Cas M".
_GLYPH_NOISE = re.compile(
    r"(?:^|\s)[•·◊◇○●▪|*+]+(?:\s+[•·◊◇○●▪|*+]+){2,}",
)


def strip_chrome(text: str) -> str:
    """Return text with menu-bar / clock / glyph-noise tokens removed.

    Idempotent.
    """
    if not text:
        return text

    out_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if tokens and len(tokens) <= 10:
            menu_ratio = sum(1 for t in tokens if t in _MENU_BAR_TOKENS) / len(tokens)
            if menu_ratio >= 0.5:
                continue
        if _CLOCK_LINE.search(stripped):
            stripped = _CLOCK_LINE.sub("", stripped).strip()
            if not stripped:
                continue
        if _SB_CHROME.search(stripped):
            stripped = _SB_CHROME.sub("", stripped).strip()
            if not stripped:
                continue
        stripped = _GLYPH_NOISE.sub(" ", stripped).strip()
        if stripped:
            out_lines.append(stripped)
    return "\n".join(out_lines)


def looks_substantive(text: str, *, min_words: int = 4) -> bool:
    """Return True if `text` has enough non-chrome content to be worth ingesting.

    Requires `min_words` alphabetic tokens averaging ≥ 2.5 characters — roughly
    the threshold between prose and OCR confetti.
    """
    if not text:
        return False
    words = [w for w in text.split() if any(c.isalpha() for c in w)]
    if len(words) < min_words:
        return False
    avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
    return not avg_word_len < 2.5


def content_hash(text: str) -> str:
    """Stable fingerprint of cleaned text for cross-capture dedup.

    Whitespace and case are normalized first so OCR jitter doesn't defeat it.
    """
    import hashlib

    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
