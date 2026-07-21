# CineInsight 🎬🔍

CineInsight is a **Multimodal Sarcasm-Aware Sentiment Analysis** system tailored for YouTube movie reviews. Traditional sentiment analysis tools often fail because they rely solely on text. CineInsight solves this by processing **Text (subtitles)**, **Audio (vocal tone)**, and **Video (facial expressions)** simultaneously to detect hidden sarcasm and calculate highly accurate sentiment scores.

## 🚀 Key Features

*   **Targeted Search Engine:** Integrated with YouTube Data API v3 to search and filter specific movie reviews.
*   **Multimodal Data Extraction:** Extracts and synchronizes audio, visual, and textual data from YouTube videos.
*   **Sarcasm Detection:** Identifies discrepancies between spoken words and physical/audio cues.
*   **Aspect-Based Sentiment Analysis (Upcoming):** Calculates individual scores for specific movie aspects like Acting, Plot, and CGI.
*   **Explainable AI (Upcoming):** Generates simple English reasoning reports to explain why the AI flagged a review as sarcastic.

## 🛠️ Technology Stack

*   **Frontend:** Streamlit / HTML & CSS
*   **Backend:** Python (Flask/Streamlit)
*   **Database:** MySQL
*   **APIs:** YouTube Data API v3
*   **Machine Learning / AI:** RoBERTa (Text), Wav2Vec 2.0 (Audio), OpenCV & Mediapipe (Visual)

## 💻 Setup Instructions (Local Development)

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/YourUsername/CineInsight.git](https://github.com/YourUsername/CineInsight.git)
   cd CineInsight
