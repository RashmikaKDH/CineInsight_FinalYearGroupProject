"""
llm_aspect_extractor.py
-----------------------
Production-safe LLM aspect extractor using google-genai (google.genai) package.

Quota-efficient design:
  - Character-limited batches (MAX_CHARS_PER_REQUEST) instead of fixed segment counts.
  - Asks Gemini to return ONLY non-general segments, skipping filler/greetings.
  - Assigns ["general"] locally by default; LLM output only overrides clear matches.
  - Structured JSON output via response_mime_type + response_schema.
  - Exponential backoff + jitter on 429 / 503 / transient errors.
  - Falls back to keyword extractor if LLM cannot complete.

Toggle: set USE_LLM_EXTRACTOR in main.py.
"""

import json
import logging
import os
import random
import re
import time
from typing import Optional

try:
    from google import genai
    from google.genai import types as genai_types
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (overridable via environment variables)
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
MODEL_NAME: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

VALID_ASPECTS = frozenset({
    "acting", "plot", "cgi", "direction", "music", "dialogue", "general",
})
# Aspects the LLM is allowed to return (never ask it to return "general")
_LLM_ASPECTS = frozenset(VALID_ASPECTS - {"general"})

MAX_CHARS_PER_REQUEST: int = 7000
MAX_RETRIES: int = 4
BASE_BACKOFF_SECONDS: float = 3.0
REQUEST_GAP_SECONDS: float = 2.5
MAX_SEGMENT_CHARS: int = 1200

# ---------------------------------------------------------------------------
# Retryable error patterns (case-insensitive match on error string)
# ---------------------------------------------------------------------------
_RETRYABLE_PATTERNS = re.compile(
    r"429|resource_exhausted|quota|rate.?limit|503|service.?unavailable"
    r"|deadline.?exceeded|timeout|temporarily.?unavailable",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Response schema for structured output
# ---------------------------------------------------------------------------
_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["index", "aspects"],
        "properties": {
            "index": {"type": "integer"},
            "aspects": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": sorted(_LLM_ASPECTS),
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_text(text) -> str:
    """Normalize whitespace and safely cap to MAX_SEGMENT_CHARS."""
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text[:MAX_SEGMENT_CHARS]


def _make_batches(segments: list) -> list[list[dict]]:
    """
    Group segments into character-limited batches.
    Stores original_index in each item so we can map results back.
    Empty-text segments are excluded from batches (they get ["general"] by default).
    Returns a list of batches; each batch is a list of dicts with
    keys: original_index, text.
    """
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars: int = 0

    for i, seg in enumerate(segments):
        text = _clean_text(seg.get("text", ""))
        if not text:
            continue
        row_len = len(str(i)) + 2 + len(text) + 1  # "N: text\n"
        if current_batch and current_chars + row_len > MAX_CHARS_PER_REQUEST:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append({"original_index": i, "text": text})
        current_chars += row_len

    if current_batch:
        batches.append(current_batch)

    return batches


def _build_prompt(batch: list[dict]) -> str:
    """
    Concise prompt that instructs the model to return only clearly relevant segments.
    """
    rows = "\n".join(f'{item["original_index"]}: "{item["text"]}"' for item in batch)
    allowed = ", ".join(sorted(_LLM_ASPECTS))
    return (
        f"You are a movie-review analyst. "
        f"Classify each numbered transcript segment into one or more of these aspects: {allowed}.\n"
        f"Rules:\n"
        f"- Return ONLY segments with clearly relevant movie-review content.\n"
        f"- Omit generic greetings, sponsor messages, filler, unrelated statements, and uncertain cases.\n"
        f"- Use only the exact labels listed above.\n"
        f"- Return a JSON array. Each entry: {{\"index\": <int>, \"aspects\": [<label>, ...]}}.\n"
        f"- If no segment qualifies, return an empty array [].\n\n"
        f"Segments:\n{rows}"
    )


def _is_retryable(error: Exception) -> bool:
    return bool(_RETRYABLE_PATTERNS.search(str(error)))


def _parse_response(
    response_text: Optional[str],
    valid_indices: set[int],
) -> dict[int, list[str]]:
    """
    Parse Gemini JSON response into {original_index: [aspects]} dict.
    Defensively handles markdown fences, malformed entries, invalid indices/aspects.
    """
    if not response_text:
        return {}

    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    # Locate outer JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return {}
    text = text[start : end + 1]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM response JSON parse failed; treating as empty.")
        return {}

    if not isinstance(parsed, list):
        return {}

    result: dict[int, list[str]] = {}
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        aspects_raw = entry.get("aspects", [])
        if not isinstance(idx, int) or idx not in valid_indices:
            continue
        if not isinstance(aspects_raw, list):
            continue
        # Validate, strip "general" from LLM output, deduplicate
        clean = list(dict.fromkeys(
            a for a in aspects_raw
            if isinstance(a, str) and a in _LLM_ASPECTS
        ))
        if clean:
            result[idx] = clean

    return result


def _call_with_retry(
    client,
    prompt: str,
    batch_num: int,
    total_batches: int,
) -> Optional[str]:
    """Call Gemini with exponential backoff; returns response text or None on final failure."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                    max_output_tokens=2048,
                ),
            )
            logger.info(
                "Batch %d/%d completed (attempt %d).",
                batch_num, total_batches, attempt + 1,
            )
            return response.text if response and response.text else None

        except Exception as e:
            err_str = str(e)
            if GEMINI_API_KEY and GEMINI_API_KEY in err_str:
                err_str = err_str.replace(GEMINI_API_KEY, "[REDACTED]")

            if _is_retryable(e):
                if attempt < MAX_RETRIES:
                    delay = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1.5)
                    logger.warning(
                        "Batch %d/%d transient error (attempt %d/%d), retrying in %.1fs: %s",
                        batch_num, total_batches, attempt + 1, MAX_RETRIES + 1,
                        delay, err_str[:120],
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    "Batch %d/%d quota/rate error after %d retries.",
                    batch_num, total_batches, MAX_RETRIES + 1,
                )
                raise RuntimeError(
                    f"Gemini quota or rate-limit error on batch {batch_num}/{total_batches}."
                ) from e
            else:
                logger.error(
                    "Batch %d/%d non-retryable error: %s",
                    batch_num, total_batches, err_str[:200],
                )
                raise RuntimeError(
                    f"Gemini API error on batch {batch_num}/{total_batches} (non-retryable)."
                ) from e

    return None  # Should not reach here


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def extract_aspects_from_segments_llm(transcript_segments: list) -> list:
    """
    Classify transcript segments into movie aspects using Gemini.

    Args:
        transcript_segments: list of dicts with keys: segment_id, start, end, text

    Returns:
        Shallow copies of each segment with "aspects" key added.

    Raises:
        RuntimeError: only if the very first batch fails with no results at all.
                      main.py catches this and falls back to keyword extraction.
    """
    if not _GENAI_AVAILABLE:
        raise RuntimeError(
            "google-genai package is not installed. Run: pip install google-genai"
        )

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set."
        )

    # Shallow copy all segments; pre-assign ["general"] to every one
    output_segments = [dict(seg, aspects=["general"]) for seg in transcript_segments]

    batches = _make_batches(transcript_segments)
    if not batches:
        logger.info("No text segments to classify via LLM; all assigned ['general'].")
        return output_segments

    client = genai.Client(api_key=GEMINI_API_KEY)
    total_batches = len(batches)
    logger.info("LLM aspect extraction: %d segments, %d batch(es).", len(transcript_segments), total_batches)

    any_success = False
    first_batch_error: Optional[Exception] = None

    for batch_idx, batch in enumerate(batches):
        batch_num = batch_idx + 1
        valid_indices = {item["original_index"] for item in batch}
        prompt = _build_prompt(batch)

        try:
            response_text = _call_with_retry(client, prompt, batch_num, total_batches)
            if response_text:
                classifications = _parse_response(response_text, valid_indices)
                for orig_idx, aspects in classifications.items():
                    output_segments[orig_idx]["aspects"] = aspects
                any_success = True
            else:
                logger.warning("Batch %d/%d returned empty response.", batch_num, total_batches)

        except RuntimeError as e:
            if batch_idx == 0 and not any_success:
                first_batch_error = e
                break
            else:
                err_str = str(e)
                if GEMINI_API_KEY and GEMINI_API_KEY in err_str:
                    err_str = err_str.replace(GEMINI_API_KEY, "[REDACTED]")
                logger.warning(
                    "Batch %d/%d failed after earlier batches succeeded; "
                    "leaving those segments as ['general']. Error: %s",
                    batch_num, total_batches, err_str[:120],
                )

        # Gap between requests (skip after final batch)
        if batch_num < total_batches:
            time.sleep(REQUEST_GAP_SECONDS)

    if not any_success and first_batch_error is not None:
        raise first_batch_error

    return output_segments
