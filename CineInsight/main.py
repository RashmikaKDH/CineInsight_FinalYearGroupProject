import csv
import json
import os
from datetime import datetime
from pipeline import download_video, get_text_tensor, get_audio_tensor, get_video_tensor
from src.transcriber import extract_audio, generate_transcript
from src.extractors.keyword_extractor import extract_aspects_from_segments, ASPECTS_DICT
from src.extractors.llm_aspect_extractor import extract_aspects_from_segments_llm

# ============================================================
# ⭐ ASPECT EXTRACTOR MODE — meka line eka change karannama method switch karanna
# True  = LLM  (Gemini API haraha — context-aware, accurate)
# False = Keyword Dictionary (fast, offline, no API cost)
# ============================================================
USE_LLM_EXTRACTOR = True

DEBUG_ASPECT_TRACE_FILE = "data/debug/debug_aspect_trace.json"
LLM_CSV_OUTPUT_DIR = "data"

def _save_llm_output_csv(url, aspect_segments):
    """Save LLM-classified segments to a timestamped CSV in the data/ folder."""
    os.makedirs(LLM_CSV_OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(LLM_CSV_OUTPUT_DIR, f"llm_output_{timestamp}.csv")

    fieldnames = ["segment_id", "start", "end", "text", "aspects", "primary_aspect"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for seg in aspect_segments:
            aspects = seg.get("aspects", ["general"])
            writer.writerow({
                "segment_id": seg.get("segment_id", ""),
                "start": seg.get("start", ""),
                "end": seg.get("end", ""),
                "text": seg.get("text", ""),
                "aspects": "|".join(aspects),
                "primary_aspect": aspects[0] if aspects else "general",
            })

    print(f"💾 LLM output saved to: {csv_path}  ({len(aspect_segments)} segments)")
    return csv_path


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
    os.makedirs(os.path.dirname(DEBUG_ASPECT_TRACE_FILE), exist_ok=True)
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
    if USE_LLM_EXTRACTOR:
        try:
            aspect_segments = extract_aspects_from_segments_llm(transcript_segments)
        except RuntimeError as e:
            # Surface the exact error reason to the UI — no silent fallback
            error_reason = str(e)
            yield json.dumps({
                "status": "aspect_error",
                "message": f"⚠️ Gemini LLM aspect extraction failed: {error_reason}"
            })
            yield json.dumps({
                "status": "error",
                "message": (
                    "Aspect extraction failed. Pipeline stopped.\n"
                    f"Reason: {error_reason}\n\n"
                    "To switch to offline mode: open main.py and set USE_LLM_EXTRACTOR = False"
                )
            })
            return  # Stop pipeline — do not continue to tensor steps
    else:
        aspect_segments = extract_aspects_from_segments(transcript_segments)
    if USE_LLM_EXTRACTOR:
        _save_llm_output_csv(url, aspect_segments)
    _save_aspect_debug_trace(url, aspect_segments)


    yield json.dumps({"status": "progress", "message": "⏳ 6. Analyzing audio features to generate audio tensors..."})
    audio_tensor = get_audio_tensor(video_path)
    
    yield json.dumps({"status": "progress", "message": "⏳ 7. Processing video frames to generate visual tensors..."})
    video_tensor = get_video_tensor(video_path)
    
    final_data = {
        "status": "completed",
        "url": url,
        "title": f"YouTube Review ({url})",  # TODO: replace with real title from pipeline
        "text_shape": str(list(text_tensor.shape)),
        "audio_shape": str(list(audio_tensor.shape)),
        "video_shape": str(list(video_tensor.shape)),
        "raw_text_snippet": raw_text[:200] + "..." if raw_text else "No text found",
        "total_segments_found": len(aspect_segments),
        "sample_segment": aspect_segments[0] if aspect_segments else None,
        # --- Mock values (to be replaced when scoring pipeline is ready) ---
        "overall_sentiment_score": 0.0,
        "sarcasm_flag": False,
        "aspect_wise_report": None,   # will be a JSON string once aspect scoring is done
        "reasoning_report_text": "Reasoning report under development.",
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