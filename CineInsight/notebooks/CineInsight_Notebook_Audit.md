# CineInsight notebook audit

The existing `CineInsight_Final_Inference.ipynb` was updated in place. The supplied original notebook and local app were not edited.

## Preserved technologies

- `distilroberta-base`: CLS, 768 dimensions.
- `facebook/wav2vec2-base-960h`: 16 kHz mono, hidden-state mean, 768 dimensions.
- `google/vit-base-patch16-224-in21k`: frame CLS mean, 768 dimensions.
- Identical `CineInsightCrossModalAttention` class, 8 heads, original checkpoint/labels.
- SHAP KernelExplainer and Gemini API explanations.

## Findings and changes

| Finding in original process | Correction / limitation |
|---|---|
| Training text uses context + text / max 128; inference used text / max 512 | Use max 128 and genuine optional context. Flag missing context and truncation. Do not fabricate context. |
| Training samples every `int(fps)` frames; review inference samples up to 16 evenly spaced frames | Match the training stride relative to the segment start. Read original video without another compression pass. |
| Full vectors were explained as 2304 independent dimensions, then absolute values were summed | Keep Kernel SHAP but explain three whole modalities, enumerate all coalitions, disable sparse feature selection and check additivity. This is a changed explanation definition. |
| Zero baseline may be far from real embeddings | Prefer available original training-split vectors. Explicitly mark zero fallback when unavailable; save background provenance. |
| Absolute SHAP values hide whether a modality supports or opposes sarcasm | Save signed effects, relative magnitudes, dominant direction and explicit tie/zero cases. |
| Normal-row zero SHAP values looked like measured zero influence | Use blank values plus `skipped_normal`. |
| Gemini was instructed to infer facial-expression/tone contradictions it had never observed | Summarize signed evidence only; prohibit invented sensory observations and word-level attribution claims. |
| SHAP/API errors could leave misleading output | Save predictions first, separate statuses, partial results and completed Gemini-response cache. |
| Checkpoint peak accuracy confused with best-loss selection | Document epoch 9 checkpoint selection (79.61% validation), epoch 11 peak accuracy (80.58%), historical test 69.23% / 104 samples. |

Outputs preserve the original prediction/confidence/impact names and add class probabilities, signed effects, direction and statuses. The same three local input files are uploaded. No database changes or local model execution were added.

## Architectural limitation confirmed

The trained attention calls use sequence length 1. In evaluation, attention weight over the single key is 1, so the attention sublayer cannot select among temporal tokens using its query. Residual connections still depend on text/audio. This is not a claim that modalities are ignored. The model is still usable for inference, but true sequence alignment requires retraining with sequence features. The existing checkpoint architecture was not changed.

Missing real conversational context and MUStARD-to-review domain shift remain. Truncation parity and cleaner explanations do not establish improved accuracy. Original training encoder revisions were not recorded; new runs record library versions, resolved encoder revision IDs, file hashes and checkpoint hash. Changes in library/model revision may still prevent bit-for-bit parity with old runs.

## Validation performed

- All Python cells parsed; output/execution history cleared.
- Exact AST equality of the learned model class against original cell 74.
- Actual CPU Torch forward test with random weights: batch and one-at-a-time outputs agree.
- Actual Torch singleton-attention test: weights equal 1; attention output unchanged when only the query changes.
- Input checks for missing context, NaN/out-of-range/short timestamps, duplicate IDs and fractional FPS sampling.
- Whole-modality masks and signed effects checked against an independent exact three-player Shapley implementation; additivity, ties and zero effects checked.
- Controlled pipeline tests confirm prediction saving, normal SHAP skipping, and preserved predictions when SHAP fails.
- Mock Gemini tests confirm skipped rows, evidence restrictions and cache reuse without repeated requests.

The actual SHAP package solver was not installed in the local test environment; the grouped wrapper was tested using the independent exact reference. No pretrained weights were downloaded, no real Drive checkpoint inference was run, and no Gemini API calls were made. Run the notebook on a small known review in Colab before relying on results. Higher accuracy is not claimed.

## Documentation checked

- [Hugging Face truncation](https://huggingface.co/docs/transformers/main/pad_truncation)
- [SHAP KernelExplainer: background, sampling and feature selection](https://shap.readthedocs.io/en/stable/generated/shap.KernelExplainer.html)
- [PyTorch attention definition](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention)

## Gemini free-tier request optimization (2026-10-06)
This supersedes earlier per-row / 2-second / first-transient-error behavior. Both notebooks now group up to five eligible missing explanations into one serial request, send compact text/probability/signed modality SHAP evidence, and validate returned segment IDs. No model architecture, checkpoint, predictions, SHAP computation, or Gemini model was changed. Completed CSV results and compatible legacy/local caches are reused.
Requests are spaced at least 15 seconds apart, with at most three attempts per batch (20/40-second transient server-error backoff) and six attempts per cell run. SDK retry attempts are explicitly one. Quota errors stop immediately. Payloads exceeding the character bound are not silently truncated. Partial reports can be downloaded and re-uploaded to resume. These are request controls, not a guarantee of free quota or relief from 503 server demand.
Validation: all notebook code cells parsed; mocked tests on the user's 98-row recovered CSV confirmed four explanations in one successful call, zero calls for completed/cached results, bounded 503 retries, immediate 429 stop, rejection of mismatched IDs, and unchanged prediction/SHAP columns. No live API call was made; model structured-output compatibility still needs a Colab run.
