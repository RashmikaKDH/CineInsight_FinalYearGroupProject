import json
import sys
from pathlib import Path
from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import download_video
from src.transcriber import extract_audio, generate_transcript
from src.aspect_extractor import ASPECTS_DICT

DEBUG_ASPECT_TRACE_FILE = "debug_aspect_trace.json"

app = Flask(__name__)


def extract_aspects_debug(transcript_segments):
    """
    Extended version of extract_aspects_from_segments that also returns
    a full keyword-hit breakdown per segment for debugging purposes.
    """
    analyzed = []
    for seg in transcript_segments:
        text_lower = seg["text"].lower()
        detected_aspects = []
        keyword_hits = {}

        for aspect, keywords in ASPECTS_DICT.items():
            hits = {}
            for kw in keywords:
                hits[kw] = kw in text_lower
            keyword_hits[aspect] = hits
            if any(hits.values()):
                detected_aspects.append(aspect)

        if not detected_aspects:
            detected_aspects = ["general"]

        analyzed.append({
            "segment_id": seg["segment_id"],
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "text_lower": text_lower,
            "keyword_hits": keyword_hits,
            "aspects": detected_aspects,
            "is_general": detected_aspects == ["general"],
        })

    return analyzed


@app.route("/")
def index():
    return render_template("debug_aspect.html")


@app.route("/api/run-aspect-debug")
def api_run_aspect_debug():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided. Add ?url=<youtube_url>"}), 400

    try:
        # Step 1: Download video
        video_path = download_video(url)

        # Step 2: Extract audio
        audio_path = extract_audio(video_path)

        # Step 3: Transcribe
        transcript_segments = generate_transcript(audio_path)

        # Step 4: Aspect detection with full debug trace
        debug_segments = extract_aspects_debug(transcript_segments)

        # Build summary statistics
        total = len(debug_segments)
        general_count = sum(1 for s in debug_segments if s["is_general"])
        detected_count = total - general_count

        aspect_counts = {aspect: 0 for aspect in ASPECTS_DICT}
        for seg in debug_segments:
            for asp in seg["aspects"]:
                if asp in aspect_counts:
                    aspect_counts[asp] += 1

        return jsonify({
            "url": url,
            "total_segments": total,
            "detected_count": detected_count,
            "general_count": general_count,
            "aspect_counts": aspect_counts,
            "aspects_dict": ASPECTS_DICT,
            "segments": debug_segments,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/load-last-trace")
def api_load_last_trace():
    """Load the trace saved by the main app's last analysis run."""
    import os
    if not os.path.exists(DEBUG_ASPECT_TRACE_FILE):
        return jsonify({"error": "No trace file found. Please analyze a video in the main app first (http://localhost:5000)."}), 404
    try:
        with open(DEBUG_ASPECT_TRACE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("  CineInsight — Aspect Detection Debugger")
    print("  Running on http://localhost:5002")
    print("=" * 55)
    app.run(port=5002, debug=True)
