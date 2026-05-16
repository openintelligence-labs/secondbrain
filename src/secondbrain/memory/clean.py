"""OCR text hygiene for the memory pipeline.

Two passes:

  1. `strip_chrome(text)` — remove menu-bar tokens ("File Edit View..."),
     timestamps that match the OS clock, and other UI scaffolding that's
     never actual content. Apple Vision OCRs the entire screen, so without
     this step we'd extract memories from app chrome.

  2. `looks_substantive(text)` — heuristic gate. If after stripping there
     isn't enough body text left, return False and the pipeline skips
     ingest entirely.

Both are conservative — bias toward keeping content. We'd rather a slightly
noisy memory than a missing one.
"""
from __future__ import annotations

import re

# Common menu-bar tokens — these always sit at the top of the screen and
# never carry useful information. Apple's menu bar layout: app name + File
# Edit View … Help, plus a hidden Apple menu.
_MENU_BAR_TOKENS = {
    "File", "Edit", "View", "Window", "Help", "Format", "Bookmarks",
    "History", "Profiles", "Tab", "Selection", "Find", "Go", "Develop",
    "Debug", "Tools", "Insert", "Table", "Image", "Object", "Arrange",
    "Modify", "Animation", "Recording", "Playback",
}

# UI chrome strings the SecondBrain app itself shows — if the daemon
# accidentally captures its own window despite the deny-list, strip the
# UI labels so they don't pollute memory.
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

# Common OCR garbage runs: long stretches of single chars / glyphs with no
# alphabetic neighbors. E.g. "Q 8 • Md •| * |• Cas M".
_GLYPH_NOISE = re.compile(
    r"(?:^|\s)[•·◊◇○●▪|*+]+(?:\s+[•·◊◇○●▪|*+]+){2,}",
)


def strip_chrome(text: str) -> str:
    """Return text with menu-bar / clock / glyph-noise tokens removed.

    Single-pass and idempotent — calling twice gives the same result as once.
    """
    if not text:
        return text

    out_lines: list[str] = []
    for line in text.splitlines():
        # Drop lines that are mostly menu-bar tokens.
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if tokens and len(tokens) <= 10:
            menu_ratio = sum(1 for t in tokens if t in _MENU_BAR_TOKENS) / len(tokens)
            if menu_ratio >= 0.5:
                continue
        # Drop clock lines.
        if _CLOCK_LINE.search(stripped):
            stripped = _CLOCK_LINE.sub("", stripped).strip()
            if not stripped:
                continue
        # Drop our own UI labels (defense in depth — deny-list should already
        # block self-captures, but if SecondBrain.app is screenshotted by
        # another app's window peeking, this still strips it).
        if _SB_CHROME.search(stripped):
            stripped = _SB_CHROME.sub("", stripped).strip()
            if not stripped:
                continue
        # Compress glyph noise runs.
        stripped = _GLYPH_NOISE.sub(" ", stripped).strip()
        if stripped:
            out_lines.append(stripped)
    return "\n".join(out_lines)


def looks_substantive(text: str, *, min_words: int = 4) -> bool:
    """Return True if `text` has enough non-chrome content to be worth ingesting.

    Conservative — bias toward keeping content. We require at least
    `min_words` alphabetic tokens whose average length is ≥ 2.5 characters,
    which is roughly the threshold between real prose and OCR confetti.
    """
    if not text:
        return False
    words = [w for w in text.split() if any(c.isalpha() for c in w)]
    if len(words) < min_words:
        return False
    avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
    if avg_word_len < 2.5:
        return False
    return True


def content_hash(text: str) -> str:
    """Stable fingerprint of cleaned text for cross-capture dedup.

    Normalizes whitespace + case before hashing so OCR jitter ("File  Edit"
    vs "File Edit") doesn't defeat the dedup check.
    """
    import hashlib
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
