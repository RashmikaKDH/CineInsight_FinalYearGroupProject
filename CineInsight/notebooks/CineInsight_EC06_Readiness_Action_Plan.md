# CineInsight EC06 readiness and action plan

Reviewed 2026-10-13 against the team's EC04/EC05 documents and current local source. This is an audit, not a declaration that all requirements have passed acceptance testing. No application behavior was changed during this review.

## Verified current implementation

- main.py prepares downloaded video, 16 kHz mono WAV, Whisper transcript, combined Gemini aspect/sentiment CSV. Old local BERT/MFCC/frame feature calls are absent.
- Colab remains a manual handoff; the combined notebook handles trained sarcasm inference, grouped SHAP and Gemini explanations. Local completion means ready_for_colab, not completed inference.
- services/report_import.py validates the final CSV, computes segment-based sentiment/aspect/sarcasm percentages, reads signed-in-user history and associates file reports with the selected Analysis_Id and URL.
- Results are stored in instance/imported_reports per user as CSV/JSON, not written back as final values into the existing database score/report columns.
- cineinsight_db.sql defines primary keys, unique user Email and reasoning_report.Analysis_Id, foreign keys and deletion behavior. These are SQL-export evidence, not confirmation of the running database schema.
- Admin UI has search and deletion confirmation; normal signup/login uses password hashing and session/role checks. Authentication acceptance tests remain necessary.

## Fresh automated evidence

Command: venv/Scripts/python.exe -X utf8 -m unittest discover -s tests
Result: 14 tests, 0 failures, 0 errors, 0 skipped, reported test runtime 0.747 seconds.

Coverage: 6 aspect/sentiment tests; 3 preparation tests; 5 report/import tests. Tests mock media processing/Gemini and database history. The actual final CSV fixture is checked for 191 segments, 21 sarcastic predictions and 11.0% segment sarcasm rate. These are integration/unit checks, not measured model accuracy or a live end-to-end acceptance run. The intentionally simulated database-unavailable test emits an error log but passes.

## Priority issues before acceptance

1. Password recovery (FR24–26): app.py reset_password changes credentials using the supplied email and new password without a verified reset token or authenticated owner. forgot() checks email existence but sends no email. Do not claim secure recovery; implement verified expiring one-time tokens or explicitly record this requirement as incomplete. Retest authentication after fixing.
2. FR59 cancel analysis: search AbortController exists but is not evidence of cancelling the backend download/Whisper/Gemini work. Record analysis cancellation as pending unless implemented and verified.
3. Shared paths: data/temp_video.mp4 and data/processed/audio.wav can be overwritten by later/concurrent preparations. Preserve matching files for the demo; do not claim concurrent-user processing.
4. FR58 conflict detection: prediction architecture alone is not proof of detected facial/tone contradictions. Do not describe pooled singleton attention as verified changing attention across temporal cues. Explain its actual limits.
5. Google login page is a localStorage simulation, not verified OAuth. Do not list it as real Google authentication.
6. Gemini model/retry behavior has changed since earlier notes: current extractor includes multiple-key handling and malformed-JSON retries. Document actual configured version and usage; key changes within a project do not prove extra quota. Existing tests do not cover multi-key branches.
7. FR38 mandatory filter selection / FR39 clear filters: current search UI has defaults and a duration selector. Match exact EC04 semantics before marking accepted.

## EC06 application assembly

Section 01: use CodePulse, confirmed full title, supervisor and four member details from prior applications. Confirm spelling, current details and exact individual ownership before signing.
Section 02: create all 67 EC04 FR acceptance rows. Columns: FR number, name, responsible member, scenario, expected result, actual result, evidence ID, team acceptance, external-user acceptance. Use Pending or Partial until actually tested. FR50–54 describe local preparation plus Colab feature extraction; FR55–57 distinguish Gemini sentiment and trained sarcasm. New CSV/history/report-import features should be labelled enhancements, not silently renumbered requirements.
Section 03: report verified final-checkpoint held-out sarcasm metrics, confusion matrix and split; separately validate Gemini overall/aspect sentiment and explanation fidelity. Include processing latency and request/token counts. Compare baselines on the same evaluation data and cite sources; no unsupported universal industry ranges.
Section 04: interfaces: browser-to-search, download-to-WAV/Whisper, transcript-to-Gemini/CSV, manual local-to-Colab media/CSV, feature-to-classifier, classifier-to-SHAP, SHAP-to-Gemini, final CSV-to-import/aggregation, history DB-to-import, stored report-to-results. Give realistic positive and failure test inputs and record actual outcomes.
Section 05: use SQL schema, representative queries, CSV schema, file-storage design and access-control tests; explain final values remain file-backed. Verify constraints in live MySQL.
Section 06: screenshots of real output, navigation/loading/invalid-file/no-data feedback, Chrome and Edge testing, mobile widths, keyboard focus and contrast. CSS alone is not responsiveness evidence.
Section 07: achievements, benefits as intended uses, assumptions, manual-Colab/Gemini/Whisper/data limits and realistic automation future work.
Sections 08–09: student declaration and supervisor declaration. Humans supply acceptance and signatures; do not prefill unverified Yes values or signatures.

## Minimal new evidence to collect

A. Full run: sign in, select one English video, preserve matching initial CSV/MP4/WAV, run Colab, import against correct history entry, verify counts/percentages/reasons. Capture steps and errors with dated screenshots. Never capture credentials.
B. FR testing: positive and invalid-input cases for registration/login/admin/search/import/reasoning. Test live MySQL with disposable test users and owner isolation, without deleting real users.
C. Sentiment: manually label a sample such as 50–100 segments from multiple videos, including mixed, neutral, unrelated, sarcastic and multi-aspect cases. Report sampling, label instructions, evaluators, disagreements, metrics and limitations. This is a practical pilot, not proof of population-wide quality.
D. Explanation fidelity: inspect all 21 sarcastic explanations in the known 191-row sample. Check modality/sign consistency and unsupported facial/voice claims. The previously identified seg_0058 sentence is a known mismatch. Report counts and failure examples.
E. Interpretability target: EC04/EC05 specifies at least 80% of nontechnical users rate reports completely understandable. Record recruited users, exact question, response scale, numerator/denominator and outcome; a suggested pilot is 10 users, where 8/10 satisfies the sample target but generalization remains limited. Do not invent acceptance responses.
F. NFRs: test Chrome/Edge and mobile screen sizes; run the declared linter and report its actual result rather than claiming 10/10; record environment and measured times separately for download, Whisper, Gemini, features, SHAP and import.

## What can be drafted now versus pending

Draft now: identity/details, implemented functionality descriptions, architecture, CSV/database/file design, current automated evidence, UI design, limitations/future work and blank acceptance/declaration tables.
Pending measurements: live functional/external acceptance, end-to-end screenshots, model-checkpoint metrics verification, sentiment/explanation validation, user study, performance/API measurements, browser/accessibility and live DB checks.
Not completed: production deployment, fully automatic Colab execution, proven concurrency, genuine email-token recovery, proven analysis cancellation, independently verified modality conflict detection or proven explanation correctness.
