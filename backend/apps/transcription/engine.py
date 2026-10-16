import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class TranscriptionEngine:
    """
    Manages loading the Vosk speech recognition model once per process
    and creates per-connection KaldiRecognizer instances with word-level
    timestamps enabled.
    """

    _model: Any = None

    @classmethod
    def get_model_path(cls) -> Path:
        model_path = getattr(settings, "VOSK_MODEL_PATH", None)
        if not model_path:
            raise ImproperlyConfigured(
                "VOSK_MODEL_PATH is not configured in Django settings."
            )
        return Path(model_path)

    @classmethod
    def get_model(cls) -> Any:
        """
        Loads the Vosk Model singleton once per process.
        Raises ImproperlyConfigured if the model folder does not exist.
        """
        if cls._model is not None:
            return cls._model

        model_path = cls.get_model_path()
        if not model_path.exists() or not model_path.is_dir():
            raise ImproperlyConfigured(
                f"Vosk model directory not found at '{model_path}'. "
                f"Please run 'python scripts/download_vosk_model.py' to download and set up the model."
            )

        try:
            import vosk
        except ImportError as exc:
            raise ImproperlyConfigured(
                "The 'vosk' package is required for transcription. "
                "Install it with 'pip install vosk'."
            ) from exc

        # Set Vosk log level to -1 to suppress Kaldi debug messages to stderr
        vosk.SetLogLevel(-1)
        logger.info("Loading Vosk Model from %s...", model_path)
        cls._model = vosk.Model(str(model_path))
        logger.info("Vosk Model successfully loaded.")
        return cls._model

    @classmethod
    def create_recognizer(cls, sample_rate: float = 16000.0) -> Any:
        """
        Creates a new KaldiRecognizer instance for a specific connection.
        Enables word-level timestamps via SetWords(True).
        """
        model = cls.get_model()
        import vosk

        recognizer = vosk.KaldiRecognizer(model, sample_rate)
        recognizer.SetWords(True)
        return recognizer

    @classmethod
    def parse_recognition_json(cls, raw_json_str: str) -> Dict[str, Any]:
        """
        Parses Vosk Result/FinalResult JSON and extracts the text
        along with standardized word-level start/end timestamps in seconds.
        """
        if not raw_json_str or not isinstance(raw_json_str, str):
            return {"text": "", "words": []}

        try:
            data = json.loads(raw_json_str)
        except (json.JSONDecodeError, TypeError):
            return {"text": "", "words": []}

        text = str(data.get("text", "")).strip()
        raw_words = data.get("result", [])

        words: List[Dict[str, Any]] = []
        if isinstance(raw_words, list):
            for item in raw_words:
                if not isinstance(item, dict):
                    continue
                w_str = str(item.get("word", "")).strip()
                if not w_str:
                    continue

                try:
                    start_val = float(item["start"])
                    end_val = float(item["end"])
                except (KeyError, ValueError, TypeError):
                    continue

                words.append({
                    "word": w_str,
                    "start": start_val,
                    "end": end_val,
                })

        return {
            "text": text,
            "words": words,
        }

    @classmethod
    def reset_model(cls) -> None:
        """Resets the singleton model instance (used in tests)."""
        cls._model = None
