"""
llm_aspect_extractor.py
-----------------------
LLM-based movie aspect extractor using Google Gemini API.

Switch between LLM and keyword extraction by changing USE_LLM_EXTRACTOR
in main.py -- no changes needed here.

Valid aspects: acting, plot, cgi, direction, music, dialogue, general
"""

import os
import json

try:
    import google.generativeai as genai
except ImportError:
    genai = None

# ---------------------------------------------------------------------------
# Gemini API Key -- same pattern as YOUTUBE_API_KEY in app.py
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

# Batch size: number of segments per single Gemini API call
_BATCH_SIZE = 10

VALID_ASPECTS = {"acting", "plot", "cgi", "direction", "music", "dialogue", "general"}


def _build_prompt(segments_batch: list) -> str:
    """Build a single prompt for a batch of transcript segments."""
    lines = []
    for i, seg in enumerate(segments_batch):
        text = seg.get("text", "").strip()
        lines.append(f'Segment {i}: "{text}"')

    segments_text = "\n".join(lines)

    prompt = f"""You are a film review analyst. Classify each transcript segment below into one or more of these movie review aspects:
- acting: mentions of actors, performances, cast
- plot: story, script, narrative, writing
- cgi: visual effects, animation, graphics, VFX
- direction: director, filmmaking, cinematography, pacing
- music: soundtrack, score, songs, background music
- dialogue: spoken lines, conversations, script dialogue
- general: anything that does not clearly fit any of the above

For EACH segment, return a JSON object with the segment index and its aspects list.
Return ONLY a valid JSON array, no markdown, no explanation.

Example output:
[
  {{"index": 0, "aspects": ["acting"]}},
  {{"index": 1, "aspects": ["plot", "dialogue"]}},
  {{"index": 2, "aspects": ["general"]}}
]

Segments to classify:
{segments_text}
"""
    return prompt


def _parse_response(response_text: str, batch_size: int) -> list:
    """Parse Gemini JSON response into a list of aspect lists."""
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    parsed = json.loads(text)

    aspect_map = {}
    for item in parsed:
        idx = item.get("index", -1)
        aspects = item.get("aspects", ["general"])
        valid = [a for a in aspects if a in VALID_ASPECTS]
        aspect_map[idx] = valid if valid else ["general"]

    return [aspect_map.get(i, ["general"]) for i in range(batch_size)]


def extract_aspects_from_segments_llm(transcript_segments: list) -> list:
    """
    Classify transcript segments into movie aspects using Gemini LLM.

    Args:
        transcript_segments: list of segment dicts with keys:
                             segment_id, start, end, text

    Returns:
        Same list with 'aspects' key added to each segment.

    Raises:
        RuntimeError: if Gemini API is unavailable or the call fails.
                      Caught in main.py to send SSE aspect_error event.
    """
    if genai is None:
        raise RuntimeError(
            "google-generativeai package is not installed. "
            "Run: pip install google-generativeai"
        )

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Set it as an environment variable: $env:GEMINI_API_KEY='your_key'"
        )

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    analyzed_segments = []

    for batch_start in range(0, len(transcript_segments), _BATCH_SIZE):
        batch = transcript_segments[batch_start: batch_start + _BATCH_SIZE]

        try:
            prompt = _build_prompt(batch)
            response = model.generate_content(prompt)
            aspects_list = _parse_response(response.text, len(batch))
        except Exception as e:
            raise RuntimeError(f"Gemini API call failed: {e}") from e

        for seg, aspects in zip(batch, aspects_list):
            seg["aspects"] = aspects
            analyzed_segments.append(seg)

    return analyzed_segments
