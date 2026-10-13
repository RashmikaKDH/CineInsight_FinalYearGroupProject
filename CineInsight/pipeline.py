import os
import shutil
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

try:
    import yt_dlp
except (ImportError, OSError):
    yt_dlp = None


class _SilentYtDlpLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def _resolve_node_runtime_path():
    node_executable = shutil.which("node")
    if node_executable:
        return node_executable

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    candidate = local_app_data / "Microsoft" / "WinGet" / "Packages"
    if candidate.exists():
        for package_dir in candidate.glob("OpenJS.NodeJS*"):
            for exe in package_dir.rglob("node.exe"):
                if exe.exists():
                    return str(exe)

    for fallback in (
        Path(r"C:\Program Files\nodejs\node.exe"),
        Path(r"C:\Program Files (x86)\nodejs\node.exe"),
    ):
        if fallback.exists():
            return str(fallback)

    return None


def _resolve_ffmpeg_bin_path():
    ffmpeg_executable = shutil.which("ffmpeg")
    if ffmpeg_executable:
        return str(Path(ffmpeg_executable).parent)

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    candidate_base = local_app_data / "Microsoft" / "WinGet" / "Packages"
    if candidate_base.exists():
        for package_dir in candidate_base.glob("Gyan.FFmpeg*"):
            for bin_dir in package_dir.rglob("bin"):
                if (bin_dir / "ffmpeg.exe").exists():
                    return str(bin_dir)

    for fallback in (
        Path(r"C:\Program Files\ffmpeg\bin"),
        Path(r"C:\Program Files (x86)\ffmpeg\bin"),
    ):
        if fallback.exists():
            return str(fallback)

    return None


def _prepend_to_path(directory_path):
    if not directory_path:
        return
    current_path = os.environ.get("PATH", "")
    parts = current_path.split(os.pathsep)
    if directory_path not in parts:
        os.environ["PATH"] = directory_path + os.pathsep + current_path


def _bootstrap_external_tools():
    node_runtime_path = _resolve_node_runtime_path()
    ffmpeg_bin_path = _resolve_ffmpeg_bin_path()

    if node_runtime_path:
        _prepend_to_path(str(Path(node_runtime_path).parent))
    if ffmpeg_bin_path:
        _prepend_to_path(ffmpeg_bin_path)

    return node_runtime_path, ffmpeg_bin_path


# 1. YouTube Video eka download karana function eka (CHUNKED & FRAGMENTED STREAM SAFE)
def download_video(url, output_path="data/temp_video.mp4"):
    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Parana kabi files thiyenawa nam auto delete karanawa
    for f in [output_path, output_path + ".part", output_path + ".ytdl"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
            
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed in the active Python environment")

    node_runtime_path, ffmpeg_bin_path = _bootstrap_external_tools()

    ydl_opts = {
        # Format 18 = YouTube native 360p progressive MP4 (no Range-header chunking needed)
        # This avoids HTTP Error 416 which occurs when forced byte-range chunking is used.
        'format': '18/best[height<=480]/bestvideo[height<=480]+bestaudio/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'logger': _SilentYtDlpLogger(),
        'nocheckcertificate': True,
        'retries': 10,
        'fragment_retries': 10,
        'file_access_retries': 5,
        'merge_output_format': 'mp4'
    }
    
    if node_runtime_path:
        ydl_opts['js_runtimes'] = {'node': {'path': node_runtime_path}}
    if ffmpeg_bin_path:
        ydl_opts['ffmpeg_location'] = ffmpeg_bin_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            sink = StringIO()
            with redirect_stdout(sink), redirect_stderr(sink):
                result = ydl.download([url])
        if result != 0 or not os.path.exists(output_path):
            raise RuntimeError("Video download failed; yt-dlp did not produce a valid file")
    except Exception as e:
        raise RuntimeError(f"Video download failed: {e}") from e
    return output_path

