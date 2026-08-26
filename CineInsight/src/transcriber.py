import os
import subprocess
import sys
from pathlib import Path
from faster_whisper import WhisperModel

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import _bootstrap_external_tools

def extract_audio(video_path, audio_path="data/processed/audio.wav"):
    os.makedirs(os.path.dirname(audio_path), exist_ok=True)
    if os.path.exists(audio_path):
        os.remove(audio_path)

    _bootstrap_external_tools()

    command = [
        "ffmpeg", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        audio_path, "-y"
    ]
    
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{result.stderr.decode()}")
    return audio_path

def generate_transcript(audio_path):
    print("Loading Whisper Model (CPU)... This might take a minute.")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    
    segments, info = model.transcribe(audio_path, beam_size=5, language="en", vad_filter=True)
    
    transcript_data = []
    for i, segment in enumerate(segments):
        transcript_data.append({
            "segment_id": f"seg_{i:04d}",
            "start": round(segment.start, 2),
            "end": round(segment.end, 2),
            "text": segment.text.strip()
        })
    return transcript_data
