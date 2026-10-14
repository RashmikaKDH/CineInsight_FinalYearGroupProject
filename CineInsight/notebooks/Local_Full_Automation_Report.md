# Local full-flow automation implementation

Updated 2026-10-14. Analyze now chains local preparation, trained inference, SHAP and Gemini explanations without manual CLI execution or final-CSV import.

## Behavior

- Signed-in user selects a YouTube video and opens /analysis.
- The UI POSTs /api/analyze/start with a form/session token and persistent per-tab request identifier. Start is idempotent for the same user/request/URL.
- A pending database Analysis_Id is created once, with NULL sentiment/sarcasm fields rather than fake zero results.
- Single background worker processes one video at a time in this Flask process. Each owned analysis gets instance/analysis_runs/<hashed-user>/<Analysis_Id>/ with prepared media/CSV and its own inference folder.
- Polling /api/analyze/status/<id> displays current preparation/inference stages and selected segment/batch counters. Closing/reconnecting the browser does not restart or cancel work.
- Final CSV is validated using the existing report parser and automatically placed in the user-owned report library. A successful run redirects to results; partial output exposes View available results.
- Reports include an authenticated Download Final CSV link. Existing manual imports remain available for older Colab outputs.
- Reusing a running/completed per-tab request opens that same analysis. Explicit Start a new analysis is available on terminal states. No automatic resubmission follows a connection failure.

## Database

Uses the existing schema from cineinsight_db.sql. No migration or destructive operation was executed.
- youtube_video is selected/created by URL.
- analysis gets one record at queue time; Aspect_Vise_Report initially stores queued/running/failed JSON.
- save_final_analysis locks the owner-matching analysis record and atomically updates Overall_Sentiment_Score, Sarcasm_Flag and Aspect_Vise_Report.
- Final aspect JSON includes actual overall/aspect breakdown, sarcasm rate, report ID and completed/partial status.
- reasoning_report is inserted/upserted using its unique Analysis_Id, avoiding repeated reasoning rows.
- Transactions roll back on failure; score and reasoning writes are committed together.
- If final DB save fails, valid CSV/local report remains available as partial, with a separate database warning. Existing analysis can remain running until repaired; there is no DB retry endpoint yet.

A live read-only MySQL check failed with connection refused at localhost:3306. Actual running-schema compatibility and final writes remain unverified until MySQL is started. The implementation matches the supplied SQL schema and mocked transaction tests.

## Models and reasoning

Uses the working local-inference models/checkpoint/background and separate SHAP_GEMINI_API_KEY. Inference progress callback does not expose raw API errors or credentials to the browser. Gemini prompt now requests plain English, avoids numeric probabilities/jargon in explanations and retains evidence/sign/no-invented-tone constraints. Cache version changed so old wording is not reused. Prompt quality has not yet been evaluated in a live API run.

## Limitations

This is a local single-Flask-process queue, not a production distributed job service. Run one app process. Flask auto-reload/server shutdown interrupts active work; old task states are identified as interrupted on reconnect instead of secretly resuming. Prepared outputs remain saved. A new explicit analysis can be started, but feature/reasoning-only resume/retry is not yet automated.

Preparation now receives per-analysis paths; its debug traces remain shared diagnostics. Status manifests and input snapshots are local filesystem data. A separate production deployment would need persistent/shared storage and worker coordination. Request identifiers link repeated starts; they do not prove a manually supplied CSV matches a video.

Gemini/SHAP failures that return partial CSV are displayed. A hard feature/model failure without final CSV is marked failed and retains earlier files. Missing reasoning configuration is checked before downloading media. Pretrained weights may download on first use.

## Verification

53 tests passed in the full offline pytest suite before the final warning-text adjustment. Added five automated-flow tests cover idempotent start, ownership/auth/token checks, fake preparation-to-inference-to-final-report flow, authenticated CSV download, partial/DB-failure preservation, process-restart detection and transactional owner-checked DB upsert. Existing tests still pass. The pipeline/full-flow tests mock external processing and DB; no API quota was consumed.

Actual Flask import smoke check passed: anonymous analysis redirects to login; signed-in processing page returns 200 and contains the automatic start endpoint; legacy GET /api/analyze returns 405 and cannot create work. After the final adjustment the focused automated-flow/report tests were run again.

## Files

services/analysis_worker.py; services/db_service.py; app.py; main.py; src/local_inference.py; services/report_import.py; templates/analysis.html; templates/report_results.html; tests/test_automated_flow.py.

## Try it

1. Start XAMPP/MySQL and confirm cineinsight_db exists with the supplied schema.
2. Keep the configured aspect Gemini key(s), SHAP_GEMINI_API_KEY and SHAP_GEMINI_MODEL in .env; keep the three model/background assets in models/cineinsight.
3. Restart Flask; avoid editing/reloading server code while processing.
4. Sign in, search/select a short review and click Analyze.
5. Observe preparation, features, SHAP and reasoning progress, then the automatic Results page. Use Download Final CSV.
6. If partial/failed, read the local server log and preserved analysis folder. A second browser connection checks the same job rather than starting a duplicate.

No claim is made that the new full UI/database flow has passed a real end-to-end video run while the database is unavailable.

