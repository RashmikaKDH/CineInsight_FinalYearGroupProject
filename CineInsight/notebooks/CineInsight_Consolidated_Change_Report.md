# CineInsight — Consolidated implementation report

Date: 2026-10-08

## Current end-to-end workflow

1. Signed-in user searches for a video and starts local preparation.
2. Local app downloads the video, extracts 16 kHz mono WAV, transcribes speech with Whisper, and uses Gemini for aspect and sentiment classification. It saves the initial CSV.
3. User uploads the matching CSV, MP4 and WAV to the combined Colab notebook. Colab computes text/audio/video features, trained sarcasm predictions, grouped SHAP and Gemini explanations.
4. User returns to Import Colab Report, selects the matching URL/date from their analysis history and uploads the final CSV. The post-preparation link preselects its Analysis_Id.
5. Backend validates the report, calculates real scores and saves a per-user report. Results and reasoning can be reopened without another Gemini request.

## Latest change: removed unnecessary local tensor work

Dependency search confirmed that get_text_tensor, get_audio_tensor and get_video_tensor were called only from main.py. Their results were used only for obsolete shape/snippet output, not for the Colab checkpoint or saved aspect/sentiment CSV.

Removed from main.py:
- Separate YouTube subtitle retrieval and BERT token generation call.
- MFCC audio feature call.
- Raw video-frame tensor call.
- Shape fields, obsolete subtitle snippet, tensor progress messages and CLI tensor display.

Removed from pipeline.py:
- Those three unused feature functions.
- Dummy token hashing and zero tensor fallback implementations.
- Unused URL parsing helper for the discarded subtitle call.
- Direct imports of NumPy, librosa, OpenCV, Torch, Transformers/BertTokenizer and youtube-transcript-api from this download module.

Retained:
- Video download and existing FFmpeg/Node discovery helpers (also used by the audio extractor).
- Audio extraction and Whisper transcription, needed for timestamps/text and Colab input.
- Gemini aspect/sentiment CSV creation and existing diagnostics.
- Completion event used to save database history and return db_analysis_id.

Completion now includes preparation_status=ready_for_colab and video_path/audio_path/csv_path. This indicates prepared files, not completed trained-model inference. No local BERT/MFCC/raw-frame feature functions remain. Existing installed packages and requirements.txt were not removed or uninstalled; other tools and Whisper may still use shared dependencies. No claim is made that all machine-learning computation has moved off the local machine: Whisper remains local.

## Earlier local Gemini changes

Aspect extraction was extended to return overall and per-aspect sentiment in the same request. CSV retains its original six columns and adds sentiment_label, aspect_sentiments, sentiment_status and sentiment_model. Batch limits, persistent response cache and request controls reduce repeated calls. The model identifier is saved locally, not generated with extra API tokens. Actual account quotas must still be checked in AI Studio. Current user reports show Flash-Lite model variants; the report records whichever configured model produced a result.

The user's extractor has also changed since the initial implementation: mixed general/specific aspects can produce completed_with_warnings. This cleanup did not rewrite that extractor or its model setting. Existing keyword/debug utilities remain in the repository; the configured production path is USE_LLM_EXTRACTOR=True and no keyword fallback was added by this cleanup.

## Colab notebook changes

CineInsight_Final_Combined.ipynb combines the user's Final_Inference2 feature/model/SHAP stages with the successful Recovery2 Gemini stage. It uses gemini-3.5-flash-lite for explanations, batches up to five rows, caches successful results and records sanitized failures. It preserves the trained feature/model/SHAP code from the supplied Inference2 notebook. It retains sentiment columns through the final report.

Step 12 was subsequently repaired to reject non-string/JSON API-key input, request a hidden plain-text key when needed and prevent error redaction from crashing on dictionary values. CineInsight_Step12_Replacement.py is available for replacing that cell without recomputing earlier runtime results. No live API call was made to validate the key fix; the user later provided a final CSV with all 21 eligible explanations completed.

## Results UI and history changes

- Dashboard link: Import Colab Report / Saved Reports.
- New report library and result pages, with responsive styling.
- Manual name field replaced by a URL/date selection from the signed-in user's database analysis history.
- Selected URL is read server-side; imports reject IDs absent from that user's history.
- Imported report JSON stores Analysis_Id, video_url and analysis_date. No database migration or new job_id.
- Storage: instance/imported_reports/<hashed-user-id>/, using original CSV plus derived JSON. Same analysis + identical bytes reuses the report; another analysis has a distinct report.
- Existing legacy imports remain readable, without retroactive automatic history matching.
- Real sentiment/aspect scores, sarcasm rate, local summary and saved reasoning replace dummy results.
- Reasoning expands on demand and supports browser Print / Save as PDF.
- Technical tensor panels, transcript/debug samples and raw errors are absent from the normal results flow. Simple preparation status remains.
- Imported text is escaped; login, per-user storage, upload size limits and form-token checks protect the import flow.

## Scoring and interpretation

Positive percentage = positive / (positive + neutral + negative + mixed) × 100. Uncertain, unrelated/not_applicable and unsuccessful rows are excluded and counted. Aspect scores use each aspect's own sentiment. Multiple aspects in one segment can contribute to multiple aspect counts. No-data categories show No data, not zero.

Sarcasm percentage = sarcastic segments / all valid predicted segments × 100. The user's latest sample has 21 / 191 = 11.0%. These are segment frequencies, not duration percentages, movie ratings, confidence scores or whole-audience sentiment.

Gemini summaries are explicitly automated interpretations. Measured signed SHAP evidence is displayed separately. The previously observed seg_0058 sentence contradicts its text SHAP sign; automatic semantic correction is not implemented. Do not present completed API status as proof of explanation accuracy.

## Verification

- Latest preparation tests: 3 passed. Checked CSV/media-path completion with no tensor APIs available, correct handling of Gemini failure without a false completion, and absence of discarded feature-library imports.
- Earlier report tests: 5 passed. Covered history URL selection/association, isolation, duplicate imports, unavailable history, invalid CSV/token handling, safe rendering and actual 191-row report aggregation.
- Notebook syntax and simulated batching/retry/cache tests were performed during notebook integration.
- Live video downloads, Whisper execution, paid/free Gemini calls, Colab GPU inference, live MySQL integration and browser visual testing were not run as part of this cleanup.

## Remaining limitations

- Video/WAV default paths are still shared (data/temp_video.mp4 and data/processed/audio.wav). Preserve matching files before preparing another video; concurrent preparations are not isolated.
- CSV does not contain an independently verifiable source-video identifier. Choose the correct analysis in history.
- Local database preparation records still use existing placeholder score/report defaults. Imported final scores are stored in the per-user file report, not written back into those database columns.
- Whisper still consumes local resources; this removal eliminates redundant BERT/MFCC/raw-frame work, not all local processing.

## Main files changed across this work

- main.py: combined output CSV and streamlined preparation orchestration.
- pipeline.py: retained media download/tools; removed obsolete local tensor code/imports.
- src/extractors/llm_aspect_extractor.py: combined aspect/sentiment implementation (earlier work).
- app.py: report blueprint registration.
- services/report_import.py: validation, aggregation, history selection and storage.
- templates/dashboard.html, analysis.html, report_base.html, reports.html, report_results.html; static/reports.css: UI flow.
- tests/test_aspect_sentiment.py, test_report_import.py, test_preparation.py: relevant offline coverage.
- notebooks/CineInsight_Final_Combined.ipynb and CineInsight_Step12_Replacement.py: combined Colab flow and key repair.
- .gitignore: classification cache exclusion (earlier work).

Restart the local Flask app to load the latest code. Search/process a video, upload its matching initial CSV/MP4/WAV to Colab, then import the final CSV against its saved URL/history entry.
