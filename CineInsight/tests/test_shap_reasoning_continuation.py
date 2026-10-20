"""Isolated regression tests for SHAP-to-Gemini explanation continuation.

Verifies:
1. 57 eligible rows complete in 12 successful requests when payload sizes permit.
2. Processing continues beyond request 6.
3. 30 cached explanations plus 27 pending rows request only the remaining 27.
4. Temporary 429/server retry delay is honored and paced.
5. Daily quota exhaustion pauses without an infinite retry loop.
6. Zero quota pauses without an infinite retry loop.
7. Network and 5xx retries are bounded (max 3 attempts) and paced.
8. Invalid credentials (401/403) do not repeatedly retry.
9. Invalid response IDs do not produce false completion.
10. A failed batch preserves earlier successful explanations in report and cache.
11. Automatic and recovery paths use the same unified implementation.
12. Recovery returns nonzero (2) exit code on partial / incomplete runs.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from src import local_inference as li
import manage_analysis


def make_mock_shap_df(count=57, sarcastic=True):
    """Generate synthetic DataFrame matching the validated SHAP schema."""
    rows = []
    for i in range(count):
        is_sarc = sarcastic if isinstance(sarcastic, bool) else (i < sarcastic)
        rows.append({
            'segment_id': f'seg_{i:04d}_plot',
            'start': float(i * 2),
            'end': float(i * 2 + 2),
            'text': f'Sample segment text line {i}',
            'aspects': 'plot',
            'primary_aspect': 'plot',
            'sentiment_label': 'positive',
            'aspect_sentiments': '{"plot":"positive"}',
            'sentiment_status': 'completed',
            'sarcasm_prediction': 'Sarcastic' if is_sarc else 'Normal',
            'shap_status': 'completed' if is_sarc else 'skipped_normal',
            'sarcastic_probability': 0.85 if is_sarc else 0.12,
            'text_shap_value': 0.15 if is_sarc else 0.0,
            'audio_shap_value': -0.05 if is_sarc else 0.0,
            'video_shap_value': 0.02 if is_sarc else 0.0,
            'dominant_modality': 'Text' if is_sarc else 'None',
            'dominant_direction': 'supports_sarcasm' if is_sarc else 'none',
            'shap_background': 'dataset'
        })
    return pd.DataFrame(rows)


class MockGeminiResponse:
    def __init__(self, payload_dict):
        self.text = json.dumps(payload_dict)


class MockGenaiClient:
    def __init__(self, handler_fn=None):
        self.handler_fn = handler_fn or self._default_handler
        self.calls = []
        self.closed = False

    def _default_handler(self, calls, contents):
        items = json.loads(contents)
        explanations = [
            {'segment_id': item['id'], 'explanation': f'Model flagged possible sarcasm because of text for {item["id"]}.'}
            for item in items
        ]
        return MockGeminiResponse({'explanations': explanations})

    @property
    def models(self):
        return self

    def generate_content(self, model, contents, config=None):
        self.calls.append({'model': model, 'contents': contents, 'config': config})
        return self.handler_fn(self.calls, contents)

    def close(self):
        self.closed = True


class ShapReasoningContinuationTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.cache_path = self.dir_path / 'gemini_explanations.json'
        self.output_csv = self.dir_path / 'cineinsight_final_explainability_report.csv'

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1 & 2: 57 eligible rows complete in 12 requests, continuing beyond 6
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(200)])
    def test_57_eligible_rows_complete_in_12_requests_and_continues_beyond_6(self, mock_time, mock_sleep):
        df = make_mock_shap_df(57, sarcastic=True)
        mock_client = MockGenaiClient()

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5,
            max_requests=None  # Default: continues until all complete
        )

        # 57 rows at 5 per batch = 11 batches of 5 + 1 batch of 2 = 12 requests
        self.assertEqual(len(mock_client.calls), 12)
        self.assertGreater(len(mock_client.calls), 6, "Must continue beyond the legacy 6-request limit")
        self.assertEqual((report['reasoning_status'] == 'completed').sum(), 57)
        self.assertTrue((report['ai_reasoning'].str.strip() != '').all())
        self.assertTrue(self.output_csv.is_file())
        self.assertTrue(self.cache_path.is_file())
        cache = json.loads(self.cache_path.read_text(encoding='utf-8'))
        self.assertEqual(len(cache), 57)
        self.assertTrue(mock_client.closed)

    # -------------------------------------------------------------------------
    # 3: 30 cached explanations + 27 pending rows requests only remaining 27
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(200)])
    def test_cached_30_and_pending_27_only_requests_remaining_27(self, mock_time, mock_sleep):
        df = make_mock_shap_df(57, sarcastic=True)

        # Pre-seed cache with explanations for the first 30 segments
        cache_data = {}
        for i in range(30):
            row = df.iloc[i]
            evidence = {
                'id': str(row.segment_id),
                'text': str(row.text),
                'p': round(float(row.sarcastic_probability), 6),
                'shap': [round(float(row[k]), 6) for k in ('text_shap_value', 'audio_shap_value', 'video_shap_value')],
                'reference': str(row.shap_background)
            }
            msg = json.dumps(evidence, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            key = hashlib.sha256(('gemini-3.5-flash-lite' + 'plain-v2' + msg).encode()).hexdigest()
            cache_data[key] = f"Cached explanation for segment {i}."

        self.cache_path.write_text(json.dumps(cache_data), encoding='utf-8')

        requested_ids = []
        def handler(calls, contents):
            items = json.loads(contents)
            for item in items:
                requested_ids.append(item['id'])
            explanations = [
                {'segment_id': item['id'], 'explanation': f'Newly generated for {item["id"]}.'}
                for item in items
            ]
            return MockGeminiResponse({'explanations': explanations})

        mock_client = MockGenaiClient(handler_fn=handler)

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5,
            max_requests=None
        )

        # Exactly 27 pending segments should be requested (5 batches of 5 + 1 batch of 2 = 6 requests)
        self.assertEqual(len(requested_ids), 27)
        self.assertEqual(len(mock_client.calls), 6)
        expected_ids = [f'seg_{i:04d}_plot' for i in range(30, 57)]
        self.assertEqual(requested_ids, expected_ids)
        # All 57 rows should be completed (30 from cache + 27 new)
        self.assertEqual((report['reasoning_status'] == 'completed').sum(), 57)

    # -------------------------------------------------------------------------
    # 4: Temporary 429 server retry delay is honored and retried
    # -------------------------------------------------------------------------
    def test_temporary_429_honors_server_retry_delay_and_succeeds(self):
        df = make_mock_shap_df(5, sarcastic=True)
        sleep_durations = []

        def mock_sleep_recorder(duration):
            sleep_durations.append(duration)

        attempt_counter = [0]
        def handler(calls, contents):
            attempt_counter[0] += 1
            if attempt_counter[0] == 1:
                # First attempt raises temporary 429 with retry delay
                err = Exception("RESOURCE_EXHAUSTED: 429 Resource has been exhausted. Please retry after 18.5s.")
                setattr(err, 'code', '429')
                raise err
            # Second attempt succeeds
            items = json.loads(contents)
            return MockGeminiResponse({
                'explanations': [{'segment_id': item['id'], 'explanation': 'Explanation.'} for item in items]
            })

        mock_client = MockGenaiClient(handler_fn=handler)

        fake_clock = [0.0]
        def fake_monotonic():
            fake_clock[0] += 0.1
            return fake_clock[0]

        with patch('time.sleep', side_effect=mock_sleep_recorder), \
             patch('time.monotonic', side_effect=fake_monotonic):
            report = li.repair_reasoning(
                frame=df,
                model_name='gemini-3.5-flash-lite',
                cache_path=self.cache_path,
                output_path=self.output_csv,
                make_client=lambda: mock_client,
                delay=15.0,
                batch_size=5
            )

        self.assertEqual(len(mock_client.calls), 2)
        # Verify a retry sleep was called with >= 18.5s
        has_server_delay_sleep = any(s >= 18.5 for s in sleep_durations)
        self.assertTrue(has_server_delay_sleep, f"Must sleep for at least server retry delay 18.5s; slept: {sleep_durations}")
        self.assertEqual((report['reasoning_status'] == 'completed').sum(), 5)

    # -------------------------------------------------------------------------
    # 5: Daily quota exhaustion pauses without infinite retry loop
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(50)])
    def test_daily_quota_pauses_without_infinite_retry_loop(self, mock_time, mock_sleep):
        df = make_mock_shap_df(10, sarcastic=True)

        def handler(calls, contents):
            err = Exception("Quota exceeded for quota metric 'Requests per day' and limit 'RequestsPerDayPerProject'")
            setattr(err, 'code', '429')
            raise err

        mock_client = MockGenaiClient(handler_fn=handler)

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5
        )

        # Must not retry: exactly 1 call made
        self.assertEqual(len(mock_client.calls), 1)
        # All rows should be marked waiting_budget, not left in pending
        self.assertTrue((report['reasoning_status'] == 'waiting_budget').all())
        self.assertEqual(report.iloc[0]['reasoning_error_code'], '429')
        self.assertIn("Requests per day", report.iloc[0]['reasoning_error'])

    # -------------------------------------------------------------------------
    # 6: Zero quota pauses without retry
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(50)])
    def test_zero_quota_pauses_without_retry(self, mock_time, mock_sleep):
        df = make_mock_shap_df(5, sarcastic=True)

        def handler(calls, contents):
            err = Exception("Resource has been exhausted. Quota limit: 0.")
            setattr(err, 'code', '429')
            raise err

        mock_client = MockGenaiClient(handler_fn=handler)

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5
        )

        self.assertEqual(len(mock_client.calls), 1)
        self.assertTrue((report['reasoning_status'] == 'waiting_budget').all())
        self.assertEqual(report.iloc[0]['reasoning_error_code'], '429')

    # -------------------------------------------------------------------------
    # 7: Network and 5xx retries are bounded and paced
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(50)])
    def test_network_and_5xx_retries_are_bounded_and_paced(self, mock_time, mock_sleep):
        df = make_mock_shap_df(10, sarcastic=True)

        def handler(calls, contents):
            err = Exception("503 Service Unavailable: backend server temporarily overloaded")
            setattr(err, 'code', '503')
            raise err

        mock_client = MockGenaiClient(handler_fn=handler)

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5
        )

        # Max 3 attempts total (initial + 2 retries)
        self.assertEqual(len(mock_client.calls), 3)
        # First batch marked error, second batch marked waiting_after_error
        self.assertEqual((report.iloc[:5]['reasoning_status'] == 'error').sum(), 5)
        self.assertEqual((report.iloc[5:]['reasoning_status'] == 'waiting_after_error').sum(), 5)
        self.assertEqual(report.iloc[0]['reasoning_error_code'], '503')

    # -------------------------------------------------------------------------
    # 8: Invalid credentials do not repeatedly retry
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(50)])
    def test_invalid_credentials_do_not_repeatedly_retry(self, mock_time, mock_sleep):
        df = make_mock_shap_df(5, sarcastic=True)

        def handler(calls, contents):
            err = Exception("401 UNAUTHENTICATED: API_KEY_INVALID")
            setattr(err, 'code', '401')
            raise err

        mock_client = MockGenaiClient(handler_fn=handler)

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5
        )

        # Exactly 1 call, fatal stop immediately
        self.assertEqual(len(mock_client.calls), 1)
        self.assertTrue((report['reasoning_status'] == 'error').all())
        self.assertEqual(report.iloc[0]['reasoning_error_code'], '401')

    # -------------------------------------------------------------------------
    # 9: Invalid response IDs do not produce false completion
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(50)])
    def test_invalid_response_ids_do_not_produce_false_completion(self, mock_time, mock_sleep):
        df = make_mock_shap_df(5, sarcastic=True)

        def handler(calls, contents):
            # Return mismatching ID
            return MockGeminiResponse({
                'explanations': [
                    {'segment_id': 'seg_bogus_id', 'explanation': 'Bogus explanation.'}
                ]
            })

        mock_client = MockGenaiClient(handler_fn=handler)

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5
        )

        self.assertEqual(len(mock_client.calls), 1)
        # None marked completed
        self.assertEqual((report['reasoning_status'] == 'completed').sum(), 0)
        self.assertTrue((report['reasoning_status'] == 'error').all())
        self.assertEqual(report.iloc[0]['reasoning_error_code'], 'ValueError')
        # Cache file should not contain bogus ID
        cache = json.loads(self.cache_path.read_text(encoding='utf-8')) if self.cache_path.exists() else {}
        self.assertEqual(len(cache), 0)

    # -------------------------------------------------------------------------
    # 10: Failed batch preserves earlier successful explanations
    # -------------------------------------------------------------------------
    @patch('time.sleep', return_value=None)
    @patch('time.monotonic', side_effect=[i * 15.0 for i in range(50)])
    def test_failed_batch_preserves_earlier_successful_explanations(self, mock_time, mock_sleep):
        df = make_mock_shap_df(10, sarcastic=True)

        call_count = [0]
        def handler(calls, contents):
            call_count[0] += 1
            if call_count[0] == 1:
                items = json.loads(contents)
                return MockGeminiResponse({
                    'explanations': [{'segment_id': item['id'], 'explanation': f'Success for {item["id"]}.'} for item in items]
                })
            err = Exception("500 Internal Server Error")
            setattr(err, 'code', '500')
            raise err

        mock_client = MockGenaiClient(handler_fn=handler)

        report = li.repair_reasoning(
            frame=df,
            model_name='gemini-3.5-flash-lite',
            cache_path=self.cache_path,
            output_path=self.output_csv,
            make_client=lambda: mock_client,
            delay=15.0,
            batch_size=5
        )

        # Batch 1 succeeded, Batch 2 failed after 3 attempts = 4 total calls
        self.assertEqual(len(mock_client.calls), 4)
        # Batch 1 (first 5 segments) remain completed
        self.assertEqual((report.iloc[:5]['reasoning_status'] == 'completed').sum(), 5)
        # Batch 2 segments marked error
        self.assertEqual((report.iloc[5:]['reasoning_status'] == 'error').sum(), 5)

        # Cache file must retain the 5 completed explanations
        cache = json.loads(self.cache_path.read_text(encoding='utf-8'))
        self.assertEqual(len(cache), 5)
        # Final CSV saved
        csv_df = pd.read_csv(self.output_csv)
        self.assertEqual((csv_df.iloc[:5]['reasoning_status'] == 'completed').sum(), 5)

    # -------------------------------------------------------------------------
    # 11: Automatic and recovery paths use the same unified implementation
    # -------------------------------------------------------------------------
    def test_automatic_and_recovery_paths_use_same_implementation(self):
        # 1. Inspect Stage 8 string in STAGES
        stage8_source = dict(li.STAGES)['Gemini reasoning']
        # Must call repair_reasoning directly without duplicate embedded definition
        self.assertIn("report = repair_reasoning(", stage8_source)
        self.assertNotIn("def repair_reasoning(", stage8_source, "Embedded repair_reasoning duplicate must be removed")
        # Must preserve dedicated reasoning key settings
        self.assertIn("api_key = REASONING_API_KEY", stage8_source)
        self.assertNotIn("os.getenv('GEMINI_API_KEY'", stage8_source)

        # 2. Inspect manage_analysis.py recover
        import inspect
        recover_code = inspect.getsource(manage_analysis.run_recover)
        self.assertIn("inference.repair_reasoning(", recover_code)

        # 3. Both rely on li.repair_reasoning
        self.assertTrue(callable(li.repair_reasoning))

    # -------------------------------------------------------------------------
    # 12: Recovery returns nonzero (2) exit code on partial / incomplete runs
    # -------------------------------------------------------------------------
    @patch('manage_analysis.inference.repair_reasoning')
    def test_recovery_returns_nonzero_code_on_partial(self, mock_repair):
        # Return a dataframe with waiting_budget rows
        partial_df = make_mock_shap_df(10, sarcastic=True)
        partial_df['reasoning_status'] = 'waiting_budget'
        partial_df['ai_reasoning'] = 'Explanation paused due to rate limits.'
        partial_df['reasoning_error_code'] = '429'
        partial_df['reasoning_error'] = 'Daily limit reached'

        def mock_repair_side_effect(**kwargs):
            partial_df.to_csv(kwargs['output_path'], index=False)
            return partial_df

        mock_repair.side_effect = mock_repair_side_effect

        aid = 99
        owner_hash = hashlib.sha256(b"1").hexdigest()
        task_dir = self.dir_path / "analysis_runs" / owner_hash / str(aid)
        run_dir = task_dir / "run"
        run_dir.mkdir(parents=True)
        shap_csv = run_dir / "cineinsight_final_results_with_shap.csv"
        make_mock_shap_df(10, sarcastic=True).to_csv(shap_csv, index=False)

        mock_row = {
            "Analysis_Id": aid, "User_Id": 1, "User_Name": "Alice",
            "YouTube_url": "https://www.youtube.com/watch?v=test", "Aspect_Vise_Report": "{}"
        }
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [mock_row]
        mock_cursor.fetchone.return_value = mock_row

        with patch.object(manage_analysis.db, "_get_connection", return_value=mock_conn), \
             patch.object(manage_analysis.db, "save_final_analysis"), \
             patch.object(manage_analysis.inference, "reasoning_config", return_value=("test-key", "gemini-3.5-flash-lite")):
            args = SimpleNamespace(analysis_id=aid, gemini_model=None, skip_gemini=False)
            exit_code = manage_analysis.run_recover(args, instance_dir=self.dir_path)

        self.assertEqual(exit_code, 2, "Recovery must return 2 when work remains incomplete (CLI partial convention)")


if __name__ == '__main__':
    unittest.main()
