"""
youtube_search.py
-----------------
Searches YouTube using the official YouTube Data API v3.
Returns top N movie review video metadata.

Never uses yt-dlp for searching — only Google API client.
"""

import os
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ---------------------------------------------------------------------------
# Duration converter: ISO 8601 → human-readable string (e.g. "12:34")
# ---------------------------------------------------------------------------

def _parse_iso8601_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (PT12M34S) to MM:SS or H:MM:SS string."""
    import re
    if not iso_duration:
        return "N/A"
    pattern = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
    match = pattern.match(iso_duration)
    if not match:
        return "N/A"
    hours   = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


# ---------------------------------------------------------------------------
# Published date formatter: ISO 8601 → "Aug 5, 2025"
# ---------------------------------------------------------------------------

def _format_published(iso_date: str) -> str:
    """Convert ISO 8601 date string to a readable date."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return iso_date[:10] if iso_date else "Unknown"


# ---------------------------------------------------------------------------
# Layer 1 pre-filter: reject non-Latin script titles at API level
# (Hindi/Devanagari, Tamil, Telugu, Sinhala, Korean, Japanese, Arabic, etc.)
# ---------------------------------------------------------------------------

import re as _re

_NON_LATIN_PATTERN = _re.compile(
    r'[\u0900-\u0DFF'   # Devanagari, Tamil, Sinhala, etc.
    r'\u0E00-\u0E7F'    # Thai
    r'\u3040-\u30FF'    # Hiragana / Katakana
    r'\u3400-\u9FFF'    # CJK (Chinese, Japanese, Korean)
    r'\u0600-\u06FF'    # Arabic
    r'\u0400-\u04FF'    # Cyrillic
    r'\uAC00-\uD7AF]'   # Hangul (Korean)
)

_NON_ENGLISH_TITLE_TAGS = _re.compile(
    r'\b(hindi|tamil|telugu|malayalam|kannada|sinhala|marathi|bengali|'
    r'punjabi|gujarati|urdu|korean|japanese|spanish|french|german|'
    r'italian|russian|chinese|bahasa|arabic|turkish|portuguese|dutch|'
    r'polish|swedish|danish|norwegian|finnish|greek|hebrew|thai|vietnamese)\b',
    flags=_re.IGNORECASE
)

_EXPLICIT_LANGUAGES_KNOWN = {
    'hi', 'ta', 'te', 'ml', 'kn', 'si', 'mr', 'bn', 'pa', 'gu', 'ur',
    'ko', 'ja', 'zh', 'zh-Hans', 'zh-Hant', 'ar', 'ru', 'es', 'fr',
    'de', 'it', 'pt', 'nl', 'pl', 'sv', 'da', 'no', 'fi', 'el', 'he',
    'th', 'vi', 'tr', 'id', 'ms', 'fa',
}


def _is_likely_english_title(title: str) -> bool:
    """Return False if the video title contains non-Latin scripts or explicit language tags."""
    if not title:
        return False
    if _NON_LATIN_PATTERN.search(title):
        return False
    if _NON_ENGLISH_TITLE_TAGS.search(title):
        return False
    return True


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def search_movie_reviews(query: str, max_results: int = 20) -> list:
    """
    Search YouTube Data API v3 for movie review videos.

    Parameters
    ----------
    query : str
        Movie name entered by the user.
    max_results : int
        Number of videos to retrieve from API (default 20).
        We request more than needed so that after title pre-filtering
        we still have enough candidates for the subtitle pipeline.

    Returns
    -------
    list of dict
        Each dict contains: video_id, title, channel, thumbnail,
        duration, published, url, audio_language.

    Raises
    ------
    ValueError
        If YOUTUBE_API_KEY environment variable is not set.
    RuntimeError
        On YouTube API quota or HTTP errors.
    """
    api_key = os.environ.get('YOUTUBE_API_KEY', '')
    if not api_key:
        raise ValueError(
            "YOUTUBE_API_KEY environment variable is not set. "
            "Set it in your .env file or system environment."
        )

    # Auto-append "movie review" if the query doesn't already mention it
    query_lower = query.lower()
    if 'review' not in query_lower:
        search_query = f"{query.strip()} movie review"
    else:
        search_query = query.strip()

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        # Step 1: Search for video IDs
        # videoCaption='closedCaption' — only return videos that have captions.
        # relevanceLanguage='en'       — bias results toward English content.
        search_response = youtube.search().list(
            q=search_query,
            part='id,snippet',
            type='video',
            maxResults=max_results,
            relevanceLanguage='en',
            videoCaption='closedCaption',   # Only videos with captions
            videoDuration='medium',         # 4–20 minutes — typical review length
        ).execute()

        video_ids = [
            item['id']['videoId']
            for item in search_response.get('items', [])
            if item['id'].get('kind') == 'youtube#video'
        ]

        if not video_ids:
            return []

        # Step 2: Batch-fetch full metadata (duration, defaultAudioLanguage, etc.)
        videos_response = youtube.videos().list(
            part='snippet,contentDetails',
            id=','.join(video_ids)
        ).execute()

        results = []
        for item in videos_response.get('items', []):
            video_id = item['id']
            snippet  = item.get('snippet', {})
            details  = item.get('contentDetails', {})

            title = snippet.get('title', '')

            # Layer 1 pre-filter: reject non-English titles immediately
            if not _is_likely_english_title(title):
                continue

            # Layer 2 pre-filter: reject videos with explicit non-English audio language
            audio_lang = snippet.get('defaultAudioLanguage', '') or ''
            if audio_lang and audio_lang.split('-')[0] in _EXPLICIT_LANGUAGES_KNOWN:
                continue

            # Pick best available thumbnail (high → medium → default)
            thumbs    = snippet.get('thumbnails', {})
            thumb_url = (
                thumbs.get('high',    {}).get('url') or
                thumbs.get('medium',  {}).get('url') or
                thumbs.get('default', {}).get('url') or
                ''
            )

            results.append({
                'video_id':       video_id,
                'title':          title,
                'channel':        snippet.get('channelTitle', ''),
                'thumbnail':      thumb_url,
                'duration':       _parse_iso8601_duration(details.get('duration', '')),
                'published':      _format_published(snippet.get('publishedAt', '')),
                'url':            f"https://www.youtube.com/watch?v={video_id}",
                'audio_language': audio_lang,
            })

        return results

    except HttpError as e:
        status = e.resp.status
        if status == 403:
            raise RuntimeError(
                "YouTube API quota exceeded or API key invalid. "
                "Check your YOUTUBE_API_KEY and daily quota in Google Cloud Console."
            ) from e
        raise RuntimeError(f"YouTube API HTTP error {status}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"YouTube search failed: {e}") from e
