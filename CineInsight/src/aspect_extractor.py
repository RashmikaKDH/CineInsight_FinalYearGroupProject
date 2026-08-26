ASPECTS_DICT = {
    "acting": ["acting", "actor", "actress", "performance", "cast", "played"],
    "plot": ["plot", "story", "script", "writing", "narrative", "storyline"],
    "cgi": ["cgi", "visual effects", "vfx", "effects", "animation", "graphics", "visuals"],
    "direction": ["director", "direction", "directed", "filmmaking", "cinematography"],
    "music": ["music", "soundtrack", "score", "songs", "background music", "bgm"],
    "dialogue": ["dialogue", "dialog", "lines", "conversation"]
}

def extract_aspects_from_segments(transcript_segments):
    analyzed_segments = []
    for seg in transcript_segments:
        text_lower = seg["text"].lower()
        detected_aspects = []
        
        for aspect, keywords in ASPECTS_DICT.items():
            if any(kw in text_lower for kw in keywords):
                detected_aspects.append(aspect)
                
        if not detected_aspects:
            detected_aspects = ["general"]
            
        seg["aspects"] = detected_aspects
        analyzed_segments.append(seg)
        
    return analyzed_segments
