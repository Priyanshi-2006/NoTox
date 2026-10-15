"""
Text normalization for chat moderation Layer 2.
Variants: lowercase, NFKC, strip zero-width characters, collapse long repeats,
de-leet, and join spaced-out letters.

Rule: Normalization only adds lookup keys, never removes them.
Extra variants can only raise the 'uncertain' rate, never lower it.
"""

import re
import unicodedata
from typing import List, Set

# Zero-width / invisible characters:
# U+200B (Zero-width space), U+200C (ZWNJ), U+200D (ZWJ), U+FEFF (BOM/ZWNBSP),
# U+00AD (Soft hyphen), U+2060 (Word joiner), U+200E / U+200F (LTR/RTL marks)
ZERO_WIDTH_REGEX = re.compile(r"[\u200b-\u200d\ufeff\u00ad\u2060\u200e\u200f]")

# Collapse 3 or more repeated characters to 1 (e.g. "fuuuuck" -> "fuck")
REPEATS_3_REGEX = re.compile(r"(.)\1{2,}", re.IGNORECASE)
# Collapse 2 or more repeated characters to 1 (e.g. "fuuck" -> "fuck")
REPEATS_2_REGEX = re.compile(r"(.)\1+", re.IGNORECASE)

# Spaced-out letters (e.g. "f u c k" or "f-u-c-k" or "f.u.c.k" -> "fuck")
SPACED_LETTERS_REGEX = re.compile(r"(?<=\b[a-zA-Z0-9])[\s._-]+(?=[a-zA-Z0-9]\b)")

# Leetspeak translation tables
LEET_PRIMARY = str.maketrans({
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "@": "a",
    "5": "s",
    "$": "s",
    "7": "t",
    "+": "t",
    "8": "b",
    "!": "i",
})

LEET_SECONDARY = str.maketrans({
    "1": "l",
    "|": "i",
    "v": "u",
})


def nfkc_normalize(text: str) -> str:
    """Normalize text using Unicode NFKC form."""
    return unicodedata.normalize("NFKC", text)


def strip_zero_width(text: str) -> str:
    """Strip zero-width and invisible formatting characters."""
    return ZERO_WIDTH_REGEX.sub("", text)


def collapse_long_repeats(text: str) -> str:
    """Collapse 3+ repeated characters down to 1."""
    return REPEATS_3_REGEX.sub(r"\1", text)


def collapse_all_repeats(text: str) -> str:
    """Collapse 2+ repeated characters down to 1."""
    return REPEATS_2_REGEX.sub(r"\1", text)


def de_leet(text: str, alt: bool = False) -> str:
    """Translate common leetspeak substitutions to alphabetic characters."""
    trans = LEET_SECONDARY if alt else LEET_PRIMARY
    return text.translate(trans)


def join_spaced_letters(text: str) -> str:
    """Join spaced-out letters like 'f u c k' -> 'fuck'."""
    return SPACED_LETTERS_REGEX.sub("", text)


def generate_text_variants(text: str) -> Set[str]:
    """
    Generate all normalized variants of the given text.
    Every variant is an addition to the candidate search space.
    """
    variants: Set[str] = set()
    if not text:
        return variants

    # 1. Raw lowercased
    raw_lower = text.lower()
    variants.add(raw_lower)

    # 2. NFKC normalized
    nfkc = nfkc_normalize(text).lower()
    variants.add(nfkc)

    # 3. Strip zero-width chars
    clean_zw = strip_zero_width(nfkc)
    variants.add(clean_zw)

    # 4. Spaced-out letters joined
    joined = join_spaced_letters(clean_zw)
    variants.add(joined)

    # 5. Repeats collapsed (from clean and from joined)
    rep3 = collapse_long_repeats(clean_zw)
    rep2 = collapse_all_repeats(clean_zw)
    variants.add(rep3)
    variants.add(rep2)

    rep3_joined = collapse_long_repeats(joined)
    variants.add(rep3_joined)

    # 6. De-leeted variants
    deleet1 = de_leet(clean_zw, alt=False)
    deleet2 = de_leet(clean_zw, alt=True)
    variants.add(deleet1)
    variants.add(deleet2)

    # 7. Combinations (de-leet + join + collapse repeats)
    combo = collapse_long_repeats(join_spaced_letters(de_leet(clean_zw, alt=False)))
    variants.add(combo)

    combo2 = collapse_all_repeats(join_spaced_letters(de_leet(clean_zw, alt=False)))
    variants.add(combo2)

    combo_alt = collapse_long_repeats(join_spaced_letters(de_leet(clean_zw, alt=True)))
    variants.add(combo_alt)

    return variants
