from pipeline import download_video, get_text_tensor, get_audio_tensor, get_video_tensor

def process_youtube_review(url):
    print("⏳ 1. Video eka download wenawa...")
    video_path = download_video(url)
    
    print("⏳ 2. Text (Subtitles) AI Tensor ekata harawanawa...")
    text_tensor, raw_text = get_text_tensor(url)
    
    print("⏳ 3. Audio voice features AI Tensor ekata harawanawa...")
    audio_tensor = get_audio_tensor(video_path)
    
    print("⏳ 4. Video frames expressions AI Tensor ekata harawanawa...")
    video_tensor = get_video_tensor(video_path)
    
    print("\n✅ OKKOMA TENSORS READY! MEWA THAMAI AI MODEL EKATA WANNE:")
    print("==================================================")
    print(f"📝 Text Tensor Shape  : {text_tensor.shape} (Words count/IDs)")
    print(f"🔊 Audio Tensor Shape : {audio_tensor.shape} (Voice MFCC features)")
    print(f"🎬 Video Tensor Shape : {video_tensor.shape} (Visual Frames)")
    print("==================================================")
    print(f"🗣️ Extract una Subtitle Text eka: \"{raw_text[:100]}...\"\n")
    
    return text_tensor, audio_tensor, video_tensor

# === TEST KARALA BALANNA YT LINK EKAK DANNA ===
if __name__ == "__main__":
    test_url = "https:winget uninstall aria2.aria2//youtu.be/ZS8EC2LQlng?si=Ov0qngs1i7zvfxcH" # Meka wenuwata kemathi review link ekak danna
    t_tensor, a_tensor, v_tensor = process_youtube_review(test_url)