import json
from pipeline import download_video, get_text_tensor, get_audio_tensor, get_video_tensor

def process_youtube_review_generator(url):
    yield json.dumps({"status": "progress", "message": "⏳ 1. Video eka download wenawa (Downloading video)..."})
    video_path = download_video(url)
    
    yield json.dumps({"status": "progress", "message": "⏳ 2. Text (Subtitles) AI Tensor ekata harawanawa (Extracting Text)..."})
    text_tensor, raw_text = get_text_tensor(url)
    
    yield json.dumps({"status": "progress", "message": "⏳ 3. Audio voice features AI Tensor ekata harawanawa (Extracting Audio)..."})
    audio_tensor = get_audio_tensor(video_path)
    
    yield json.dumps({"status": "progress", "message": "⏳ 4. Video frames expressions AI Tensor ekata harawanawa (Extracting Video)..."})
    video_tensor = get_video_tensor(video_path)
    
    final_data = {
        "status": "completed",
        "text_shape": str(list(text_tensor.shape)),
        "audio_shape": str(list(audio_tensor.shape)),
        "video_shape": str(list(video_tensor.shape)),
        "raw_text_snippet": raw_text[:200] + "..." if raw_text else "No text found"
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