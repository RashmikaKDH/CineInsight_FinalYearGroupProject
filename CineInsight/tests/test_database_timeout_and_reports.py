"""
Focused regression tests for bounded database waits and DB-independent saved reports.

Tests:
1. Reports listing performs no database lookup.
2. Profile displays owned saved reports when its account query times out.
3. Login timeout produces a controlled response and no authenticated session.
4. Missing/deleted account and database timeout follow different paths.
5. Report ownership, newest-first ordering, latest-five limit, and malformed metadata handling.
6. Both connection factories (app.py and services/db_service.py) apply intended timeout settings.
"""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import mysql.connector
from flask import session

from app import app as full_app, get_db_connection
from services.db_service import _get_connection
from services.report_import import get_user_saved_reports


class DatabaseTimeoutAndReportsTests(unittest.TestCase):
    def setUp(self):
        full_app.config['TESTING'] = True
        full_app.config['WTF_CSRF_ENABLED'] = False
        full_app.config['SECRET_KEY'] = 'test-secret-key-1234'
        self.client = full_app.test_client()

    def set_session(self, user_id=1, name='Test User', email='user@example.com', role='User'):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['user_name'] = name
            sess['user_email'] = email
            sess['user_role'] = role

    # -------------------------------------------------------------------------
    # 1. Reports listing performs no database lookup
    # -------------------------------------------------------------------------
    def test_reports_listing_performs_no_database_lookup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            import hashlib
            owner = hashlib.sha256(b'1').hexdigest()
            rep_folder = Path(tmp_dir) / 'imported_reports' / owner
            rep_folder.mkdir(parents=True, exist_ok=True)

            rep_data = {
                'id': 'b' * 64,
                'title': 'Offline Standalone Report',
                'video_url': 'https://youtube.com/watch?v=offline',
                'analysis_date': '2026-10-18 10:00',
                'overall': {'positive': 88.0},
                'sarcasm_rate': 5.0,
                'total': 42,
                'pipeline_status': 'completed'
            }
            (rep_folder / (('b' * 64) + '.json')).write_text(json.dumps(rep_data), encoding='utf-8')

            # Patch database connection in both app and db_service to raise if called
            with patch('services.db_service._get_connection', side_effect=AssertionError('Database must not be called!')), \
                 patch('app.get_db_connection', side_effect=AssertionError('Database must not be called!')), \
                 patch('mysql.connector.connect', side_effect=AssertionError('Database must not be called!')):
                
                # Direct service call
                reports = get_user_saved_reports(tmp_dir, 1)
                self.assertEqual(len(reports), 1)
                self.assertEqual(reports[0]['title'], 'Offline Standalone Report')

                # Web route call
                self.set_session(user_id=1)
                with patch.object(full_app, 'instance_path', tmp_dir):
                    res = self.client.get('/reports')
                    self.assertEqual(res.status_code, 200)
                    self.assertIn(b'Offline Standalone Report', res.data)
                    self.assertIn(b'Saved Reports', res.data)
                    self.assertIn(b'YOUR ANALYSIS LIBRARY', res.data)

    # -------------------------------------------------------------------------
    # 2. Profile displays owned saved reports when its account query times out
    # -------------------------------------------------------------------------
    def test_profile_displays_owned_saved_reports_when_account_query_times_out(self):
        self.set_session(user_id=1, name='Timeout Tester', email='timeout@test.com', role='User')
        timeout_error = mysql.connector.errors.ReadTimeoutError(errno=3024, msg='Statement read timed out')

        mock_saved_reports = [
            {
                'id': 'c' * 64,
                'title': 'Timeout Test Movie Review',
                'video_url': 'https://youtube.com/watch?v=test',
                'date': '2026-10-19 12:00',
                'positive_score': 74.2,
                'sarcasm_rate': 8.5,
                'total': 120,
                'pipeline_status': 'completed'
            }
        ]

        with patch('app.get_db_connection', side_effect=timeout_error), \
             patch('services.report_import.get_user_saved_reports', return_value=mock_saved_reports):
            
            res = self.client.get('/profile')
            self.assertEqual(res.status_code, 200)
            # Profile uses session identity fallback
            self.assertIn(b'Timeout Tester', res.data)
            self.assertIn(b'timeout@test.com', res.data)
            # Brief notice banner is shown
            self.assertIn(b'Live account details are temporarily unavailable', res.data)
            # Saved reports are still displayed
            self.assertIn(b'Timeout Test Movie Review', res.data)
            self.assertIn(b'74.2% Positive', res.data)
            self.assertIn(b'8.5% Sarcasm', res.data)

    # -------------------------------------------------------------------------
    # 3. Login timeout produces a controlled response and no authenticated session
    # -------------------------------------------------------------------------
    def test_login_timeout_produces_controlled_response_and_no_authenticated_session(self):
        conn_timeout_error = mysql.connector.errors.ConnectionTimeoutError(errno=2003, msg='Connection timed out')

        with patch('app.get_db_connection', side_effect=conn_timeout_error):
            res = self.client.post('/signin', data={'email': 'alice@example.com', 'password': 'secretpassword'})
            # Returns HTTP 503 Service Unavailable
            self.assertEqual(res.status_code, 503)
            # Friendly error message is rendered without exposing internal DB details
            self.assertIn(b'Service temporarily unavailable', res.data)
            self.assertNotIn(b'2003', res.data)
            self.assertNotIn(b'cineinsight_db', res.data)

            # Session is not populated
            with self.client.session_transaction() as sess:
                self.assertNotIn('user_id', sess)
                self.assertNotIn('user_name', sess)

    # -------------------------------------------------------------------------
    # 4. Missing/deleted account and database timeout follow different paths
    # -------------------------------------------------------------------------
    def test_missing_or_deleted_account_and_database_timeout_follow_different_paths(self):
        # Path A: Database timeout -> stays on profile, shows session info and warning banner
        self.set_session(user_id=1, name='Alice Session', email='alice@session.com', role='User')
        with patch('app.get_db_connection', side_effect=TimeoutError('Socket timeout')), \
             patch('services.report_import.get_user_saved_reports', return_value=[]):
            res_timeout = self.client.get('/profile')
            self.assertEqual(res_timeout.status_code, 200)
            self.assertIn(b'Live account details are temporarily unavailable', res_timeout.data)
            self.assertIn(b'Alice Session', res_timeout.data)
            # User is still authenticated in session
            with self.client.session_transaction() as sess:
                self.assertEqual(sess.get('user_id'), 1)

        # Path B: Database query succeeds without errors, but user record is NOT found (deleted account)
        self.set_session(user_id=8888, name='Deleted User', email='deleted@user.com', role='User')
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # user not found in DB
        mock_conn.cursor.return_value = mock_cursor

        with patch('app.get_db_connection', return_value=mock_conn):
            res_deleted = self.client.get('/profile')
            # Must NOT silently present deleted account as active; redirects to signin
            self.assertEqual(res_deleted.status_code, 302)
            self.assertTrue(res_deleted.headers['Location'].endswith('/signin'))
            # Session must be cleared
            with self.client.session_transaction() as sess:
                self.assertNotIn('user_id', sess)

    # -------------------------------------------------------------------------
    # 5. Report ownership, newest-first ordering, latest-five limit, and malformed metadata
    # -------------------------------------------------------------------------
    def test_report_ownership_newest_first_limit_and_malformed_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            import hashlib
            owner1 = hashlib.sha256(b'1').hexdigest()
            owner2 = hashlib.sha256(b'2').hexdigest()

            dir1 = Path(tmp_dir) / 'imported_reports' / owner1
            dir2 = Path(tmp_dir) / 'imported_reports' / owner2
            dir1.mkdir(parents=True, exist_ok=True)
            dir2.mkdir(parents=True, exist_ok=True)

            # Create 7 valid reports for user 1
            for i in range(1, 8):
                rep_id = hex(i)[2:].zfill(64)
                rep_path = dir1 / f"{rep_id}.json"
                rep_path.write_text(json.dumps({
                    'id': rep_id,
                    'title': f"User 1 Report {i}",
                    'video_url': f"https://youtube.com/watch?v={i}",
                    'analysis_date': f"2026-10-{10+i:02d} 10:00",
                    'overall': {'positive': 50.0 + i},
                    'sarcasm_rate': 10.0 + i,
                    'total': 100 + i,
                    'pipeline_status': 'completed'
                }), encoding='utf-8')
                # Explicitly space mtime to test newest-first sort
                os.utime(rep_path, (1700000000 + i * 100, 1700000000 + i * 100))

            # Add malformed files for user 1:
            # - invalid JSON
            bad_json = dir1 / "bad_syntax.json"
            bad_json.write_text("{this is not json}", encoding='utf-8')
            # - non-dict JSON (array)
            non_dict = dir1 / "array.json"
            non_dict.write_text("[1, 2, 3]", encoding='utf-8')
            # - missing optional fields
            partial_rep = dir1 / ("e" * 64 + ".json")
            partial_rep.write_text(json.dumps({
                'id': "e" * 64,
                'video_url': "https://youtube.com/watch?v=fallback_title"
                # Missing title, analysis_date, overall, sarcasm_rate, total
            }), encoding='utf-8')
            os.utime(partial_rep, (1700000000 + 800, 1700000000 + 800))

            # Create a report for user 2
            u2_rep = dir2 / ("f" * 64 + ".json")
            u2_rep.write_text(json.dumps({
                'id': "f" * 64,
                'title': "User 2 Secret Report",
                'video_url': "https://youtube.com/watch?v=secret"
            }), encoding='utf-8')

            # Fetch for User 1 with limit=5
            reports_user1_limit5 = get_user_saved_reports(tmp_dir, 1, limit=5)
            self.assertEqual(len(reports_user1_limit5), 5)

            # Newest first: partial_rep had timestamp 1700000800, rep 7 had 1700000700
            self.assertEqual(reports_user1_limit5[0]['id'], "e" * 64)
            self.assertEqual(reports_user1_limit5[0]['title'], "https://youtube.com/watch?v=fallback_title")
            self.assertIsNotNone(reports_user1_limit5[0]['date'])  # fell back to file mtime
            self.assertEqual(reports_user1_limit5[1]['title'], "User 1 Report 7")

            # Fetch all for User 1
            reports_user1_all = get_user_saved_reports(tmp_dir, 1)
            # 7 valid reports + 1 partial report = 8 (malformed syntax and array were skipped)
            self.assertEqual(len(reports_user1_all), 8)

            # Verify User 2's report was NEVER leaked to User 1
            titles = [r['title'] for r in reports_user1_all]
            self.assertNotIn("User 2 Secret Report", titles)

            # Verify User 2 only sees their report
            reports_user2 = get_user_saved_reports(tmp_dir, 2)
            self.assertEqual(len(reports_user2), 1)
            self.assertEqual(reports_user2[0]['title'], "User 2 Secret Report")

    # -------------------------------------------------------------------------
    # 6. Both connection factories apply intended timeout settings
    # -------------------------------------------------------------------------
    def test_both_connection_factories_apply_intended_timeout_settings(self):
        with patch('mysql.connector.connect') as mock_connect:
            get_db_connection()
            mock_connect.assert_called_once()
            _, kwargs = mock_connect.call_args
            self.assertEqual(kwargs.get('connection_timeout'), 5)
            self.assertEqual(kwargs.get('read_timeout'), 10)
            self.assertEqual(kwargs.get('write_timeout'), 10)

        with patch('mysql.connector.connect') as mock_connect:
            _get_connection()
            mock_connect.assert_called_once()
            _, kwargs = mock_connect.call_args
            self.assertEqual(kwargs.get('connection_timeout'), 5)
            self.assertEqual(kwargs.get('read_timeout'), 10)
            self.assertEqual(kwargs.get('write_timeout'), 10)


if __name__ == '__main__':
    unittest.main()
