"""CineInsight - Gemini Models Diagnostic & Security Verification Tool.

Tests Gemini API keys against Google Generative Language API,
verifies which models are active (200 OK), and measures latency.

Security Best Practices:
- No hardcoded API keys.
- Keys are masked in console output (e.g. AQ.Ab8...LZQ).
- Keys are transmitted via secure HTTP headers (x-goog-api-key).
- Never writes keys to log files or temp files.
"""

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("[ERROR] 'requests' package is required. Run: pip install requests", flush=True)
    sys.exit(1)


API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Priority models for LLM classification & sentiment analysis
PRIORITY_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
]


def mask_key(key: str) -> str:
    """Mask an API key for safe console display."""
    if not key:
        return "<empty>"
    clean_key = key.strip()
    if len(clean_key) <= 10:
        return "*" * len(clean_key)
    return f"{clean_key[:6]}...{clean_key[-4:]}"


def load_env_keys(project_dir: Path) -> tuple[list[str], str]:
    """Safely load GEMINI_API_KEYS / GEMINI_API_KEY and GEMINI_MODEL from .env."""
    keys: list[str] = []
    configured_model: str = ""

    # Check process environment
    env_keys_raw = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
    configured_model = os.getenv("GEMINI_MODEL", "")

    # Also parse .env file directly
    env_file = project_dir / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in ("GEMINI_API_KEYS", "GEMINI_API_KEY") and not env_keys_raw:
                            env_keys_raw = v
                        elif k == "GEMINI_MODEL" and not configured_model:
                            configured_model = v
        except Exception as e:
            print(f"[!] Warning reading .env file: {e}", flush=True)

    if env_keys_raw:
        for k in env_keys_raw.split(","):
            cleaned = k.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)

    return keys, configured_model


def fetch_models(api_key: str) -> tuple[list[dict], int, str]:
    """Fetch the list of models available for this API key."""
    url = f"{API_BASE}/models"
    headers = {
        "x-goog-api-key": api_key,
        "User-Agent": "CineInsight-Diagnostic/1.0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=25)
        status = response.status_code
        if status == 200:
            data = response.json()
            return data.get("models", []), 200, "OK"
        return [], status, response.text[:200]
    except requests.exceptions.RequestException as e:
        return [], 0, str(e)


def test_model_generate(api_key: str, model_name: str) -> tuple[int, int, str]:
    """Test text generation on a specific model using a minimal prompt.
    
    Returns:
        (status_code, latency_ms, detail_message)
    """
    clean_name = model_name
    if clean_name.startswith("models/"):
        clean_name = clean_name[len("models/"):]

    url = f"{API_BASE}/models/{clean_name}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
        "User-Agent": "CineInsight-Diagnostic/1.0"
    }
    payload = {
        "contents": [{"parts": [{"text": "Hello"}]}],
        "generationConfig": {
            "maxOutputTokens": 3
        }
    }

    start = time.perf_counter()
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        latency = int((time.perf_counter() - start) * 1000)
        status = response.status_code

        if status == 200:
            return 200, latency, "Working (200 OK)"
        elif status == 429:
            return 429, latency, "Rate limit / Quota exceeded"
        elif status == 503:
            return 503, latency, "Service overloaded (503)"
        elif status == 504:
            return 504, latency, "Gateway timeout (504)"
        elif status == 404:
            return 404, latency, "Model not supported / 404"
        elif status == 400:
            return 400, latency, "Bad request (400)"
        elif status == 403:
            return 403, latency, "Permission denied (403)"
        else:
            return status, latency, f"HTTP Error {status}"
    except requests.exceptions.Timeout:
        latency = int((time.perf_counter() - start) * 1000)
        return 408, latency, "Request timed out (>20s)"
    except requests.exceptions.RequestException as e:
        latency = int((time.perf_counter() - start) * 1000)
        return 0, latency, f"Network error: {str(e)[:40]}"


def run_diagnostics(api_key: str, key_label: str, filter_keyword: str = "", configured_model: str = "", test_all: bool = False):
    """Run diagnostics on a single API key."""
    masked = mask_key(api_key)
    print("\n" + "=" * 76, flush=True)
    print(f"  DIAGNOSTIC FOR API KEY: {masked} ({key_label})", flush=True)
    print("=" * 76, flush=True)

    # 1. Fetch available models
    print("[*] Contacting Google Generative Language API...", flush=True)
    models, status, error_detail = fetch_models(api_key)

    if status != 200:
        print(f"\n[FAIL] Authentication failed or API unreachable! (HTTP Status: {status})", flush=True)
        print(f"       Details: {error_detail}", flush=True)
        if status in (400, 401, 403):
            print("\n[!] Possible causes:", flush=True)
            print("    1. Invalid or expired API Key.", flush=True)
            print("    2. Generative Language API is disabled in Google AI Studio / GCP.", flush=True)
        return

    print(f"[OK] Authentication verified! Total available models: {len(models)}", flush=True)

    # 2. Filter models that support generateContent
    gen_models = [
        m for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    model_name_set = {m.get("name", "").replace("models/", ""): m for m in gen_models}

    # Decide which models to test:
    candidates = []
    if filter_keyword:
        # User specified custom filter
        for m in gen_models:
            name = m.get("name", "")
            if filter_keyword.lower() in name.lower():
                candidates.append(m)
    elif test_all:
        # User requested testing all models
        candidates = gen_models
    else:
        # Default smart mode: test priority CineInsight models + configured model
        added = set()
        # Always test configured model first if present
        if configured_model and configured_model in model_name_set:
            candidates.append(model_name_set[configured_model])
            added.add(configured_model)

        for pm in PRIORITY_MODELS:
            if pm in model_name_set and pm not in added:
                candidates.append(model_name_set[pm])
                added.add(pm)

        # If none matched priority, fall back to any flash/pro models
        if not candidates:
            for m in gen_models:
                name = m.get("name", "").replace("models/", "")
                if any(x in name for x in ["flash", "pro"]) and not any(x in name for x in ["-tts", "-image"]):
                    candidates.append(m)
                    if len(candidates) >= 6:
                        break

    if not candidates:
        print(f"[!] No models matched criteria.", flush=True)
        return

    mode_info = f"Filter '{filter_keyword}'" if filter_keyword else ("All Models" if test_all else "Recommended / Core Models")
    print(f"[*] Testing {len(candidates)} models ({mode_info})...\n", flush=True)
    print(f"{'MODEL NAME':<32} | {'STATUS':<24} | {'LATENCY':<12}", flush=True)
    print("-" * 76, flush=True)

    working_models: list[tuple[str, int]] = []
    rate_limited_models: list[str] = []
    failed_models: list[tuple[str, int, str]] = []

    for m in candidates:
        full_name = m.get("name", "")
        short_name = full_name.replace("models/", "")

        status_code, latency, msg = test_model_generate(api_key, full_name)

        if status_code == 200:
            status_str = "PASS (200 OK)"
            working_models.append((short_name, latency))
        elif status_code == 429:
            status_str = "RATE LIMITED (429)"
            rate_limited_models.append(short_name)
        elif status_code == 404:
            status_str = "UNAVAILABLE (404)"
            failed_models.append((short_name, status_code, msg))
        elif status_code == 503:
            status_str = "OVERLOADED (503)"
            failed_models.append((short_name, status_code, msg))
        elif status_code == 408:
            status_str = "TIMEOUT (>15s)"
            failed_models.append((short_name, status_code, msg))
        else:
            status_str = f"ERR {status_code}"
            failed_models.append((short_name, status_code, msg))

        print(f"{short_name:<32} | {status_str:<24} | {f'{latency} ms':<12}", flush=True)
        time.sleep(0.15)

    # 3. Summary & Recommendations
    print("-" * 76, flush=True)
    print("\n[SUMMARY & RECOMMENDATIONS]", flush=True)
    print(f"Total Tested: {len(candidates)} | Active (200 OK): {len(working_models)} | Rate-Limited: {len(rate_limited_models)} | Failed: {len(failed_models)}", flush=True)

    if working_models:
        working_models.sort(key=lambda x: x[1])
        print("\nFastest & Active Models:", flush=True)
        for m_name, lat in working_models[:5]:
            mark = "  <-- CURRENT IN .env" if configured_model and configured_model == m_name else ""
            print(f"   * {m_name:<28} [Latency: {lat} ms]{mark}", flush=True)

        # Determine best pick for CineInsight
        best_pick = working_models[0][0]
        flash_picks = [m for m, _ in working_models if "flash" in m and "lite" not in m]
        if flash_picks:
            best_pick = flash_picks[0]

        print(f"\nRecommended setting for your .env file:", flush=True)
        print(f"   GEMINI_MODEL={best_pick}\n", flush=True)
    else:
        print("\n[!] None of the tested models returned HTTP 200 OK.", flush=True)
        if rate_limited_models:
            print("    Some models are rate-limited (HTTP 429). Wait a few minutes and re-test.", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="CineInsight - Gemini API Key & Active Models Diagnostic Tool"
    )
    parser.add_argument(
        "--key", "-k",
        type=str,
        default="",
        help="Specific Gemini API Key to test (if omitted, reads from .env or prompts)"
    )
    parser.add_argument(
        "--env", "-e",
        action="store_true",
        help="Directly test first API key found in .env without interactive prompts"
    )
    parser.add_argument(
        "--all-keys",
        action="store_true",
        help="Test all API keys found in .env"
    )
    parser.add_argument(
        "--filter", "-f",
        type=str,
        default="",
        help="Filter models by keyword (e.g. 'flash', 'pro', '2.5')"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Test all available models (including experimental/TTS/image models)"
    )

    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parent
    env_keys, configured_model = load_env_keys(project_dir)

    print("=" * 76, flush=True)
    print("       CineInsight - Gemini Models Diagnostic & Security Checker       ", flush=True)
    print("=" * 76, flush=True)

    keys_to_test: list[tuple[str, str]] = []

    if args.key:
        keys_to_test.append((args.key.strip(), "CLI Argument"))
    elif args.all_keys:
        if not env_keys:
            print("[ERROR] No GEMINI_API_KEYS found in .env!", flush=True)
            sys.exit(1)
        for i, k in enumerate(env_keys, 1):
            keys_to_test.append((k, f".env Key {i}/{len(env_keys)}"))
    elif args.env:
        if not env_keys:
            print("[ERROR] No GEMINI_API_KEYS found in .env!", flush=True)
            sys.exit(1)
        keys_to_test.append((env_keys[0], ".env Key 1"))
    else:
        # Interactive selection
        if env_keys:
            print(f"Found {len(env_keys)} Gemini API key(s) in .env:", flush=True)
            for i, k in enumerate(env_keys, 1):
                print(f"  [{i}] {mask_key(k)}", flush=True)
            print(f"  [C] Custom key (enter a new key manually)", flush=True)
            print(f"  [A] Test ALL {len(env_keys)} keys in .env", flush=True)

            try:
                choice = input("\nSelect an option [1/C/A] (Default: 1): ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                choice = "1"

            if choice == "A":
                for i, k in enumerate(env_keys, 1):
                    keys_to_test.append((k, f".env Key {i}/{len(env_keys)}"))
            elif choice == "C":
                try:
                    custom = input("Enter Gemini API Key to test: ").strip()
                except (EOFError, KeyboardInterrupt):
                    custom = ""
                if not custom:
                    print("[ERROR] Key cannot be empty.", flush=True)
                    sys.exit(1)
                keys_to_test.append((custom, "Custom Key"))
            elif choice.isdigit() and 1 <= int(choice) <= len(env_keys):
                idx = int(choice) - 1
                keys_to_test.append((env_keys[idx], f".env Key {idx+1}"))
            else:
                keys_to_test.append((env_keys[0], ".env Key 1"))
        else:
            print("[!] No keys found in .env.", flush=True)
            try:
                custom = input("Enter Gemini API Key to test: ").strip()
            except (EOFError, KeyboardInterrupt):
                custom = ""
            if not custom:
                print("[ERROR] Key cannot be empty.", flush=True)
                sys.exit(1)
            keys_to_test.append((custom, "Manual Input"))

    for api_key, label in keys_to_test:
        run_diagnostics(
            api_key=api_key,
            key_label=label,
            filter_keyword=args.filter,
            configured_model=configured_model,
            test_all=args.all
        )

    print("\n" + "=" * 76, flush=True)
    print("Diagnostic complete.", flush=True)
    print("=" * 76 + "\n", flush=True)


if __name__ == "__main__":
    main()
