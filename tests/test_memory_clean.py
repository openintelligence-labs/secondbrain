"""OCR cleaner + substantive-text gate."""
from __future__ import annotations

from secondbrain.memory.clean import (
    content_hash,
    looks_substantive,
    strip_chrome,
)


def test_strip_chrome_drops_menu_bar_lines():
    raw = (
        "Chrome File Edit View History Bookmarks Profiles Tab Window Help\n"
        "Snowflake quarterly review with Sam at 3pm tomorrow.\n"
    )
    out = strip_chrome(raw)
    assert "Snowflake quarterly review" in out
    assert "File Edit View" not in out


def test_strip_chrome_drops_secondbrain_ui_labels():
    """The recursive-extraction bug — if SB's own panel is captured, the
    UI labels must be stripped so they don't end up in memory."""
    raw = (
        "Timeline Search Digest Commitments People Settings\n"
        "DENSITY PER HOUR DRAG TO SCOPE DOUBLE-CLICK TO RESET\n"
        "Reviewed Linda's PR feedback line by line.\n"
    )
    out = strip_chrome(raw)
    assert "Reviewed Linda's PR feedback line by line." in out
    assert "Timeline" not in out
    assert "DENSITY PER HOUR" not in out


def test_strip_chrome_drops_clock_lines():
    raw = "Tue May 12 11:55 PM\nReal content here that should survive."
    out = strip_chrome(raw)
    assert "Real content here that should survive." in out
    assert "Tue May 12" not in out


def test_strip_chrome_compresses_glyph_noise():
    raw = "• · ◊ • | * |• • Real content survives."
    out = strip_chrome(raw)
    assert "Real content survives." in out


def test_looks_substantive_accepts_real_prose():
    assert looks_substantive("I'll send the doc tomorrow.") is True
    assert looks_substantive("Reviewed Linda's PR feedback line by line.") is True


def test_looks_substantive_rejects_short_or_noisy():
    assert looks_substantive("") is False
    assert looks_substantive("A B C") is False              # too few words
    assert looks_substantive("a b c d e") is False           # avg word len < 2.5
    assert looks_substantive("• · ◊ · ●") is False           # no alpha


def test_content_hash_is_whitespace_insensitive():
    a = content_hash("Sam will ship by Friday.")
    b = content_hash("Sam   will  ship   by  Friday.")
    c = content_hash("sam will ship by friday.")
    assert a == b == c


def test_content_hash_changes_with_content():
    a = content_hash("Sam will ship by Friday.")
    b = content_hash("Sam will ship by Monday.")
    assert a != b


def test_strip_chrome_idempotent():
    raw = "Chrome File Edit View History\nSnowflake review tomorrow."
    once = strip_chrome(raw)
    twice = strip_chrome(once)
    assert once == twice
