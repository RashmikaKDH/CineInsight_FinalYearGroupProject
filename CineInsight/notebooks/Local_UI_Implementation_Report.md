# Local CSV results UI — implementation report

## What changed

- Dashboard now links to Import Colab Report / Saved Reports.
- /reports accepts the final Colab CSV and a selected analysis from the signed-in user's database history. Initial aspect-only CSVs are rejected with a clear message.
- The backend validates required columns, unique IDs, timestamps, finite probabilities and SHAP values, sentiment labels and aspect mappings. Uploads are limited to 5 MB and 20,000 rows.
- Results show the video title, overall positive segment share, sarcasm segment percentage, sentiment counts, per-aspect scores with Why details, and a counts-based conclusion.
- View Reasoning Report opens the saved Gemini explanations alongside the signed SHAP evidence and timestamps. Print / Save as PDF uses the browser print dialog. No new Gemini requests are made.
- Replaced the old analysis page's hardcoded scores and technical tensor/debug panels with simple preparation progress and a link to import the completed report. The existing video processing backend is retained.
- Empty report history and unavailable scores have explicit empty states; an aspect with no eligible sentiment data shows No data, never 0%.

## Storage and account access

Reports are stored under instance/imported_reports/<hashed-user-id>/ as original CSV and prepared JSON. Existing instance/ ignore rules exclude these files from Git. Login is required; another user's report ID cannot access the report. A token protects the import form. SHA-256 of the analysis ID plus file contents avoids exact duplicate uploads for the same user and analysis. User content uses template escaping rather than HTML injection.

No database schema or trained-model changes. Imported JSON now stores the selected existing Analysis_Id, video URL and analysis date. The URL is read server-side from the signed-in user's analysis history; there is no manual name field. The results heading uses this URL. After local processing, the import link preselects the returned database analysis ID. Reports remain local files; existing database score/report columns are not updated. Older manually named imports remain readable and are not automatically associated with history. Identical files imported into different analyses are stored separately. The CSV still cannot prove it belongs to the selected video. A deployment using multiple machines would need shared storage.

If the history database is unavailable, importing is blocked with a user-friendly message; saved local reports remain accessible. With no history, process a video while signed in before importing.

## Scoring rules

Positive share = positive / (positive + neutral + negative + mixed) × 100. Uncertain, not_applicable and unsuccessful sentiment rows are excluded and counted. completed_with_warnings rows are included. Aspect scores use aspect-specific labels; a multi-aspect segment can count once in each relevant aspect. Sarcasm rate = Sarcastic / all valid predicted segments × 100. These are segment-based percentages, not duration-weighted scores, calibrated confidence, audience ratings or movie quality.

The conclusion is generated locally from counts, not an additional LLM call. All available aspect categories are shown, including general, so reviews with no acting/CGI data are represented honestly.

## Explanation limits

The source CSV includes at least one Gemini sentence (seg_0058) that conflicts with the signed text SHAP value. The UI labels Gemini output as an automated interpretation, warns it may be inaccurate, and separately displays computed sign directions. It does not silently rewrite original explanations or claim automatic semantic verification. Review/correction of such text remains necessary before a final research demonstration.

## Validation

Flask test-client tests passed for import/redirect/render, escaped transcript content, duplicate import handling, cross-user isolation, login requirement, form-token rejection and invalid CSV rejection. The user's 191-row CSV parses to 21 sarcastic rows (11.0%) and 21 reasoning entries. Python syntax checks passed. No paid API calls, live model inference or database migrations were performed. Full browser visual/mobile testing and full app startup with MySQL/external services were not performed; responsive CSS and server-rendered templates are implemented.

## How to use

1. Restart the local Flask app and sign in.
2. On Dashboard, select Import Colab Report / Saved Reports.
3. Select the matching video URL and date from analysis history, then select the final explainability CSV and Import and view results. No name needs to be typed.
4. Open View Reasoning Report to see saved explanations; use Print / Save as PDF to export.
5. Use Reports to reopen saved results. No Colab rerun is needed for an already completed CSV.

## Files

app.py (blueprint registration); services/report_import.py (validation, aggregation, storage, routes); templates/dashboard.html (entry link); templates/analysis.html (simple preparation view); templates/report_base.html, reports.html, report_results.html (report UI); static/reports.css (responsive styling); tests/test_report_import.py (functional tests).


## History integration validation (2026-10-08)
Five Flask test cases pass, covering URL preselection/rendering, stored analysis association, rejection of selections absent from the current user history, database-unavailable handling, and the earlier import/security/actual-CSV checks. Database responses were mocked; no live MySQL or browser visual test was performed.

## Local preparation cleanup (2026-10-08)
The previous note that local tensor calls remain is superseded. BERT token, MFCC and raw-frame extraction calls/functions and their obsolete imports/output fields have now been removed. Video download, WAV extraction, Whisper and Gemini CSV remain. See CineInsight_Consolidated_Change_Report.md for the complete current workflow, tests and limitations.
