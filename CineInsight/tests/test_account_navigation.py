"""
Tests for user account navigation and saved-reports library functionality.

Verifies:
  - Shared account panel presence and rendering across Dashboard, Profile, Admin,
    Reports, Results, and Analysis pages.
  - Dropdown contains user name, email, My Profile, My Reports, Sign Out (POST).
  - Admin Panel link in dropdown only rendered for Admin role.
  - Home page reflects logged-out vs logged-in state.
  - Dashboard removes old standalone Colab import text link.
  - Profile renders My Reports section with latest 5 reports, empty state, and 'View all reports'.
  - Reports library (/reports) displays saved reports, empty state, and backup manual import link.
  - Manual import backup route (/reports/import) is accessible and authenticated.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from flask import Flask, session
from services.report_import import reports, get_user_saved_reports
from app import app as full_app

ROOT = Path(__file__).resolve().parents[1]


class AccountNavigationTests(unittest.TestCase):
    def setUp(self):
        full_app.config['TESTING'] = True
        full_app.config['WTF_CSRF_ENABLED'] = False
        self.client = full_app.test_client()

    def set_session(self, user_id=1, name='Alice Smith', email='alice@example.com', role='User'):
        with self.client.session_transaction() as s:
            s['user_id'] = user_id
            s['user_name'] = name
            s['user_email'] = email
            s['user_role'] = role

    def clear_session(self):
        with self.client.session_transaction() as s:
            s.clear()

    # -------------------------------------------------------------------------
    # Requirement 1: Shared user account panel
    # -------------------------------------------------------------------------
    def test_shared_account_panel_user_role(self):
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        # Name and avatar
        self.assertIn(b'Alice', res.data)
        self.assertIn(b'data-name="Alice Smith"', res.data)
        # Dropdown contents
        self.assertIn(b'user-dropdown-menu', res.data)
        self.assertIn(b'alice@example.com', res.data)
        self.assertIn(b'My Profile', res.data)
        self.assertIn(b'My Reports', res.data)
        # Normal user must NOT see Admin Panel in dropdown
        self.assertNotIn(b'Admin Panel</a>', res.data)
        # Sign Out form with POST method
        self.assertIn(b'action="/logout"', res.data)
        self.assertIn(b'method="post"', res.data)
        self.assertIn(b'Sign Out', res.data)

    def test_shared_account_panel_admin_role(self):
        self.set_session(user_id=2, name='Admin Bob', email='admin@example.com', role='Admin')
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Admin Bob', res.data)
        self.assertIn(b'admin@example.com', res.data)
        # Admin user MUST see Admin Panel link in dropdown
        self.assertIn(b'Admin Panel', res.data)
        self.assertIn(b'href="/admin"', res.data)

    def test_shared_header_across_authenticated_pages(self):
        self.set_session(user_id=2, name='Admin Bob', email='admin@example.com', role='Admin')
        pages = ['/dashboard', '/reports', '/profile', '/admin']
        for page in pages:
            with self.subTest(page=page):
                res = self.client.get(page)
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'user-menu-button', res.data)
                self.assertIn(b'user-dropdown-menu', res.data)
                self.assertIn(b'Admin Bob', res.data)

    # -------------------------------------------------------------------------
    # Requirement 2: Home page
    # -------------------------------------------------------------------------
    def test_home_page_logged_out(self):
        self.clear_session()
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Sign In', res.data)
        self.assertIn(b'Get Started', res.data)
        self.assertNotIn(b'user-menu-button', res.data)

    def test_home_page_logged_in(self):
        self.set_session(user_id=1, name='Carol Danvers', email='carol@example.com', role='User')
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        # Dashboard access and account panel
        self.assertIn(b'Dashboard', res.data)
        self.assertIn(b'user-menu-button', res.data)
        self.assertIn(b'Carol', res.data)

    # -------------------------------------------------------------------------
    # Requirement 3: Dashboard old link removed
    # -------------------------------------------------------------------------
    def test_dashboard_removed_old_import_link(self):
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'Import Colab Report / Saved Reports', res.data)
        # Video search elements still present
        self.assertIn(b'review-link-input', res.data)
        self.assertIn(b'btn-search', res.data)

    # -------------------------------------------------------------------------
    # Requirement 4: Profile My Reports section
    # -------------------------------------------------------------------------
    def test_profile_my_reports_empty_state(self):
        self.set_session(user_id=9999, name='New User', email='new@example.com', role='User')
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'User_Id': 9999, 'Name': 'New User', 'Email': 'new@example.com', 'Role': 'User'
        }
        mock_conn.cursor.return_value = mock_cursor
        with patch('app.get_db_connection', return_value=mock_conn), \
             patch('services.report_import.get_user_saved_reports', return_value=[]):
            res = self.client.get('/profile')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'My Reports', res.data)
            self.assertIn(b'No saved reports yet', res.data)
            self.assertIn(b'Analyze a Movie Review', res.data)

    def test_profile_my_reports_with_data(self):
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        mock_reports = [
            {
                'id': 'a' * 64,
                'title': 'Dune Part Two Review',
                'video_url': 'https://youtube.com/watch?v=1',
                'date': '2026-10-15 14:00',
                'positive_score': 85.5,
                'sarcasm_rate': 12.0,
                'total': 150,
                'pipeline_status': 'completed'
            }
        ]
        with patch('services.report_import.get_user_saved_reports', return_value=mock_reports):
            res = self.client.get('/profile')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'My Reports', res.data)
            self.assertIn(b'Dune Part Two Review', res.data)
            self.assertIn(b'85.5% Positive', res.data)
            self.assertIn(b'12.0% Sarcasm', res.data)
            self.assertIn(b'/reports/' + (b'a' * 64), res.data)
            self.assertIn(b'View all reports', res.data)

    # -------------------------------------------------------------------------
    # Requirement 5: Reports page as saved-reports library and backup import
    # -------------------------------------------------------------------------
    def test_reports_library_normal_view(self):
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        mock_reports = [
            {
                'id': 'b' * 64,
                'title': 'Oppenheimer Review',
                'video_url': 'https://youtube.com/watch?v=2',
                'date': '2026-10-16 10:30',
                'positive_score': 90.0,
                'sarcasm_rate': 5.0,
                'total': 120,
                'pipeline_status': 'completed'
            }
        ]
        with patch('services.report_import.get_user_saved_reports', return_value=mock_reports):
            res = self.client.get('/reports')
            self.assertEqual(res.status_code, 200)
            # Saved Reports Library title and wording
            self.assertIn(b'Saved Reports', res.data)
            self.assertIn(b'YOUR ANALYSIS LIBRARY', res.data)
            self.assertIn(b'Oppenheimer Review', res.data)
            self.assertIn(b'90.0%', res.data)
            self.assertIn(b'View Report', res.data)
            self.assertIn(b'CSV', res.data)
            # Prominent Colab instructions and import form removed from normal view
            self.assertNotIn(b'id="import-form"', res.data)
            # Discreet backup import link is available
            self.assertIn(b'/reports/import', res.data)

    def test_reports_library_empty_state(self):
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        with patch('services.report_import.get_user_saved_reports', return_value=[]):
            res = self.client.get('/reports')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'No saved reports yet', res.data)
            self.assertIn(b'Go to Dashboard', res.data)
            self.assertIn(b'/reports/import', res.data)

    def test_manual_import_backup_route_auth_and_rendering(self):
        # Logged out redirect
        self.clear_session()
        res = self.client.get('/reports/import')
        self.assertEqual(res.status_code, 302)

        # Logged in access
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        res = self.client.get('/reports/import')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Manual Colab Report Import', res.data)
        self.assertIn(b'id="import-form"', res.data)
        self.assertIn(b'Back to Saved Reports', res.data)

    def test_get_user_saved_reports_isolation_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp_instance:
            import hashlib
            owner1 = hashlib.sha256(b'1').hexdigest()
            owner2 = hashlib.sha256(b'2').hexdigest()
            dir1 = Path(tmp_instance) / 'imported_reports' / owner1
            dir2 = Path(tmp_instance) / 'imported_reports' / owner2
            dir1.mkdir(parents=True)
            dir2.mkdir(parents=True)

            # Create 7 reports for user 1
            import time
            for i in range(7):
                rep_id = f"{i:02d}" * 32
                payload = {
                    'id': rep_id,
                    'title': f'Movie Review #{i}',
                    'video_url': f'https://youtube.com/watch?v={i}',
                    'analysis_date': f'2026-10-1{i} 12:00',
                    'overall': {'positive': 80 + i, 'total': 100},
                    'sarcasm_rate': float(i * 3),
                    'total': 100 + i,
                    'pipeline_status': 'completed'
                }
                p = dir1 / f"{rep_id}.json"
                p.write_text(json.dumps(payload), encoding='utf-8')
                # ensure distinct mtime
                import os
                os.utime(p, (time.time() + i * 10, time.time() + i * 10))

            # Create 1 report for user 2
            rep2_id = "ff" * 32
            payload2 = {
                'id': rep2_id,
                'title': 'User 2 Private Report',
                'video_url': 'https://youtube.com/watch?v=secret',
                'overall': {'positive': 50.0},
                'sarcasm_rate': 20.0,
                'total': 50
            }
            (dir2 / f"{rep2_id}.json").write_text(json.dumps(payload2), encoding='utf-8')

            # Fetch for user 1 with limit=5
            res1_limited = get_user_saved_reports(tmp_instance, 1, limit=5)
            self.assertEqual(len(res1_limited), 5)
            # Most recent first
            self.assertEqual(res1_limited[0]['title'], 'Movie Review #6')
            self.assertEqual(res1_limited[0]['positive_score'], 86)
            self.assertEqual(res1_limited[0]['sarcasm_rate'], 18.0)

            # Fetch all for user 1
            res1_all = get_user_saved_reports(tmp_instance, 1)
            self.assertEqual(len(res1_all), 7)
            # Must NOT contain user 2's report
            self.assertFalse(any(r['title'] == 'User 2 Private Report' for r in res1_all))

            # Fetch for user 2
            res2 = get_user_saved_reports(tmp_instance, 2)
            self.assertEqual(len(res2), 1)
            self.assertEqual(res2[0]['title'], 'User 2 Private Report')
            self.assertFalse(any('Movie Review' in r['title'] for r in res2))

            # Fetch for user with no folder
            res3 = get_user_saved_reports(tmp_instance, 999)
            self.assertEqual(res3, [])

    def test_analysis_page_renders_account_panel(self):
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        res = self.client.get('/analysis')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'user-menu-button', res.data)
        self.assertIn(b'user-dropdown-menu', res.data)
        self.assertIn(b'Alice', res.data)

    def test_results_page_renders_account_panel(self):
        self.set_session(user_id=1, name='Alice Smith', email='alice@example.com', role='User')
        with tempfile.TemporaryDirectory() as tmp_instance:
            import hashlib
            owner1 = hashlib.sha256(b'1').hexdigest()
            folder = Path(tmp_instance) / 'imported_reports' / owner1
            folder.mkdir(parents=True)
            rep_id = 'e' * 64
            report_data = {
                'id': rep_id,
                'title': 'Test Movie Review',
                'total': 10,
                'sarcastic': 2,
                'sarcasm_rate': 20.0,
                'overall': {'positive': 80.0, 'total': 10, 'excluded': 0, 'counts': {'positive': 8}},
                'aspects': {'acting': {'positive': 100.0, 'total': 5, 'excluded': 0, 'counts': {'positive': 5}}},
                'reasons': [],
                'conclusion': 'Great review.'
            }
            (folder / f"{rep_id}.json").write_text(json.dumps(report_data), encoding='utf-8')
            (folder / f"{rep_id}.csv").write_bytes(b'header\nrow\n')

            with patch('services.report_import.store_dir', return_value=folder):
                res = self.client.get(f'/reports/{rep_id}')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'user-menu-button', res.data)
                self.assertIn(b'user-dropdown-menu', res.data)
                self.assertIn(b'Test Movie Review', res.data)


if __name__ == '__main__':
    unittest.main()
