"""Comprehensive unit and integration tests for CineInsight manage_analysis.py.

Covers:
1. List/preview and confirmation cancellation (requiring typing RESET).
2. Selected-analysis removal with unrelated analyses preserved.
3. Request/report mappings removed correctly.
4. Transaction already active after preview SELECT handled cleanly.
5. Owner or existence changing between preview and deletion.
6. DB failure rolls back and restores files.
7. Restore failure retains quarantine and manifest with clear error.
8. Cleanup failure after successful DB commit does not restore files.
9. Active, queued and stale worker states distinguished across processes.
10. Shared-cache lock contention aborts without modifying analysis.
11. Shared-cache partial cleanup reported accurately.
12. Unsafe paths and symlink hierarchy rejection (not silently skipped).
13. Missing files handled gracefully.
14. Stale browser ID recovery without automatic resubmission.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import manage_analysis
from manage_analysis import (
    clear_shared_aspect_cache,
    find_analysis_artifacts,
    has_symlink_or_junction_in_hierarchy,
    is_path_safe,
    list_analyses,
    run_list,
    run_reset,
    staged_delete_analysis,
    verify_safe_path,
)
from src.extractors.cache_lock import CrossProcessLock
from services import analysis_worker


class RealisticMockCursor:
    def __init__(self, connection):
        self.conn = connection
        self.rowcount = 1
        self.executed = []
        self._current_result = []

    def execute(self, query, params=None):
        self.executed.append((query, params))
        self.conn.in_transaction = True

        if self.conn.fail_on_execute:
            raise RuntimeError("Simulated query execution failure")

        q_upper = query.strip().upper()
        if "SELECT" in q_upper and "FOR UPDATE" in q_upper:
            # Locking read
            if self.conn.for_update_row is not None:
                self._current_result = [self.conn.for_update_row]
            else:
                self._current_result = []
        elif "SELECT" in q_upper:
            self._current_result = list(self.conn.preview_rows)
        elif "DELETE FROM ANALYSIS" in q_upper:
            self.conn.mutation_executed = True
            self.rowcount = self.conn.analysis_delete_rowcount
        elif "DELETE FROM REASONING_REPORT" in q_upper:
            self.conn.mutation_executed = True
            self.rowcount = self.conn.reasoning_delete_rowcount

    def fetchone(self):
        return self._current_result.pop(0) if self._current_result else None

    def fetchall(self):
        res = list(self._current_result)
        self._current_result = []
        return res

    def close(self):
        pass


class RealisticMockConnection:
    """Mock connection that simulates MySQL transaction rules."""

    def __init__(self, preview_rows=None, for_update_row=None, fail_on_execute=False):
        self.preview_rows = preview_rows or []
        self.for_update_row = for_update_row
        self.fail_on_execute = fail_on_execute
        self.in_transaction = False
        self.committed = False
        self.rolled_back = False
        self.mutation_executed = False
        self.analysis_delete_rowcount = 1
        self.reasoning_delete_rowcount = 1
        self.cursor_obj = RealisticMockCursor(self)

    def cursor(self, dictionary=False):
        return self.cursor_obj

    def start_transaction(self):
        if self.in_transaction:
            raise RuntimeError("Transaction already in progress.")
        self.in_transaction = True

    def commit(self):
        self.in_transaction = False
        self.committed = True

    def rollback(self):
        self.in_transaction = False
        self.rolled_back = True

    def close(self):
        pass


class TestManageAnalysis(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.instance_dir = self.root / "instance"
        self.instance_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.root / "data" / "cache" / "aspect_sentiment"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Structure for user 1 (owner_hash)
        self.user_id_1 = 1
        self.owner_hash_1 = hashlib.sha256(str(self.user_id_1).encode()).hexdigest()
        self.user_runs_1 = self.instance_dir / "analysis_runs" / self.owner_hash_1
        self.user_reports_1 = self.instance_dir / "imported_reports" / self.owner_hash_1
        self.user_runs_1.mkdir(parents=True, exist_ok=True)
        self.user_reports_1.mkdir(parents=True, exist_ok=True)

        # Structure for user 2
        self.user_id_2 = 2
        self.owner_hash_2 = hashlib.sha256(str(self.user_id_2).encode()).hexdigest()
        self.user_runs_2 = self.instance_dir / "analysis_runs" / self.owner_hash_2
        self.user_reports_2 = self.instance_dir / "imported_reports" / self.owner_hash_2
        self.user_runs_2.mkdir(parents=True, exist_ok=True)
        self.user_reports_2.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. List / Preview & Confirmation Cancellation
    # -------------------------------------------------------------------------
    def test_manifest_exists_before_first_move(self):
        aid=811
        folder=self.user_runs_1/str(aid);folder.mkdir()
        source=folder/'prepared.csv';source.write_text('important')
        artifacts=find_analysis_artifacts(self.instance_dir,1,aid)
        conn=RealisticMockConnection(for_update_row={'Analysis_Id':aid,'User_Id':1,'Video_Id':5})
        original_move=shutil.move
        def checked_move(src,dst):
            manifest=next((self.instance_dir/'.staging_trash').glob('*/recovery_manifest.json'))
            data=json.loads(manifest.read_text())
            self.assertTrue(any(i['original']==str(source) and i['state']=='planned' for i in data['items']))
            return original_move(src,dst)
        with patch('manage_analysis.shutil.move',side_effect=checked_move):
            result=staged_delete_analysis(self.instance_dir,1,aid,artifacts,db_conn=conn)
        self.assertTrue(result['success'])

    def test_preview_commit_failure_aborts_before_mutation(self):
        row={'Analysis_Id':812,'User_Id':1,'Video_Id':5,'Analysis_Date':'date','Aspect_Vise_Report':None,'YouTube_url':'url','Title':'name','Name':'user'}
        conn=RealisticMockConnection(preview_rows=[row])
        with patch('manage_analysis.db._get_connection',return_value=conn), \
             patch.object(conn,'commit',side_effect=RuntimeError('commit failed')), \
             patch('manage_analysis.staged_delete_analysis') as deletion:
            result=run_reset(SimpleNamespace(analysis_id=812,clear_aspect_cache=False),confirm_fn=lambda:'RESET')
        self.assertEqual(result,1);deletion.assert_not_called();self.assertTrue(conn.rolled_back)

    def test_list_analyses_formats_output_and_hides_credentials(self):
        mock_rows = [
            {
                "Analysis_Id": 101,
                "User_Id": 1,
                "User_Name": "Alice",
                "User_Email": "alice@example.com",
                "Video_Id": 5,
                "Video_Title": "Film Review 1",
                "YouTube_url": "https://www.youtube.com/watch?v=abc101",
                "Analysis_Date": "2026-10-14 10:00:00",
                "Overall_Sentiment_Score": 0.85,
                "Sarcasm_Flag": 0,
                "Aspect_Vise_Report": json.dumps({"status": "completed", "aspects": {}}),
            }
        ]
        mock_conn = RealisticMockConnection(preview_rows=mock_rows)
        results = list_analyses(db_conn=mock_conn)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["analysis_id"], 101)
        self.assertEqual(item["user_id"], 1)
        self.assertEqual(item["status"], "completed")
        self.assertEqual(item["video_url"], "https://www.youtube.com/watch?v=abc101")
        for key in item.keys():
            self.assertNotIn("password", key.lower())
            self.assertNotIn("token", key.lower())
            self.assertNotIn("secret", key.lower())

    def test_reset_confirmation_cancellation(self):
        """When user types something other than 'RESET', operation aborts cleanly."""
        aid = 101
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "task.json"
        task_file.write_text(json.dumps({"status": "completed"}), encoding="utf-8")

        mock_row = {
            "Analysis_Id": aid,
            "User_Id": self.user_id_1,
            "Video_Id": 5,
            "Analysis_Date": "2026-10-14 10:00:00",
            "Aspect_Vise_Report": json.dumps({"status": "completed"}),
            "YouTube_url": "https://www.youtube.com/watch?v=abc101",
            "Title": "Test Movie",
            "Name": "Alice",
        }
        mock_conn = RealisticMockConnection(preview_rows=[mock_row], for_update_row=mock_row)
        args = SimpleNamespace(analysis_id=aid, clear_aspect_cache=False)

        with patch("manage_analysis.get_instance_dir", return_value=self.instance_dir), \
             patch("manage_analysis.db._get_connection", return_value=mock_conn):
            # Injected confirmation says "NO"
            exit_code = run_reset(args, confirm_fn=lambda: "NO")

        self.assertEqual(exit_code, 0)
        self.assertTrue(task_file.exists())
        self.assertFalse(mock_conn.mutation_executed)

    # -------------------------------------------------------------------------
    # 2. Selected-Analysis Removal with Unrelated Analyses Preserved
    # -------------------------------------------------------------------------
    def test_selected_analysis_removal_preserves_unrelated(self):
        aid1 = 101
        aid2 = 102

        # Create files for Analysis 101
        task_dir_1 = self.user_runs_1 / str(aid1)
        task_dir_1.mkdir(parents=True, exist_ok=True)
        (task_dir_1 / "task.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        prep_dir_1 = task_dir_1 / "prepared"
        prep_dir_1.mkdir(parents=True, exist_ok=True)
        (prep_dir_1 / "video.mp4").write_text("mp4data", encoding="utf-8")
        (prep_dir_1 / "input.csv").write_text("csvdata", encoding="utf-8")

        # Create files for Analysis 102
        task_dir_2 = self.user_runs_1 / str(aid2)
        task_dir_2.mkdir(parents=True, exist_ok=True)
        task2_file = task_dir_2 / "task.json"
        task2_file.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        prep_dir_2 = task_dir_2 / "prepared"
        prep_dir_2.mkdir(parents=True, exist_ok=True)
        video2 = prep_dir_2 / "video.mp4"
        video2.write_text("mp4data_2", encoding="utf-8")

        artifacts_1 = find_analysis_artifacts(self.instance_dir, self.user_id_1, aid1)
        mock_row = {"Analysis_Id": aid1, "User_Id": self.user_id_1, "Video_Id": 5}
        mock_conn = RealisticMockConnection(for_update_row=mock_row)

        res = staged_delete_analysis(
            instance_dir=self.instance_dir,
            user_id=self.user_id_1,
            analysis_id=aid1,
            artifacts=artifacts_1,
            db_conn=mock_conn,
        )

        self.assertTrue(res["success"])
        self.assertFalse((prep_dir_1 / "video.mp4").exists())
        self.assertTrue(task2_file.exists())
        self.assertTrue(video2.exists())
        self.assertEqual(video2.read_text(encoding="utf-8"), "mp4data_2")

    # -------------------------------------------------------------------------
    # 3. Request / Report Mappings Removed Correctly
    # -------------------------------------------------------------------------
    def test_request_and_report_mappings_removed(self):
        aid1 = 101
        aid2 = 102

        req_dir = self.user_runs_1 / "requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        marker1 = req_dir / "req_101.json"
        marker1.write_text(json.dumps({"analysis_id": aid1, "url": "https://youtu.be/101"}), encoding="utf-8")
        marker2 = req_dir / "req_102.json"
        marker2.write_text(json.dumps({"analysis_id": aid2, "url": "https://youtu.be/102"}), encoding="utf-8")

        rep1_json = self.user_reports_1 / "rep_101.json"
        rep1_json.write_text(json.dumps({"analysis_id": aid1, "id": "rep_101"}), encoding="utf-8")
        rep1_csv = self.user_reports_1 / "rep_101.csv"
        rep1_csv.write_text("csvcontent1", encoding="utf-8")

        rep2_json = self.user_reports_1 / "rep_102.json"
        rep2_json.write_text(json.dumps({"analysis_id": aid2, "id": "rep_102"}), encoding="utf-8")

        artifacts_1 = find_analysis_artifacts(self.instance_dir, self.user_id_1, aid1)
        mock_row = {"Analysis_Id": aid1, "User_Id": self.user_id_1, "Video_Id": 5}
        mock_conn = RealisticMockConnection(for_update_row=mock_row)

        staged_delete_analysis(
            instance_dir=self.instance_dir,
            user_id=self.user_id_1,
            analysis_id=aid1,
            artifacts=artifacts_1,
            db_conn=mock_conn,
        )

        self.assertFalse(marker1.exists())
        self.assertFalse(rep1_json.exists())
        self.assertFalse(rep1_csv.exists())
        self.assertTrue(marker2.exists())
        self.assertTrue(rep2_json.exists())

    # -------------------------------------------------------------------------
    # 4. Database Transaction Handling (Preview SELECT active transaction)
    # -------------------------------------------------------------------------
    def test_transaction_already_active_after_preview_select_handled(self):
        """Verify that preview read transaction is committed so start_transaction does not fail."""
        aid = 101
        mock_row = {
            "Analysis_Id": aid,
            "User_Id": self.user_id_1,
            "Video_Id": 5,
            "Analysis_Date": "2026-10-14 10:00:00",
            "Aspect_Vise_Report": json.dumps({"status": "completed"}),
            "YouTube_url": "https://www.youtube.com/watch?v=abc101",
            "Title": "Test Movie",
            "Name": "Alice",
        }
        mock_conn = RealisticMockConnection(preview_rows=[mock_row], for_update_row=mock_row)
        args = SimpleNamespace(analysis_id=aid, clear_aspect_cache=False)

        with patch("manage_analysis.get_instance_dir", return_value=self.instance_dir), \
             patch("manage_analysis.db._get_connection", return_value=mock_conn):
            exit_code = run_reset(args, confirm_fn=lambda: "RESET")

        self.assertEqual(exit_code, 0)
        self.assertTrue(mock_conn.committed)

    # -------------------------------------------------------------------------
    # 5. Owner / Existence Changing Between Preview and Deletion
    # -------------------------------------------------------------------------
    def test_analysis_deleted_between_preview_and_deletion_aborts(self):
        aid = 101
        mock_preview = {
            "Analysis_Id": aid,
            "User_Id": self.user_id_1,
            "Video_Id": 5,
            "Analysis_Date": "2026-10-14 10:00:00",
            "Aspect_Vise_Report": json.dumps({"status": "completed"}),
            "YouTube_url": "https://www.youtube.com/watch?v=abc101",
            "Title": "Test Movie",
            "Name": "Alice",
        }
        # for_update_row is None -> row was deleted concurrently
        mock_conn = RealisticMockConnection(preview_rows=[mock_preview], for_update_row=None)
        args = SimpleNamespace(analysis_id=aid, clear_aspect_cache=False)

        with patch("manage_analysis.get_instance_dir", return_value=self.instance_dir), \
             patch("manage_analysis.db._get_connection", return_value=mock_conn):
            exit_code = run_reset(args, confirm_fn=lambda: "RESET")

        self.assertEqual(exit_code, 2)
        self.assertTrue(mock_conn.rolled_back)

    def test_owner_changed_between_preview_and_deletion_aborts(self):
        aid = 101
        mock_preview = {
            "Analysis_Id": aid,
            "User_Id": self.user_id_1,
            "Video_Id": 5,
            "Analysis_Date": "2026-10-14 10:00:00",
            "Aspect_Vise_Report": json.dumps({"status": "completed"}),
            "YouTube_url": "https://www.youtube.com/watch?v=abc101",
            "Title": "Test Movie",
            "Name": "Alice",
        }
        # Ownership changed to User 99
        mock_update = {"Analysis_Id": aid, "User_Id": 99, "Video_Id": 5}
        mock_conn = RealisticMockConnection(preview_rows=[mock_preview], for_update_row=mock_update)
        args = SimpleNamespace(analysis_id=aid, clear_aspect_cache=False)

        with patch("manage_analysis.get_instance_dir", return_value=self.instance_dir), \
             patch("manage_analysis.db._get_connection", return_value=mock_conn):
            exit_code = run_reset(args, confirm_fn=lambda: "RESET")

        self.assertEqual(exit_code, 2)
        self.assertTrue(mock_conn.rolled_back)

    # -------------------------------------------------------------------------
    # 6. DB Failure Rolls Back and Restores Staged Files
    # -------------------------------------------------------------------------
    def test_db_failure_rolls_back_and_restores_files(self):
        aid = 302
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "task.json"
        task_file.write_text("critical_task_data", encoding="utf-8")

        artifacts = find_analysis_artifacts(self.instance_dir, self.user_id_1, aid)
        mock_row = {"Analysis_Id": aid, "User_Id": self.user_id_1, "Video_Id": 5}
        mock_conn = RealisticMockConnection(for_update_row=mock_row, fail_on_execute=True)

        with self.assertRaises(RuntimeError):
            staged_delete_analysis(
                instance_dir=self.instance_dir,
                user_id=self.user_id_1,
                analysis_id=aid,
                artifacts=artifacts,
                db_conn=mock_conn,
            )

        self.assertTrue(mock_conn.rolled_back)
        self.assertFalse(mock_conn.committed)
        self.assertTrue(task_file.exists())
        self.assertEqual(task_file.read_text(encoding="utf-8"), "critical_task_data")

    # -------------------------------------------------------------------------
    # 7. Restore Failure Retains Quarantine and Manifest
    # -------------------------------------------------------------------------
    def test_restore_failure_retains_quarantine_and_manifest(self):
        aid = 303
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "task.json"
        task_file.write_text("precious_data", encoding="utf-8")

        artifacts = find_analysis_artifacts(self.instance_dir, self.user_id_1, aid)
        mock_row = {"Analysis_Id": aid, "User_Id": self.user_id_1, "Video_Id": 5}
        mock_conn = RealisticMockConnection(for_update_row=mock_row, fail_on_execute=True)

        # Patch shutil.move during the restore phase to raise PermissionError
        original_move = shutil.move
        def move_with_restore_failure(src, dst):
            # Fail only when restoring from staging to instance
            if ".staging_trash" in str(src):
                raise PermissionError("Simulated locked file restore failure")
            return original_move(src, dst)

        with patch("shutil.move", side_effect=move_with_restore_failure):
            with self.assertRaises(RuntimeError) as cm:
                staged_delete_analysis(
                    instance_dir=self.instance_dir,
                    user_id=self.user_id_1,
                    analysis_id=aid,
                    artifacts=artifacts,
                    db_conn=mock_conn,
                )

        self.assertIn("CRITICAL: Rollback failed to restore", str(cm.exception))
        staging_trash = self.instance_dir / ".staging_trash"
        self.assertTrue(staging_trash.exists())
        staging_subdirs = list(staging_trash.iterdir())
        self.assertEqual(len(staging_subdirs), 1)
        staged_folder = staging_subdirs[0]

        # Verify manifest exists and is marked recovery_failed
        manifest_file = staged_folder / "recovery_manifest.json"
        self.assertTrue(manifest_file.exists())
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(manifest_data["phase"], "recovery_failed")
        self.assertIn("failed_restores", manifest_data)

    # -------------------------------------------------------------------------
    # 8. Cleanup Failure After Successful DB Commit Does NOT Restore Files
    # -------------------------------------------------------------------------
    def test_cleanup_failure_after_db_commit_does_not_restore_files(self):
        aid = 304
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "task.json"
        task_file.write_text("data_to_delete", encoding="utf-8")

        artifacts = find_analysis_artifacts(self.instance_dir, self.user_id_1, aid)
        mock_row = {"Analysis_Id": aid, "User_Id": self.user_id_1, "Video_Id": 5}
        mock_conn = RealisticMockConnection(for_update_row=mock_row)

        # Patch shutil.rmtree to simulate post-commit staging folder cleanup failure
        with patch("shutil.rmtree", side_effect=OSError("Access denied during post-commit cleanup")):
            res = staged_delete_analysis(
                instance_dir=self.instance_dir,
                user_id=self.user_id_1,
                analysis_id=aid,
                artifacts=artifacts,
                db_conn=mock_conn,
            )

        self.assertTrue(res["success"])
        self.assertTrue(res["db_committed"])
        self.assertTrue(res["cleanup_failed"])
        self.assertFalse(task_file.exists())  # Must NOT be restored!

    # -------------------------------------------------------------------------
    # 9. Active, Queued and Stale Worker States
    # -------------------------------------------------------------------------
    def test_active_running_worker_state_refused(self):
        aid = 401
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        lock_file = task_dir / ".task.lock"
        active_lock = CrossProcessLock(lock_file, timeout=0)
        active_lock.acquire(timeout=0)
        try:
            is_active = analysis_worker.is_analysis_active(self.instance_dir, self.user_id_1, aid)
            self.assertTrue(is_active)
        finally:
            active_lock.release()

    def test_active_queued_worker_state_refused(self):
        """Even with no task lock, an alive worker keeps queued state active."""
        aid = 402
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "task.json"
        # Alive worker process
        task_file.write_text(
            json.dumps({"status": "queued", "process": analysis_worker.PROCESS, "pid": os.getpid()}),
            encoding="utf-8",
        )

        with patch("services.analysis_worker.is_worker_alive", return_value=True):
            is_active = analysis_worker.is_analysis_active(self.instance_dir, self.user_id_1, aid)
            self.assertTrue(is_active)

    def test_stale_queued_or_running_worker_state_permitted(self):
        """When worker process is dead, a queued or running task is recognized as stale."""
        aid = 403
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "task.json"
        task_file.write_text(
            json.dumps({"status": "running", "process": "dead_token_999", "pid": 999999}),
            encoding="utf-8",
        )

        with patch("services.analysis_worker.is_worker_alive", return_value=False):
            is_active = analysis_worker.is_analysis_active(self.instance_dir, self.user_id_1, aid)
            self.assertFalse(is_active)

    # -------------------------------------------------------------------------
    # 10. Shared-Cache Lock Contention Aborts Without Resetting Analysis
    # -------------------------------------------------------------------------
    def test_shared_cache_lock_contention_aborts_without_modifying_analysis(self):
        aid = 501
        task_dir = self.user_runs_1 / str(aid)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "task.json"
        task_file.write_text(json.dumps({"status": "completed"}), encoding="utf-8")

        mock_preview = {
            "Analysis_Id": aid,
            "User_Id": self.user_id_1,
            "Video_Id": 5,
            "Analysis_Date": "2026-10-14 10:00:00",
            "Aspect_Vise_Report": json.dumps({"status": "completed"}),
            "YouTube_url": "https://www.youtube.com/watch?v=abc101",
            "Title": "Test Movie",
            "Name": "Alice",
        }
        mock_conn = RealisticMockConnection(preview_rows=[mock_preview])
        args = SimpleNamespace(analysis_id=aid, clear_aspect_cache=True)

        cache_lock_path = PROJECT_ROOT / "data" / "cache" / ".aspect_sentiment.lock"
        other_cache_lock = CrossProcessLock(cache_lock_path, timeout=0)
        other_cache_lock.acquire(timeout=0)
        try:
            with patch("manage_analysis.get_instance_dir", return_value=self.instance_dir), \
                 patch("manage_analysis.db._get_connection", return_value=mock_conn):
                exit_code = run_reset(args, confirm_fn=lambda: "RESET")
            self.assertEqual(exit_code, 1)
            self.assertTrue(task_file.exists())
            self.assertFalse(mock_conn.mutation_executed)
        finally:
            other_cache_lock.release()

    # -------------------------------------------------------------------------
    # 11. Shared-Cache Partial Cleanup Reported Accurately
    # -------------------------------------------------------------------------
    def test_shared_cache_partial_cleanup_reported(self):
        aid = 502
        mock_preview = {
            "Analysis_Id": aid,
            "User_Id": self.user_id_1,
            "Video_Id": 5,
            "Analysis_Date": "2026-10-14 10:00:00",
            "Aspect_Vise_Report": json.dumps({"status": "completed"}),
            "YouTube_url": "https://www.youtube.com/watch?v=abc101",
            "Title": "Test Movie",
            "Name": "Alice",
        }
        mock_conn = RealisticMockConnection(preview_rows=[mock_preview], for_update_row=mock_preview)
        (self.cache_dir/"cached.json").write_text("{}",encoding="utf-8")
        args = SimpleNamespace(analysis_id=aid, clear_aspect_cache=True)

        with patch("manage_analysis.get_instance_dir", return_value=self.instance_dir), \
             patch("manage_analysis.db._get_connection", return_value=mock_conn), \
             patch("manage_analysis.verify_cache_dir_safety", return_value=self.cache_dir), \
             patch("pathlib.Path.unlink", side_effect=OSError("Locked cache file")):
            exit_code = run_reset(args, confirm_fn=lambda: "RESET")

        self.assertEqual(exit_code, 2)
        self.assertTrue(mock_conn.committed)

    # -------------------------------------------------------------------------
    # 12. Unsafe Paths and Symlinks Rejected in Hierarchy
    # -------------------------------------------------------------------------
    def test_unsafe_paths_and_symlinks_rejected(self):
        allowed = [(self.instance_dir / "analysis_runs").resolve()]

        outside = PROJECT_ROOT / "models" / "cineinsight" / "model.pth"
        with self.assertRaises(ValueError):
            verify_safe_path(outside, allowed)

        self.assertFalse(is_path_safe(outside, allowed))

        # Root directory itself rejected
        with self.assertRaises(ValueError):
            verify_safe_path(self.instance_dir / "analysis_runs", allowed)

        # Hierarchy symlink check
        symlink_dir = self.instance_dir / "analysis_runs" / "symlink_dir"
        target_dir = self.temp_dir.name
        try:
            os.symlink(target_dir, str(symlink_dir), target_is_directory=True)
            nested_file = symlink_dir / "nested.txt"
            self.assertTrue(has_symlink_or_junction_in_hierarchy(nested_file))
            with self.assertRaises(ValueError):
                verify_safe_path(nested_file, allowed)
        except OSError:
            pass

    # -------------------------------------------------------------------------
    # 13. Missing Files Handled Gracefully
    # -------------------------------------------------------------------------
    def test_missing_files_handled_gracefully(self):
        aid = 601
        artifacts = find_analysis_artifacts(self.instance_dir, self.user_id_1, aid)
        self.assertIsNone(artifacts["task_dir"])
        self.assertEqual(artifacts["all_files"], [])

        mock_row = {"Analysis_Id": aid, "User_Id": self.user_id_1, "Video_Id": 5}
        mock_conn = RealisticMockConnection(for_update_row=mock_row)

        res = staged_delete_analysis(
            instance_dir=self.instance_dir,
            user_id=self.user_id_1,
            analysis_id=aid,
            artifacts=artifacts,
            db_conn=mock_conn,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["files_deleted"], 0)
        self.assertTrue(mock_conn.committed)

    # -------------------------------------------------------------------------
    # 14. Stale Browser ID Recovery Without Automatic Resubmission
    # -------------------------------------------------------------------------
    def test_status_endpoint_returns_404_for_reset_analysis(self):
        state = analysis_worker.load_state(self.instance_dir, self.user_id_1, 999)
        self.assertIsNone(state)

    def test_browser_template_contains_404_handling_and_no_auto_restart(self):
        template_file = PROJECT_ROOT / "templates" / "analysis.html"
        self.assertTrue(template_file.is_file())
        content = template_file.read_text(encoding="utf-8")

        self.assertIn("response.status===404", content)
        self.assertIn("sessionStorage.removeItem(key)", content)
        self.assertIn("aid=null", content)
        self.assertIn("new-run", content)
        branch_404 = content[content.index("response.status===404"):content.index("return;")]
        self.assertNotIn("start()", branch_404)
        self.assertNotIn("location.reload()", branch_404)


if __name__ == "__main__":
    unittest.main()
