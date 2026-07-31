import os
import re
import shutil
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import numpy as np
from urllib.parse import urlparse, parse_qs

try:
    import librosa
except (ImportError, OSError):
    librosa = None

try:
    import yt_dlp
except (ImportError, OSError):
    yt_dlp = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except (ImportError, OSError):
    YouTubeTranscriptApi = None

try:
    import cv2
except (ImportError, OSError):
    cv2 = None

try:
    import torch
except (ImportError, OSError):
    torch = None

try:
    from transformers import BertTokenizer
except (ImportError, OSError):
    BertTokenizer = None


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


def _extract_video_id(url):
    parsed_url = urlparse(url)

    if parsed_url.hostname in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        query = parse_qs(parsed_url.query)
        if "v" in query and query["v"]:
            return query["v"][0]

    if parsed_url.hostname in {"youtu.be", "www.youtu.be"}:
        video_id = parsed_url.path.lstrip("/")
        if video_id:
            return video_id

    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)

    raise ValueError(f"Could not extract YouTube video ID from URL: {url}")


def _fallback_tokenize(text, max_length=512):
    tokens = text.lower().split()
    token_ids = [min(abs(hash(token)) % 30000 + 1, 30000) for token in tokens[:max_length]]
    token_ids.extend([0] * (max_length - len(token_ids)))
    return np.array([token_ids], dtype=np.int64)




# 1. YouTube Video eka download karana function eka (CHUNKED & FRAGMENTED STREAM SAFE)
def download_video(url, output_path="temp_video.mp4"):
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
        # Format 18 wenuwata DASH/HLS fragmented streams use karamu. 
        # Mewa podi kabi walata kadala enna nisa connection drop wenne naha!
        'format': 'bestvideo[height<=360]+bestaudio/best[height<=360]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'logger': _SilentYtDlpLogger(),
        'nocheckcertificate': True,
        'external_downloader': None,
        'no_continue': True,
        
        # --- CONNECTION DROP PREVENT KARANA ALUTH OPTS ---
        'http_chunk_size': 10485760,         # 10MB chunks walata kadala gannawa
        'retries': 15,                       # Drop unoth 15 parak try karanawa
        'fragment_retries': 15,              # Fragment ekak drop unoth ekama try karanawa
        'file_access_retries': 5,
        'concurrent_fragment_downloads': 3,  # Safely kabi 3k ekawara gannawa (aria2c one na)
        'merge_output_format': 'mp4'         # Anthimata FFmpeg walin MP4 karala denawa
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

# 2. Subtitles (Text) extract karala AI Tensor ekak karana function eka
def get_text_tensor(url):
    try:
        video_id = _extract_video_id(url)
        
        transcript = None
        if YouTubeTranscriptApi is None:
            raise ImportError("youtube_transcript_api is not installed")

        transcript_api = YouTubeTranscriptApi()

        if hasattr(transcript_api, "fetch"):
            transcript = transcript_api.fetch(video_id)
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript = YouTubeTranscriptApi.get_transcript(video_id)

        if transcript is None:
            raise AttributeError("No supported transcript retrieval method was found")

        full_text = " ".join(
            item["text"] if isinstance(item, dict) else getattr(item, "text", str(item))
            for item in transcript
        )
    except Exception as e:
        print(f"⚠️ Subtitles natha. Default text gani: {e}")
        full_text = "No transcript available for this video."

    if BertTokenizer is not None:
        tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
        tensor_format = "pt" if torch is not None else "np"
        inputs = tokenizer(full_text, return_tensors=tensor_format, max_length=512, truncation=True, padding="max_length")
        return inputs['input_ids'], full_text

    return _fallback_tokenize(full_text), full_text


# 3. Audio eka extract karala AI Tensor ekak karana function eka
def get_audio_tensor(video_path):
    _bootstrap_external_tools()

    if not video_path or not os.path.exists(video_path):
        print("⚠️ Valid video file nathi nisa audio tensor fallback ekak dunnawa.")
        fallback = np.zeros((1, 40, 100), dtype=np.float32)
        if torch is not None:
            return torch.tensor(fallback, dtype=torch.float32)
        return fallback

    if librosa is None:
        print("⚠️ librosa natha. Audio tensor fallback ekak dunnawa.")
        fallback = np.zeros((1, 40, 100), dtype=np.float32)
        if torch is not None:
            return torch.tensor(fallback, dtype=torch.float32)
        return fallback

    try:
        y, sr = librosa.load(video_path, sr=16000, duration=30.0)
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        if torch is not None:
            return torch.tensor(mfccs, dtype=torch.float32).unsqueeze(0)
        return np.expand_dims(mfccs.astype(np.float32), axis=0)
    except Exception as e:
        print(f"⚠️ Audio extract karanna beri una: {e}")
        fallback = np.zeros((1, 40, 100), dtype=np.float32)
        if torch is not None:
            return torch.tensor(fallback, dtype=torch.float32)
        return fallback


# 4. Video frames extract karala AI Tensor ekak karana function eka
def get_video_tensor(video_path, num_frames=10):
    _bootstrap_external_tools()

    if not video_path or not os.path.exists(video_path):
        print("⚠️ Valid video file nathi nisa video tensor fallback ekak dunnawa.")
        fallback = np.zeros((1, num_frames, 3, 224, 224), dtype=np.float32)
        if torch is not None:
            return torch.tensor(fallback, dtype=torch.float32)
        return fallback

    if cv2 is None:
        print("⚠️ OpenCV natha. Video tensor fallback ekak dunnawa.")
        fallback = np.zeros((1, num_frames, 3, 224, 224), dtype=np.float32)
        if torch is not None:
            return torch.tensor(fallback, dtype=torch.float32)
        return fallback

    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total_frames // num_frames) if total_frames > 0 else 1
    
    frames = []
    for i in range(0, max(1, total_frames), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if ret and len(frames) < num_frames:
            frame = cv2.resize(frame, (224, 224))
            frame = frame / 255.0
            frames.append(frame)
    cap.release()

    if not frames:
        print(f"⚠️ Video frames extract karanna beri una: {video_path}")
        fallback = np.zeros((1, num_frames, 3, 224, 224), dtype=np.float32)
        if torch is not None:
            return torch.tensor(fallback, dtype=torch.float32)
        return fallback
    
    while len(frames) < num_frames:
        frames.append(np.zeros((224, 224, 3), dtype=np.float32))

    frames_array = np.array(frames[:num_frames]).transpose(0, 3, 1, 2)
    if torch is not None:
        return torch.tensor(frames_array, dtype=torch.float32).unsqueeze(0)
    return np.expand_dims(frames_array.astype(np.float32), axis=0)