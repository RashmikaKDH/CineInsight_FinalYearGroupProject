"""
language_detector.py
--------------------
Language detection using fasttext-langdetect (ftlangdetect).

This package wraps the fastText lid.176.bin model with a pre-compiled
Windows-compatible binary — no C++ Build Tools required.

API:
    from ftlangdetect import detect
    result = detect("some text")
    # Returns: {'lang': 'en', 'score': 0.92}

We accept a video only when result['lang'] == 'en'.
Model file is downloaded automatically on first use by ftlangdetect.
"""


class LanguageDetector:
    """
    Wraps ftlangdetect for English language detection.

    The underlying fastText model is managed automatically by the
    ftlangdetect package — no manual model path needed.
    """

    def __init__(self):
        try:
            from ftlangdetect import detect as _detect
            self._detect = _detect
            # Warm-up call to trigger model download on first use
            self._detect("warmup", low_memory=False)
        except ImportError as e:
            raise RuntimeError(
                "fasttext-langdetect package is not installed. "
                "Run: pip install fasttext-langdetect"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize language detector: {e}"
            ) from e

    def is_english(self, text: str) -> bool:
        """
        Predict whether the given text is English.

        Parameters
        ----------
        text : str
            Transcript text. First 500 characters are used for speed.

        Returns
        -------
        bool
            True if detected language is English, False otherwise.
        """
        if not text or not text.strip():
            return False

        sample = text[:500].replace('\n', ' ').strip()

        try:
            result = self._detect(sample, low_memory=False)
            return result.get('lang') == 'en'
        except Exception:
            return False

    def detect_language(self, text: str) -> str:
        """
        Return the raw detected language code (e.g. 'en', 'hi', 'ta').
        Returns 'unknown' on failure.
        """
        if not text or not text.strip():
            return 'unknown'
        try:
            sample = text[:500].replace('\n', ' ').strip()
            result = self._detect(sample, low_memory=False)
            return result.get('lang', 'unknown')
        except Exception:
            return 'unknown'


# ---------------------------------------------------------------------------
# Module-level singleton — created once, reused across all requests
# ---------------------------------------------------------------------------

_detector_instance: LanguageDetector | None = None


def get_detector() -> LanguageDetector:
    """
    Return the shared LanguageDetector singleton.
    Creates it on first call; returns the cached instance on subsequent calls.
    No model path argument needed — ftlangdetect manages the model internally.
    """
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = LanguageDetector()
    return _detector_instance
