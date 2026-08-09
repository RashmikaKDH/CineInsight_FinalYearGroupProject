"""
subtitle_service.py
-------------------
Downloads subtitle files (.vtt) for a YouTube video using yt-dlp.

Priority order:
  1. Manual subtitles (human-created)
  2. Auto-generated subtitles
  3. Neither → returns (None, "none")

IMPORTANT: Video/audio streams are NEVER downloaded.
Only subtitle files are retrieved.
"""

import os
import glob
import tempfile

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


class _SilentLogger:
    """Suppress all yt-dlp console output."""
    def debug(self, msg):   pass
    def warning(self, msg): pass
    def error(self, msg):   pass


def download_subtitles(video_id: str, output_dir: str) -> tuple:
    """
    Download English subtitle file for a YouTube video.

    Parameters
    ----------
    video_id : str
        YouTube video ID (e.g. "dQw4w9WgXcQ").
    output_dir : str
        Directory path where the .vtt file will be saved.

    Returns
    -------
    tuple (str | None, str)
        (vtt_file_path, subtitle_type)
        subtitle_type is one of: "manual", "auto", "none"
    """
    if yt_dlp is None:
        return (None, "none")

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    outtmpl   = os.path.join(output_dir, f"{video_id}.%(ext)s")

    # ---- Attempt 1: Manual subtitles ----------------------------------------
    manual_opts = {
        'skip_download':       True,
        'writesubtitles':      True,
        'writeautomaticsub':   False,
        'subtitleslangs':      ['en'],
        'subtitlesformat':     'vtt',
        'outtmpl':             outtmpl,
        'quiet':               True,
        'no_warnings':         True,
        'logger':              _SilentLogger(),
        'socket_timeout':      15,
    }

    try:
        with yt_dlp.YoutubeDL(manual_opts) as ydl:
            ydl.download([video_url])
    except Exception:
        pass  # Will check for file below

    vtt_path = _find_vtt_file(output_dir, video_id)
    if vtt_path:
        return (vtt_path, "manual")

    # ---- Attempt 2: Auto-generated subtitles --------------------------------
    auto_opts = {
        'skip_download':       True,
        'writesubtitles':      False,
        'writeautomaticsub':   True,
        'subtitleslangs':      ['en'],
        'subtitlesformat':     'vtt',
        'outtmpl':             outtmpl,
        'quiet':               True,
        'no_warnings':         True,
        'logger':              _SilentLogger(),
        'socket_timeout':      15,
    }

    try:
        with yt_dlp.YoutubeDL(auto_opts) as ydl:
            ydl.download([video_url])
    except Exception:
        pass

    vtt_path = _find_vtt_file(output_dir, video_id)
    if vtt_path:
        return (vtt_path, "auto")

    # ---- Neither available --------------------------------------------------
    return (None, "none")


def _find_vtt_file(directory: str, video_id: str) -> str | None:
    """
    Locate the downloaded .vtt file for a given video ID.
    yt-dlp may name the file with language codes appended
    (e.g. video_id.en.vtt or video_id.en-GB.vtt).
    """
    pattern = os.path.join(directory, f"{video_id}*.vtt")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    return None


def cleanup_subtitle_files(output_dir: str, video_id: str) -> None:
    """Remove all downloaded subtitle files for a video ID."""
    pattern = os.path.join(output_dir, f"{video_id}*")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass
