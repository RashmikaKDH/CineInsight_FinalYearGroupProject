# Combined aspect and sentiment extraction

The local Gemini step now returns segment-level sentiment plus a sentiment for each detected aspect in the same request. Existing sarcasm models and Gemini SHAP explanations are unchanged. The default Gemini model remains gemini-3.5-flash (GEMINI_MODEL can override it).

CSV additions: sentiment_label, aspect_sentiments (JSON object), sentiment_status, sentiment_model. Existing columns retain their format. The inference notebook copies input columns through predictions and SHAP; the recovery notebook also preserves them. Old CSVs are not retroactively enriched. UI scoring/import is separate work and is not implemented here.

Labels: positive, neutral, negative, mixed, uncertain, not_applicable. Empty text is skipped. Never count failed, uncertain, or not_applicable rows as neutral. For a positive-share score use positive / (positive + neutral + negative + mixed), reporting mixed and excluded counts separately. This is a share of classified segments, not a calibrated probability or a movie quality rating. Aspect percentages use that aspect's labels, not the segment's overall sentiment.

Defaults (application safeguards, not verified account quotas):
- Up to 20 segments and approximately 7500 serialized text characters per request; full text retained, oversized segments rejected.
- 15 seconds minimum between attempts within one app process, sequential extraction runs.
- At most 3 attempts per batch and 20 attempts per run, including retries.
- Only 500/502/503/504 retry with 20/40 second backoff plus jitter. 429 stops immediately.
- SDK retries disabled. Output capped at 8192 tokens (including any thinking budget); malformed/truncated output is rejected, not silently accepted.
- Local per-text/model/prompt-version cache persists successful batches; rerunning can resume. No separate sentiment API requests, audio/video payloads, search tools or paid fallback.
- GEMINI_SEGMENTS_PER_REQUEST, GEMINI_REQUEST_GAP_SECONDS, GEMINI_MAX_REQUESTS_PER_RUN configure limits. Other app processes and the Colab explanation step share project quota but are not coordinated by this local lock.

Google pricing lists free-tier standard input/output for the default model, but the user's active account tier and RPM/TPM/RPD must be checked in AI Studio. Code does not change billing or prove that a supplied key belongs to a free-tier project.
https://ai.google.dev/gemini-api/docs/pricing
https://ai.google.dev/gemini-api/docs/rate-limits

Validation: 6 offline unittest cases cover 98 rows in five requests, cache reuse, mixed aspect labels, CSV serialization, bounded retries/429 stop, budget/resume, missing/duplicate IDs, and empty/oversized input. No live API was called. Review a manually labelled sample before presenting sentiment as validated research results.
