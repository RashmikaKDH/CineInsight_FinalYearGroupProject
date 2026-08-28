import json
from pipeline import download_video, get_text_tensor, get_audio_tensor, get_video_tensor
from src.transcriber import extract_audio, generate_transcript
from src.extractors.keyword_extractor import extract_aspects_from_segments, ASPECTS_DICT

DEBUG_ASPECT_TRACE_FILE = "debug_aspect_trace.json"

def _save_aspect_debug_trace(url, aspect_segments):
    """Save a full keyword-hit debug trace so debug_aspect.py can load it directly."""
    debug_segments = []
    for seg in aspect_segments:
        text_lower = seg["text"].lower()
        keyword_hits = {}
        for aspect, keywords in ASPECTS_DICT.items():
            keyword_hits[aspect] = {kw: kw in text_lower for kw in keywords}
        debug_segments.append({
            "segment_id": seg["segment_id"],
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "text_lower": text_lower,
            "keyword_hits": keyword_hits,
            "aspects": seg["aspects"],
            "is_general": seg["aspects"] == ["general"],
        })

    total = len(debug_segments)
    general_count = sum(1 for s in debug_segments if s["is_general"])
    aspect_counts = {a: 0 for a in ASPECTS_DICT}
    for s in debug_segments:
        for a in s["aspects"]:
            if a in aspect_counts:
                aspect_counts[a] += 1

    trace = {
        "url": url,
        "total_segments": total,
        "detected_count": total - general_count,
        "general_count": general_count,
        "aspect_counts": aspect_counts,
        "aspects_dict": ASPECTS_DICT,
        "segments": debug_segments,
    }
    with open(DEBUG_ASPECT_TRACE_FILE, "w", encoding="utf-8") as f:
        json.dump(trace, f, ensure_ascii=False, indent=2)
    return trace

def process_youtube_review_generator(url):
    yield json.dumps({"status": "progress", "message": "⏳ 1. Downloading video and extracting metadata..."})
    video_path = download_video(url)
    
    yield json.dumps({"status": "progress", "message": "⏳ 2. Processing subtitles to generate text tensors..."})
    text_tensor, raw_text = get_text_tensor(url)
    
    yield json.dumps({"status": "progress", "message": "⏳ 3. Extracting clean audio for AI..."})
    audio_path = extract_audio(video_path)
    
    yield json.dumps({"status": "progress", "message": "⏳ 4. Transcribing speech to text (Whisper)..."})
    transcript_segments = generate_transcript(audio_path)
    
    yield json.dumps({"status": "progress", "message": "⏳ 5. Detecting movie aspects..."})
    aspect_segments = extract_aspects_from_segments(transcript_segments)
    _save_aspect_debug_trace(url, aspect_segments)

    yield json.dumps({"status": "progress", "message": "⏳ 6. Analyzing audio features to generate audio tensors..."})
    audio_tensor = get_audio_tensor(video_path)
    
    yield json.dumps({"status": "progress", "message": "⏳ 7. Processing video frames to generate visual tensors..."})
    video_tensor = get_video_tensor(video_path)
    
    final_data = {
        "status": "completed",
        "text_shape": str(list(text_tensor.shape)),
        "audio_shape": str(list(audio_tensor.shape)),
        "video_shape": str(list(video_tensor.shape)),
        "raw_text_snippet": raw_text[:200] + "..." if raw_text else "No text found",
        "total_segments_found": len(aspect_segments),
        "sample_segment": aspect_segments[0] if aspect_segments else None
    }
    yield json.dumps(final_data)

def process_youtube_review(url):
    for data_str in process_youtube_review_generator(url):
        data = json.loads(data_str)
        if data["status"] == "progress":
            print(data["message"])
        elif data["status"] == "completed":
            print("\n✅ OKKOMA TENSORS READY! MEWA THAMAI AI MODEL EKATA WANNE:")
            print("==================================================")
            print(f"📝 Text Tensor Shape  : {data['text_shape']}")
            print(f"🔊 Audio Tensor Shape : {data['audio_shape']}")
            print(f"🎬 Video Tensor Shape : {data['video_shape']}")
            print("==================================================")
            print(f"🗣️ Extract una Subtitle Text eka: \"{data['raw_text_snippet']}\"\n")

if __name__ == "__main__":
    test_url = "https://youtu.be/ZS8EC2LQlng?si=Ov0qngs1i7zvfxcH"
    process_youtube_review(test_url)