import logging
import math
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from better_profanity import Profanity
from django.conf import settings

from apps.chat.services import ChatService

logger = logging.getLogger(__name__)


@dataclass
class FlaggedWordSegment:
    word: str
    start: Optional[float] = None
    end: Optional[float] = None
    has_valid_timing: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": self.start,
            "end": self.end,
            "has_valid_timing": self.has_valid_timing,
        }


@dataclass
class StreamModerationResult:
    is_flagged: bool
    flagged_words: List[str] = field(default_factory=list)
    flagged_segments: List[FlaggedWordSegment] = field(default_factory=list)
    original_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_flagged": self.is_flagged,
            "flagged_words": self.flagged_words,
            "flagged_segments": [seg.to_dict() for seg in self.flagged_segments],
            "original_text": self.original_text,
        }


@dataclass
class AudioInterval:
    start: float
    end: float
    is_speech: bool = True
    is_censored: bool = False
    is_pending: bool = True


class AudioIntervalModerator:
    """
    Coordinates timestamp-to-audio interval mapping and moderation decisions
    for live broadcast streams.
    Ensures:
    1. Profane words map to silenced intervals.
    2. Clean words map to passed intervals.
    3. Delayed moderation decisions fail closed (silenced) when playout time arrives.
    4. Surrounding clean speech in the same utterance is preserved.
    """

    def __init__(self, buffer_delay_sec: float = 1.5, padding_sec: float = 0.06):
        self.buffer_delay_sec = buffer_delay_sec
        self.padding_sec = padding_sec
        self.intervals: List[AudioInterval] = []
        self.censored_ranges: List[Tuple[float, float]] = []
        self.clean_ranges: List[Tuple[float, float]] = []

    def register_speech_interval(self, start: float, end: float) -> None:
        """Registers that speech activity was detected in the interval [start, end]."""
        self.intervals.append(
            AudioInterval(start=float(start), end=float(end), is_speech=True, is_pending=True)
        )

    def apply_moderation_result(
        self,
        words: List[Dict[str, Any]],
        flagged_segments: List[Dict[str, Any]],
    ) -> None:
        """
        Applies word-level transcript moderation decisions.
        Flags profane words for suppression and clears clean words.
        """
        flagged_words = {
            str(s.get("word", "")).lower().strip()
            for s in flagged_segments
            if s and s.get("word")
        }

        # 1. Process explicit flagged word segments with timestamps
        for seg in flagged_segments:
            s_start = seg.get("start")
            s_end = seg.get("end")
            if s_start is not None and s_end is not None and float(s_end) >= float(s_start):
                c_start = max(0.0, float(s_start) - self.padding_sec)
                c_end = float(s_end) + self.padding_sec
                self.censored_ranges.append((c_start, c_end))

        # 2. Process all recognized words
        for w in words:
            word_str = str(w.get("word", "")).lower().strip()
            w_start = w.get("start")
            w_end = w.get("end")
            if w_start is None or w_end is None:
                continue

            start_f = float(w_start)
            end_f = float(w_end)

            if word_str in flagged_words:
                c_start = max(0.0, start_f - self.padding_sec)
                c_end = end_f + self.padding_sec
                self.censored_ranges.append((c_start, c_end))
            else:
                self.clean_ranges.append((start_f, end_f))

        # 3. Update pending status of registered intervals
        for interval in self.intervals:
            for c_start, c_end in self.censored_ranges:
                if not (interval.end <= c_start or interval.start >= c_end):
                    interval.is_censored = True
                    interval.is_pending = False
            for cl_start, cl_end in self.clean_ranges:
                if not (interval.end <= cl_start or interval.start >= cl_end):
                    if not interval.is_censored:
                        interval.is_pending = False

    def should_suppress_at_playout(
        self,
        stream_time: float,
        current_wall_time: float,
        registration_wall_time: float,
    ) -> Tuple[bool, str]:
        """
        Determines whether the audio sample at stream_time should be suppressed (silenced)
        when playout occurs.
        Returns (should_suppress, reason).
        """
        # 1. Check if explicitly censored
        for c_start, c_end in self.censored_ranges:
            if c_start <= stream_time <= c_end:
                return True, "censored_profanity"

        # 2. Check if within a registered speech interval
        for interval in self.intervals:
            if interval.start <= stream_time <= interval.end:
                if interval.is_censored:
                    return True, "censored_profanity"
                if interval.is_pending:
                    # Decision is late when playout time arrives -> fail closed!
                    if current_wall_time - registration_wall_time >= self.buffer_delay_sec:
                        return True, "late_moderation_fail_closed"
                    return False, "buffering"
                return False, "clean_speech"

        # 3. Non-speech / background silence is allowed to proceed
        return False, "non_speech"

    def censor_audio_samples(
        self,
        samples: List[float],
        sample_rate: int,
        buffer_start_time: float,
        is_decision_late: bool = False,
    ) -> List[float]:
        """
        Returns a new list of audio samples where profane and late-unmoderated
        intervals are replaced with silence (0.0), and clean audio is preserved.
        """
        output = list(samples)
        for i in range(len(output)):
            t = buffer_start_time + (i / float(sample_rate))
            suppress, _ = self.should_suppress_at_playout(
                stream_time=t,
                current_wall_time=buffer_start_time + self.buffer_delay_sec if is_decision_late else buffer_start_time,
                registration_wall_time=buffer_start_time,
            )
            if suppress:
                output[i] = 0.0
        return output



class StreamModerationService:
    """
    Moderation engine for speech-to-text live transcripts.
    Uses dedicated live audio profanity wordlist while delegating to ChatService
    to preserve existing chat moderation baseline.
    """

    _audio_profanity: Optional[Profanity] = None

    @classmethod
    def _get_audio_profanity(cls) -> Profanity:
        if cls._audio_profanity is None:
            cls.load_wordlist()
        return cls._audio_profanity

    @classmethod
    def load_wordlist(cls, custom_path: Optional[str] = None) -> bool:
        """
        Loads the dedicated profanity filter for live speech moderation.
        Uses settings.PROFANITY_WORDLIST_PATH by default, falling back to built-in words.
        """
        cls._audio_profanity = Profanity()
        wordlist_path = custom_path
        if wordlist_path is None:
            try:
                wordlist_path = getattr(settings, "PROFANITY_WORDLIST_PATH", None)
            except Exception:
                wordlist_path = None

        if wordlist_path:
            try:
                resolved = Path(wordlist_path).resolve()
                if resolved.is_file():
                    cls._audio_profanity.load_censor_words_from_file(str(resolved))
                    logger.info("Loaded live audio profanity wordlist from %s", resolved)
                    return True
                else:
                    msg = (
                        f"Live audio profanity wordlist not found at '{resolved}'. "
                        "Falling back to built-in censor words."
                    )
                    logger.warning(msg)
                    warnings.warn(msg, UserWarning, stacklevel=2)
            except Exception as exc:
                msg = f"Error loading live audio profanity wordlist from '{wordlist_path}': {exc}"
                logger.warning(msg)
                warnings.warn(msg, UserWarning, stacklevel=2)

        cls._audio_profanity.load_censor_words()
        return False

    @classmethod
    def contains_profanity(cls, content: str) -> bool:
        """
        Evaluates whether content contains profanity for live audio moderation.
        Checks both the dedicated audio profanity wordlist and ChatService.
        """
        if not content or not isinstance(content, str) or not content.strip():
            return False

        prof_filter = cls._get_audio_profanity()

        # Always check ChatService baseline to preserve integration
        chat_flag = False
        try:
            chat_flag = ChatService.contains_profanity(content)
        except Exception:
            chat_flag = False

        audio_flag = prof_filter.contains_profanity(content)
        return bool(chat_flag or audio_flag)

    @classmethod
    def _parse_and_validate_timing(
        cls, item: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float], bool]:
        """
        Validates timing fields from an STT word object.
        Accepts 'start' / 'start_time' and 'end' / 'end_time'.
        Requires finite, non-negative numbers where end > start.
        Returns (start, end, has_valid_timing).
        """
        raw_start = item.get("start")
        if raw_start is None:
            raw_start = item.get("start_time")

        raw_end = item.get("end")
        if raw_end is None:
            raw_end = item.get("end_time")

        if raw_start is None or raw_end is None:
            return None, None, False

        try:
            start_val = float(raw_start)
            end_val = float(raw_end)
        except (ValueError, TypeError):
            return None, None, False

        if not (math.isfinite(start_val) and math.isfinite(end_val)):
            return None, None, False

        if start_val < 0.0 or end_val <= start_val:
            return None, None, False

        return start_val, end_val, True

    @classmethod
    def moderate_transcript(
        cls,
        text: str,
        words: Optional[List[Dict[str, Any]]] = None,
    ) -> StreamModerationResult:
        """
        Evaluates a transcript string and optional word timestamps.

        Args:
            text: Transcribed speech text.
            words: Optional list of word objects with timing data, e.g.:
                   [{"word": "hello", "start": 0.0, "end": 0.5}]

        Returns:
            StreamModerationResult with moderation flag and structured segments.
        """
        if not text or not isinstance(text, str):
            return StreamModerationResult(is_flagged=False, original_text=str(text or ""))

        # Evaluate the transcript text using audio profanity filter and ChatService
        if not cls.contains_profanity(text):
            return StreamModerationResult(
                is_flagged=False,
                flagged_words=[],
                flagged_segments=[],
                original_text=text,
            )

        flagged_words: List[str] = []
        flagged_segments: List[FlaggedWordSegment] = []

        # If word objects are provided, check individual word tokens
        if words and isinstance(words, list):
            for item in words:
                if not isinstance(item, dict):
                    continue

                raw_word = item.get("word")
                if raw_word is None or not isinstance(raw_word, (str, int, float)):
                    continue

                word_str = str(raw_word).strip()
                if not word_str:
                    continue

                clean_token = word_str.strip(".,!?;:\"'()[]{}")
                is_word_prohibited = cls.contains_profanity(word_str) or (
                    bool(clean_token) and cls.contains_profanity(clean_token)
                )

                if is_word_prohibited:
                    start_val, end_val, has_valid_timing = cls._parse_and_validate_timing(item)
                    canonical_word = clean_token if clean_token else word_str
                    flagged_words.append(canonical_word)
                    flagged_segments.append(
                        FlaggedWordSegment(
                            word=canonical_word,
                            start=start_val,
                            end=end_val,
                            has_valid_timing=has_valid_timing,
                        )
                    )

        # Fallback when words were missing, empty, or failed to resolve specific tokens
        if not flagged_segments:
            for token in text.split():
                clean_token = token.strip(".,!?;:\"'()[]{}")
                if clean_token and cls.contains_profanity(clean_token):
                    flagged_words.append(clean_token)
                    flagged_segments.append(
                        FlaggedWordSegment(
                            word=clean_token,
                            start=None,
                            end=None,
                            has_valid_timing=False,
                        )
                    )

        # In case the profanity is a phrase that was not matched on individual split tokens
        if not flagged_segments:
            fallback_text = text.strip()
            flagged_words.append(fallback_text)
            flagged_segments.append(
                FlaggedWordSegment(
                    word=fallback_text,
                    start=None,
                    end=None,
                    has_valid_timing=False,
                )
            )

        # Deduplicate word strings while maintaining first-seen order
        unique_flagged_words = list(dict.fromkeys(flagged_words))

        return StreamModerationResult(
            is_flagged=True,
            flagged_words=unique_flagged_words,
            flagged_segments=flagged_segments,
            original_text=text,
        )
