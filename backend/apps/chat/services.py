from datetime import datetime
from typing import List, Optional
import re

from better_profanity import profanity

from apps.chat.models import ChatMessage, ModerationLog


# Load the default profanity word list, excluding ordinary dictionary words like "kill"
# whose potential harm is entirely contextual/intent-based and must be interpreted
# semantically by Layer 3 (Gemini / AI) rather than blindly blocked at Layer 1.
profanity.load_censor_words()
_NON_PROFANITY_WORDS = {"kill", "howtokill"}
profanity.CENSOR_WORDSET = [
    w for w in profanity.CENSOR_WORDSET
    if str(w).lower() not in _NON_PROFANITY_WORDS
]

# ---------------------------------------------------------------------------
# Context-aware profanity detection helpers
# ---------------------------------------------------------------------------
#
# The naive `better_profanity.contains_profanity()` does word-boundary matching
# against a censor list.  This is intentionally broad for catch-all safety, but
# it produces false positives for:
#   - Profanity used as a compliment/intensifier: "you are fucking gorgeous"
#   - Profanity used as a general exclamation:    "that was fucking amazing"
#   - Idiomatic / figurative use:                 "you killed the vibe"
#
# Strategy:
#   1. First check with better_profanity.  If clean → fast-pass (no false neg.).
#   2. If flagged, run context-aware analysis:
#      a. Check for CLEAR attack patterns (profanity directed at a person/group).
#      b. Check for ALLOWED patterns (profanity as intensifier/compliment/idiom).
#      c. If clearly in an allowed pattern → override to clean.
#      d. Otherwise keep the original block.
#
# This preserves safety: we only *relax* blocks that match known-safe syntactic
# patterns; we never silently allow unknown or ambiguous patterns.

# Patterns where "fuck/fucking/fuckin" precedes a clearly positive or neutral
# adjective or achievement verb — i.e. used as an intensifier/compliment, not an attack.
_FUCK_INTENSIFIER_RE = re.compile(
    r"\b(fucking?|fuckin['']?)\s+"
    r"(gorgeous|beautiful|amazing|awesome|brilliant|incredible|fantastic|"
    r"wonderful|great|epic|perfect|stunning|lovely|delightful|excellent|"
    r"outstanding|good|nice|cool|sweet|rad|sick|lit|fire|legendary|talented|"
    r"smart|clever|creative|hilarious|funny|happy|lucky|blessed|proud|"
    r"adorable|cute|handsome|charming|dope|wild|crazy|insane|massive|huge|"
    r"impressive|spectacular|extraordinary|phenomenal|superb|unbelievable|"
    r"nailed|crushed|owned|slayed|smashed|aced|rocked|killed|destroyed|"
    r"dominated|annihilated|slapped|wrecked|handled|demolished)\b",
    re.IGNORECASE,
)

# Direct attack patterns with "fuck": "fuck you", "fuck him/her/them", "fuck off"
_FUCK_ATTACK_RE = re.compile(
    r"\bfuck\s*(you|u|him|her|them|that|this|off|out|your|ur|yourself|yourselves|y'?all)\b",
    re.IGNORECASE,
)

# Direct personal violent threats: "i will kill you", "kill yourself", "i will murder you", etc.
_VIOLENT_THREAT_RE = re.compile(
    r"\b("
    r"(i('?ll|'?m\s+going\s+to|'?m\s+gonna|\s+will|\s+wanna|\s+want\s+to|\s+gonna)?\s+)?"
    r"(fucking?\s+|totally\s+|literally\s+)?kill\s+(you|u|him|her|them|your|ur|all\s+of\s+you|everyone|y'?all)"
    r"|kill\s+your\s*self"
    r"|go\s+kill\s+your\s*self"
    r"|i('?ll|'?m\s+going\s+to|\s+will)?\s+murder\s+(you|u|him|her|them)"
    r"|i('?ll|'?m\s+going\s+to|\s+will)?\s+slit\s+your\s+throat"
    r"|i('?ll|'?m\s+going\s+to|\s+will)?\s+shoot\s+(you|u|him|her|them)"
    r"|i\s+hope\s+you\s+die"
    r"|death\s+to\s+you"
    r")\b",
    re.IGNORECASE,
)

# Ordinary non-profane words that better_profanity over-censors by default
_OVER_CENSORED_WORDS = re.compile(
    r"\b(kill|killed|kills|killing|howtokill)\b",
    re.IGNORECASE,
)

# Idiomatic / figurative uses of "kill" (not directed at a person as a threat).
_KILL_IDIOMATIC_RE = re.compile(
    r"\b(killed?|kills|killing)\s+"
    r"(it|the\s+vibe|the\s+mood|me\s+(softly|with)|time|the\s+game|"
    r"the\s+competition|the\s+show|the\s+stage|the\s+joke|the\s+moment|"
    r"the\s+beat|the\s+crowd|two\s+birds|the\s+lights|the\s+engine|"
    r"my\s+vibe|my\s+mood|my\s+buzz|the\s+hype|the\s+energy|the\s+flow|"
    r"the\s+silence|the\s+tension|the\s+atmosphere)\b",
    re.IGNORECASE,
)

# Direct personal threat with "kill": "i will kill you", "gonna kill her", etc.
_KILL_THREAT_RE = re.compile(
    r"\b(i('?ll|'?m\s+going\s+to|'?m\s+gonna|\s+will|\s+wanna|\s+want\s+to|\s+gonna)?\s+)?"
    r"kill\s+(you|u|him|her|them|your|ur|all\s+of\s+you|everyone|y'?all)\b",
    re.IGNORECASE,
)

# "ass" used in a compound/intensifier word: "badass", "kick-ass", "smartass"
_ASS_COMPOUND_RE = re.compile(
    r"\b(bad|kick|smart|wise|jack|dumb|hard|lazy|fat|tight|class|sass|"
    r"bad[-\s]?ass|kick[-\s]?ass|smart[-\s]?ass)\b",
    re.IGNORECASE,
)

# "ass" used as a direct personal insult
_ASS_INSULT_RE = re.compile(
    r"\b(you('re|re|\s+are)|what\s+an?|he('s|\s+is)|she('s|\s+is)|they('re|\s+are))\s+an?\s+ass\b",
    re.IGNORECASE,
)

# "bitch" used as a compliment/exclamation ("you're a badass bitch", "slay bitch")
_BITCH_COMPLIMENT_RE = re.compile(
    r"\b(badass|slay|fierce|queen|boss|iconic|powerful|strong|gorgeous)\s+bitch\b"
    r"|\bbitch\s+(please|you\s+slayed|slayed|queen|nailed|killed\s+it)\b",
    re.IGNORECASE,
)

# Direct "bitch" insult aimed at a person
_BITCH_INSULT_RE = re.compile(
    r"\b(you|he|she|they)\s*(are\s+a|'re\s+a|\s+is\s+a|'re|are|is)\s+bitch\b"
    r"|\bstfu\s+bitch\b|\bshut\s+up\s+bitch\b|\bfuck\s+you\s+bitch\b",
    re.IGNORECASE,
)


def _is_context_safe(content: str) -> bool:
    """
    Returns True if the content, despite being flagged by better_profanity,
    matches a known-safe linguistic pattern AND does NOT match a known-attack
    pattern.

    Only called when better_profanity has already flagged the message.
    Conservative by design: unknown or ambiguous patterns are NOT relaxed.
    """
    lower = content.lower()

    # --- "fuck/fucking" family ---
    if re.search(r"\bfuck", content, re.IGNORECASE):
        is_attack = bool(_FUCK_ATTACK_RE.search(content))
        is_intensifier = bool(_FUCK_INTENSIFIER_RE.search(content))
        if is_intensifier and not is_attack:
            return True

    # --- "kill" family ---
    if re.search(r"\bkill", content, re.IGNORECASE):
        is_threat = bool(_KILL_THREAT_RE.search(content))
        is_idiomatic = bool(_KILL_IDIOMATIC_RE.search(content))
        if is_idiomatic and not is_threat:
            return True

    # --- "ass" family ---
    if re.search(r"\bass\b", content, re.IGNORECASE):
        is_insult = bool(_ASS_INSULT_RE.search(content))
        is_compound = bool(_ASS_COMPOUND_RE.search(content))
        if is_compound and not is_insult:
            return True

    # --- "bitch" family ---
    if "bitch" in lower:
        is_insult = bool(_BITCH_INSULT_RE.search(content))
        is_compliment = bool(_BITCH_COMPLIMENT_RE.search(content))
        if is_compliment and not is_insult:
            return True

    return False


class ChatService:

    @classmethod
    def contains_profanity(cls, content: str) -> bool:
        """
        Check for explicit threats and profanities.

        1. Explicit violent personal threats (e.g. 'i will kill you', 'kill yourself')
           are ALWAYS BLOCKED.
        2. Clean text with no profanities passes immediately.
        3. Flagged text is checked for context-safe usage (compliment/praise intensifiers).

        Returns:
            True  -> violent threat / hostile profanity detected -> message should be blocked
            False -> clean, benign, or safely idiomatic -> message may proceed
        """
        # 1. Direct personal death threats and violent directives -> ALWAYS BLOCK
        if _VIOLENT_THREAT_RE.search(content):
            return True

        # 2. Quick clean path — most messages pass here without extra work.
        if not profanity.contains_profanity(content):
            return False

        # 3. If flagged ONLY due to over-censored non-profane words like 'kill' (and not a violent threat):
        cleaned_without_kill = _OVER_CENSORED_WORDS.sub("", content).strip()
        if not profanity.contains_profanity(cleaned_without_kill):
            return False

        # 4. Flagged by word-list; check whether it's a context-safe usage.
        if _is_context_safe(content):
            return False

        # Still flagged after context check → treat as profanity.
        return True

    @classmethod
    def save_message(cls, sender, content: str, blocked: bool = False) -> ChatMessage:
        return ChatMessage.objects.create(
            sender=sender,
            content=content,
            blocked=blocked,
        )

    @classmethod
    def log_moderation(
        cls,
        user,
        message: Optional[ChatMessage],
        stage: str,
        verdict: str,
        bloom_status: str,
        latency_ms: float,
        raw_text: str = "",
    ) -> ModerationLog:
        """
        Store moderation outcome. Fast-path 'clean' rows store metadata only
        (empty text) for privacy and volume. Offending text is stored only for
        flagged or blocked items.
        """
        text_to_store = raw_text if verdict in ("blocked", "flagged") else ""
        return ModerationLog.objects.create(
            user=user,
            message=message,
            stage=stage,
            verdict=verdict,
            bloom_status=bloom_status,
            latency_ms=latency_ms,
            text=text_to_store,
        )

    @classmethod
    def get_messages(cls, limit: int = 50, before: Optional[datetime] = None) -> List[ChatMessage]:
        """
        Returns the latest `limit` messages oldest-first, optionally before a cursor datetime.
        Excludes blocked messages.
        """
        queryset = ChatMessage.objects.select_related("sender").filter(blocked=False)
        if before is not None:
            queryset = queryset.filter(created_at__lt=before)

        # Query the latest `limit` messages matching the filter
        latest_messages = list(queryset.order_by("-created_at")[:limit])
        # Order oldest-first
        latest_messages.reverse()
        return latest_messages
