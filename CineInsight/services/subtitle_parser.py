"""
subtitle_parser.py
------------------
Parses a WebVTT (.vtt) subtitle file into a single clean plain-text string.

Removes:
  - WEBVTT header and metadata blocks
  - Timestamp lines  (00:00:01.000 --> 00:00:04.000)
  - HTML/VTT formatting tags  (<c>, <b>, <i>, <ruby>, </c>, etc.)
  - Cue identifiers (numeric or string IDs before timestamps)
  - Duplicate consecutive lines (VTT cues overlap intentionally)
  - Extra blank lines
"""

import re


# ---------------------------------------------------------------------------
# Regex patterns compiled once at module load
# ---------------------------------------------------------------------------

_RE_TIMESTAMP  = re.compile(
    r'^\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[.,]\d{3}.*$'
)
_RE_HTML_TAG   = re.compile(r'<[^>]+>')
_RE_BLANK_LINE = re.compile(r'^\s*$')
_RE_CUE_ID     = re.compile(r'^[\w\-]+$')   # numeric or word cue identifiers


def parse_vtt_to_text(vtt_path: str) -> str:
    """
    Convert a .vtt subtitle file to a clean plain-text transcript.

    Parameters
    ----------
    vtt_path : str
        Absolute path to the .vtt file.

    Returns
    -------
    str
        Clean transcript text. Returns empty string on any error.
    """
    try:
        with open(vtt_path, encoding='utf-8', errors='replace') as f:
            raw = f.read()
    except (OSError, IOError):
        return ''

    lines = raw.splitlines()
    cleaned_lines = []
    seen_lines    = set()          # for duplicate removal

    skip_header = True             # skip everything before first blank line after WEBVTT

    for line in lines:
        # Skip the WEBVTT header block (first few lines until blank line)
        if skip_header:
            if line.strip().startswith('WEBVTT'):
                continue
            if _RE_BLANK_LINE.match(line):
                skip_header = False
            continue

        # Skip timestamp lines
        if _RE_TIMESTAMP.match(line.strip()):
            continue

        # Skip blank lines
        if _RE_BLANK_LINE.match(line):
            continue

        # Skip pure cue identifiers (e.g. "1", "2", "intro", "NOTE")
        stripped = line.strip()
        if stripped.startswith('NOTE') or stripped.startswith('STYLE'):
            continue
        if _RE_CUE_ID.match(stripped) and len(stripped) < 20:
            # Likely a cue number, not actual speech
            try:
                int(stripped)
                continue
            except ValueError:
                pass

        # Remove HTML/VTT inline tags
        text = _RE_HTML_TAG.sub('', stripped)
        text = text.strip()

        if not text:
            continue

        # Deduplicate consecutive identical lines (VTT overlap)
        if text in seen_lines:
            continue

        # Rolling dedup window — keep last 5 unique lines in memory
        seen_lines.add(text)
        if len(seen_lines) > 5:
            seen_lines.pop()

        cleaned_lines.append(text)

    return ' '.join(cleaned_lines)
