"""
Tokenization for chat moderation Layer 2.
Extracts unigrams and bigrams across all normalized text variants.
"""

import re
from typing import List, Set

from apps.chat.moderation.normalize import generate_text_variants

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9'-]+", re.UNICODE)


def extract_tokens(text: str) -> List[str]:
    """
    Extract word tokens from text, stripping surrounding punctuation.
    """
    raw_tokens = TOKEN_PATTERN.findall(text)
    clean_tokens: List[str] = []
    for token in raw_tokens:
        t = token.strip("'-")
        if t:
            clean_tokens.append(t)
    return clean_tokens


def get_lookup_keys(text: str) -> Set[str]:
    """
    Generate all unigram and bigram lookup keys across all normalized variants.
    Rule: Normalization only adds lookup keys, never removes them.
    """
    keys: Set[str] = set()
    if not text:
        return keys

    variants = generate_text_variants(text)

    for variant in variants:
        tokens = extract_tokens(variant)

        # Unigrams
        for token in tokens:
            keys.add(token)

            # If token contains internal punctuation/separators, also split and combine
            if "-" in token:
                sub_parts = [p.strip() for p in token.split("-") if p.strip()]
                for p in sub_parts:
                    keys.add(p)
                keys.add(" ".join(sub_parts))
                keys.add("".join(sub_parts))

        # Bigrams
        for i in range(len(tokens) - 1):
            bigram = f"{tokens[i]} {tokens[i+1]}"
            keys.add(bigram)

    return keys
