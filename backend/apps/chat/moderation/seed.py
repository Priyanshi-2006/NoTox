"""
Seeding logic for Bloom pre-filter Layer 2.
Loads better_profanity censor word list plus custom extras file (e.g. Romanized Hindi slurs).
"""

import os
from pathlib import Path
from typing import Iterable, List, Optional, Set

from better_profanity import profanity

from apps.chat.moderation.bloom import BaseBloomBackend, RedisBloomBackend, get_bloom_backend

# Ensure default profanity word list is loaded if not already initialized
if not getattr(profanity, "CENSOR_WORDSET", None):
    profanity.load_censor_words()

EXTRAS_FILE = Path(__file__).resolve().parent / "data" / "extras.txt"


def load_seed_tokens() -> List[str]:
    """
    Collect all toxic seed tokens from better_profanity and extras.txt.
    """
    tokens: Set[str] = set()

    # 1. Words from better_profanity
    for item in profanity.CENSOR_WORDSET:
        word = str(item).strip().lower()
        if word:
            tokens.add(word)

    # 2. Extras file (custom slurs, Romanized Hindi words, etc.)
    if EXTRAS_FILE.exists():
        with open(EXTRAS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                tokens.add(line.lower())

    # 3. Contextual sensitive tokens that must be caught by Layer 2 Bloom
    # and routed to Layer 3 (Gemini / AI) for semantic interpretation
    SENSITIVE_CONTEXTUAL_TOKENS = {
        "kill", "killed", "killing", "kills", "killer", "murder", "threat", "die", "death"
    }
    tokens.update(SENSITIVE_CONTEXTUAL_TOKENS)

    return sorted(tokens)


async def seed_bloom(
    backend: Optional[BaseBloomBackend] = None,
    tokens: Optional[Iterable[str]] = None,
) -> int:
    """
    Idempotently seed the Bloom filter backend with toxic tokens.
    """
    target_backend = backend or get_bloom_backend()

    # If Redis backend, ensure the filter is reserved first
    if isinstance(target_backend, RedisBloomBackend):
        await target_backend.reserve()

    seed_list = list(tokens) if tokens is not None else load_seed_tokens()
    added_count = await target_backend.add_many(seed_list)
    return added_count
