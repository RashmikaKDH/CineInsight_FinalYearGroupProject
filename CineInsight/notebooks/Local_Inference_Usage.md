# Local inference pipeline

Run from the CineInsight project folder after local preparation:

```powershell
.\venv\Scripts\python.exe src/local_inference.py --csv "data\YOUR_LLM_OUTPUT.csv" --video "data\temp_video.mp4" --audio "data\processed\audio.wav"
```

Use the matching three files from one preparation, not an older CSV. The default assets were copied from Downloads into models/cineinsight. Set GEMINI_API_KEY in .env for reasoning. Default explanation model: gemini-3.5-flash-lite. Model APIs/configuration for local aspect extraction remain separate. --skip-gemini allows feature/model/SHAP processing without a live Gemini request. --device cpu, cuda or auto selects computation.

Install on a fresh environment using requirements-inference.txt. pandas, shap and pillow were installed in the current project venv; initial Hugging Face weight downloads still require internet and disk space. No encoder weights are included in this repository.

Output: data/local_inference/inference_<timestamp>/, with copied inputs, feature vectors, predictions.csv, SHAP report, final explainability CSV, provenance manifest and status.json. Completed Gemini responses are cached in this run folder. Each CLI invocation creates a new run; interrupted-run resume and retry-only CLI commands are not yet implemented. Partial reasoning returns exit code 2; stage failure retains earlier output files. --skip-gemini marks reasoning disabled, not completed.

The implementation embeds reviewed notebook stage source; does not import or require Colab. Existing feature models, classifier and grouped SHAP were preserved. Status is written per stage. This is the standalone inference step, not yet connected to the Flask Analyze button or its history/results UI. No retraining is performed.

Verification: all stage code compiles, no Colab import remains, actual checkpoint strictly loads, finite classifier probabilities and background dimensions/hash pass. Mocked integration exercises local input copying/final CSV/status creation without model downloads/API calls. Real end-to-end pretrained feature extraction, model inference and Gemini on a video have not yet been run. CPU time and RAM usage are not measured.

## Dedicated reasoning configuration update

SHAP numeric computation requires no API key. Gemini explanation requests now require SHAP_GEMINI_API_KEY. They never fall back to GEMINI_API_KEY/GEMINI_API_KEYS used by aspect extraction. An empty SHAP_GEMINI_API_KEY placeholder was appended to .env without changing existing keys. Fill it privately before running.

SHAP_GEMINI_MODEL configures the explanation model (default gemini-3.5-flash-lite). Model selection follows a strict precedence hierarchy:
1. CLI flag: `--gemini-model <model>` (highest precedence)
2. Process Environment: `SHAP_GEMINI_MODEL` exported in terminal or OS session (takes precedence over .env because `load_dotenv(..., override=False)`)
3. Project `.env` file: `SHAP_GEMINI_MODEL` (loaded if not already set in process environment)
4. Built-in hardcoded fallback: `'gemini-3.5-flash-lite'` (lowest precedence)

Note: Existing terminal environment values may override `.env` because `override=False` in `load_dotenv()`. If you change `.env`, ensure the variable is not already defined in your current terminal session. Relative media/assets/output paths resolve against the project root.

Terminal shows device, output folder, START stage, existing per-segment output, DONE stage and elapsed seconds; messages flush immediately. Model loading/download messages are retained. Failure identifies the stage/folder and reports predictions_preserved only if predictions.csv exists. SHAP failures now count as partial output rather than completed. Analyze-button integration remains unchanged.

No live inference/API request was made for this configuration update. Offline tests cover dedicated key isolation, model precedence, missing-key behavior, path resolution and CSV output flow. --skip-gemini remains available.
