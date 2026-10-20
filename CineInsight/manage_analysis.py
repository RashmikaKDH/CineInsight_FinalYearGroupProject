#!/usr/bin/env python3
"""CineInsight Analysis Management Utility.

Terminal-only command to inspect, list, and reset individual analyses.
Allows resetting an analysis so the same video can be analyzed again from scratch.

Safety guarantees:
- Requires typing RESET to confirm deletion (no --yes flag bypass).
- Staged recovery deletion: database transaction with filesystem staging/rollback.
- Writes recovery manifest and retains quarantine if file restoration is incomplete.
- Distinguishes pre-commit DB failures from post-commit staging cleanup issues.
- Protects user accounts, other analyses, checkpoint/background models and pretrained caches.
- Preserves youtube_video metadata records by default.
- Strict symlink/junction rejection covering entire path hierarchy.
- Cross-process worker coordination: distinguishes live worker processes from stale states.
- Shared cache lock coordinated before mutation when --clear-aspect-cache is used.

Usage:
    python manage_analysis.py list
    python manage_analysis.py list --user-id 2
    python manage_analysis.py reset --analysis-id 123
    python manage_analysis.py reset --analysis-id 123 --clear-aspect-cache
"""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from dotenv import load_dotenv

from services import db_service as db
from services.analysis_worker import (
    owner_dir,
    get_analysis_lock,
    is_analysis_active,
    is_worker_alive,
    find_inference_csv,
    write_json,
)
from services.report_import import parse_report
from src import local_inference as inference
from src.extractors.cache_lock import CrossProcessLock
from manage_cache import (
    verify_cache_dir_safety,
    get_aspect_sentiment_cache_dir,
    is_symlink_or_junction,
)


def get_instance_dir(root: Path | None = None) -> Path:
    """Return resolved instance directory."""
    if root is not None:
        r = Path(root).resolve()
        if r.name == "instance" or (r / "analysis_runs").is_dir():
            return r
        return (r / "instance").resolve()
    return (PROJECT_ROOT / "instance").resolve()


def has_symlink_or_junction_in_hierarchy(path: Path) -> bool:
    """Check if the path or any of its parent directories is a symlink or directory junction."""
    try:
        cur = path
        while True:
            if is_symlink_or_junction(cur):
                return True
            try:
                cur_resolved = cur.resolve()
                if is_symlink_or_junction(cur_resolved):
                    return True
            except OSError:
                return True
            if cur.parent == cur:
                break
            cur = cur.parent
    except OSError:
        return True
    return False


def verify_safe_path(path: Path, allowed_roots: list[Path]) -> Path:
    """Verify that path is safe and inside allowed roots, rejecting symlinks and junctions anywhere in its hierarchy."""
    if has_symlink_or_junction_in_hierarchy(path):
        raise ValueError(f"Unsafe symlink or directory junction rejected in hierarchy: '{path}'")

    try:
        resolved = path.resolve()
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot resolve path '{path}': {exc}")

    if has_symlink_or_junction_in_hierarchy(resolved):
        raise ValueError(f"Unsafe symlink or directory junction rejected in resolved hierarchy: '{resolved}'")

    inside_allowed = False
    for root in allowed_roots:
        resolved_root = root.resolve()
        if resolved == resolved_root:
            raise ValueError(f"Path cannot be the allowed root directory itself: '{resolved}'")
        if resolved.is_relative_to(resolved_root):
            inside_allowed = True
            break

    if not inside_allowed:
        raise ValueError(f"Path traversal violation: '{resolved}' is outside allowed storage roots")

    parts_lower = [p.lower() for p in resolved.parts]
    if "models" in parts_lower and "cineinsight" in parts_lower:
        raise ValueError(f"Critical path protection: models/cineinsight cannot be targeted: '{resolved}'")
    if "venv" in parts_lower or ".git" in parts_lower:
        raise ValueError(f"Critical path protection: system directory cannot be targeted: '{resolved}'")

    return resolved


def is_path_safe(path: Path, allowed_roots: list[Path]) -> bool:
    """Boolean wrapper for path verification without raising."""
    try:
        verify_safe_path(path, allowed_roots)
        return True
    except (ValueError, OSError):
        return False


def list_analyses(user_id: int | None = None, limit: int = 50, db_conn=None) -> list[dict[str, Any]]:
    """List analyses from database with status and video metadata. Never exposes credentials."""
    conn = db_conn or db._get_connection()
    close_conn = db_conn is None
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT 
                a.Analysis_Id,
                a.User_Id,
                u.Name AS User_Name,
                u.Email AS User_Email,
                v.Video_Id,
                v.Title AS Video_Title,
                v.YouTube_url,
                a.Analysis_Date,
                a.Overall_Sentiment_Score,
                a.Sarcasm_Flag,
                a.Aspect_Vise_Report
            FROM analysis a
            LEFT JOIN youtube_video v ON a.Video_Id = v.Video_Id
            LEFT JOIN user u ON a.User_Id = u.User_Id
        """
        params: list[Any] = []
        if user_id is not None:
            query += " WHERE a.User_Id = %s"
            params.append(user_id)

        query += " ORDER BY a.Analysis_Id DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        results = []
        for r in rows:
            status = "unknown"
            if r["Aspect_Vise_Report"]:
                try:
                    rep_data = json.loads(r["Aspect_Vise_Report"])
                    status = rep_data.get("status", "unknown")
                except Exception:
                    status = "unparsed"

            results.append({
                "analysis_id": r["Analysis_Id"],
                "user_id": r["User_Id"],
                "user_name": r["User_Name"] or "Unknown",
                "video_url": r["YouTube_url"] or "Unknown",
                "video_title": r["Video_Title"] or "Unknown",
                "date": str(r["Analysis_Date"]),
                "status": status,
            })
        return results
    finally:
        cursor.close()
        if close_conn:
            conn.close()


def find_analysis_artifacts(
    instance_dir: Path,
    user_id: int,
    analysis_id: int,
) -> dict[str, Any]:
    """Identify and verify all filesystem artifacts belonging to this analysis.
    
    Rejects symlinks or unsafe paths anywhere in the hierarchy.
    """
    allowed_roots = [
        (instance_dir / "analysis_runs").resolve(),
        (instance_dir / "imported_reports").resolve(),
    ]

    owner_hash = hashlib.sha256(str(user_id).encode()).hexdigest()
    user_runs_dir = instance_dir / "analysis_runs" / owner_hash
    task_dir = user_runs_dir / str(analysis_id)

    artifacts: dict[str, Any] = {
        "task_dir": None,
        "request_markers": [],
        "report_files": [],
        "all_files": [],
        "all_dirs": [],
    }

    # 1. Task directory
    if task_dir.exists():
        safe_task_dir = verify_safe_path(task_dir, allowed_roots)
        artifacts["task_dir"] = safe_task_dir
        artifacts["all_dirs"].append(safe_task_dir)
        for item in safe_task_dir.rglob("*"):
            if item.name == ".task.lock":
                continue
            safe_item = verify_safe_path(item, allowed_roots)
            if safe_item.is_file():
                artifacts["all_files"].append(safe_item)
            elif safe_item.is_dir():
                artifacts["all_dirs"].append(safe_item)

    # 2. Request markers matching this analysis_id
    requests_dir = user_runs_dir / "requests"
    if requests_dir.is_dir():
        for marker in requests_dir.glob("*.json"):
            safe_marker = verify_safe_path(marker, allowed_roots)
            try:
                data = json.loads(safe_marker.read_text(encoding="utf-8"))
                if data.get("analysis_id") == analysis_id:
                    artifacts["request_markers"].append(safe_marker)
                    artifacts["all_files"].append(safe_marker)
            except Exception:
                pass

    # 3. Report files in imported_reports matching this analysis_id
    user_reports_dir = instance_dir / "imported_reports" / owner_hash
    if user_reports_dir.is_dir():
        for report_json in user_reports_dir.glob("*.json"):
            safe_json = verify_safe_path(report_json, allowed_roots)
            try:
                data = json.loads(safe_json.read_text(encoding="utf-8"))
                if data.get("analysis_id") == analysis_id:
                    artifacts["report_files"].append(safe_json)
                    artifacts["all_files"].append(safe_json)
                    matching_csv = safe_json.with_suffix(".csv")
                    if matching_csv.exists():
                        safe_csv = verify_safe_path(matching_csv, allowed_roots)
                        artifacts["report_files"].append(safe_csv)
                        artifacts["all_files"].append(safe_csv)
            except Exception:
                pass

    return artifacts


def write_recovery_manifest(path, manifest):
    """Atomically persist recovery intent before touching source files."""
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def staged_delete_analysis(
    instance_dir: Path,
    user_id: int,
    analysis_id: int,
    artifacts: dict[str, Any],
    db_conn,
) -> dict[str, Any]:
    """Execute staged deletion with recovery manifest, atomic DB transaction, and rollback safety.

    Phases:
    1. Move files to an isolated quarantine staging directory and write recovery manifest.
    2. Execute database deletion in an atomic transaction:
       - SELECT ... FOR UPDATE to re-verify row and owner
       - DELETE FROM reasoning_report WHERE Analysis_Id = %s
       - DELETE FROM analysis WHERE Analysis_Id = %s AND User_Id = %s
       - Verify affected analysis row count is 1
       - Commit transaction
    3. Update manifest to 'db_committed'.
    4. Permanently remove the staging quarantine directory.
    5. If DB failure occurs before commit:
       - Roll back DB transaction.
       - Restore staged files back to original paths.
       - If any file fails to restore, retain quarantine and manifest, raising clear error.
    6. If cleanup fails after DB commit:
       - Do NOT restore files (DB is already committed).
       - Retain quarantine and report cleanup failure.
    """
    allowed_roots = [
        (instance_dir / "analysis_runs").resolve(),
        (instance_dir / "imported_reports").resolve(),
    ]
    staging_base = (instance_dir / ".staging_trash").resolve()
    staging_base.mkdir(parents=True, exist_ok=True)
    verify_safe_path(staging_base, [instance_dir.resolve()])

    staging_token = secrets.token_hex(8)
    staging_dir = staging_base / f"reset_{analysis_id}_{staging_token}_{os.getpid()}"
    staging_dir.mkdir(parents=True, exist_ok=False)

    manifest_path = staging_dir / "recovery_manifest.json"
    manifest: dict[str, Any] = {
        "analysis_id": analysis_id,
        "user_id": user_id,
        "pid": os.getpid(),
        "created_at": time.time(),
        "phase": "staging",
        "items": [],
    }

    staged_items: list[tuple[Path, Path]] = []
    db_committed = False

    try:
        # Record the complete plan BEFORE the first move.
        plan = []
        for index, f in enumerate(sorted(set(artifacts.get("all_files", [])))):
            if f.name == ".task.lock":
                continue
            source = verify_safe_path(f, allowed_roots)
            if source.is_file():
                dest = staging_dir / "files" / f"{index:04d}_{source.name}"
                verify_safe_path(dest, [staging_base])
                plan.append((source, dest))
                manifest["items"].append({"original":str(source),"staged":str(dest),"state":"planned"})
        write_recovery_manifest(manifest_path, manifest)
        for index, (source, dest) in enumerate(plan):
            verify_safe_path(source, allowed_roots)
            verify_safe_path(dest, [staging_base])
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Register first so a failed/partial move is recoverable too.
            staged_items.append((source, dest))
            shutil.move(str(source), str(dest))
            manifest["items"][index]["state"] = "moved"
            write_recovery_manifest(manifest_path, manifest)
        manifest["phase"] = "staged"
        write_recovery_manifest(manifest_path, manifest)

        # Clean empty subdirectories in task_dir (bottom-up)
        task_dir = artifacts.get("task_dir")
        if task_dir and task_dir.exists():
            for item in sorted(task_dir.rglob("*"), reverse=True):
                if item.is_dir() and not is_symlink_or_junction(item):
                    try:
                        item.rmdir()
                    except OSError:
                        pass

        # Phase 2: Database transaction
        db_conn.start_transaction()
        cursor = db_conn.cursor(dictionary=True)
        try:
            # Re-read and lock row with SELECT ... FOR UPDATE
            cursor.execute(
                "SELECT Analysis_Id, User_Id, Video_Id FROM analysis WHERE Analysis_Id = %s FOR UPDATE",
                (analysis_id,),
            )
            locked_row = cursor.fetchone()
            if not locked_row:
                raise ValueError(f"Analysis {analysis_id} was removed before reset could proceed.")
            if locked_row["User_Id"] != user_id:
                raise ValueError(
                    f"Analysis {analysis_id} ownership changed (expected User {user_id}, found User {locked_row['User_Id']})."
                )

            # Owner-scoped deletion
            cursor.execute("DELETE FROM reasoning_report WHERE Analysis_Id = %s", (analysis_id,))
            reasoning_deleted = cursor.rowcount

            cursor.execute(
                "DELETE FROM analysis WHERE Analysis_Id = %s AND User_Id = %s",
                (analysis_id, user_id),
            )
            analysis_deleted = cursor.rowcount
            if analysis_deleted != 1:
                raise RuntimeError(f"Expected to delete exactly 1 analysis record, deleted {analysis_deleted}.")

            manifest["phase"] = "commit_pending"
            write_recovery_manifest(manifest_path, manifest)
            db_conn.commit()
            db_committed = True
        except Exception as db_exc:
            db_conn.rollback()
            raise db_exc
        finally:
            cursor.close()

        # Update manifest to db_committed
        manifest["phase"] = "db_committed"
        write_recovery_manifest(manifest_path, manifest)

        # Phase 3: Post-commit cleanup
        cleanup_failed = False
        try:
            shutil.rmtree(str(staging_dir))
        except Exception:
            cleanup_failed = True

        return {
            "success": True,
            "db_committed": True,
            "cleanup_failed": cleanup_failed,
            "staging_dir": staging_dir if cleanup_failed else None,
            "reasoning_deleted": reasoning_deleted,
            "analysis_deleted": analysis_deleted,
            "files_deleted": len(staged_items),
        }

    except Exception as exc:
        if not db_committed:
            # Rollback: restore staged files back to their original paths
            manifest["phase"] = "recovery_failed"
            failed_restores = []
            for original, staged in staged_items:
                try:
                    if staged.exists():
                        verify_safe_path(staged, [staging_base])
                        verify_safe_path(original, allowed_roots)
                        if original.exists():
                            raise RuntimeError("Restore refused: original path is already occupied.")
                        original.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(staged), str(original))
                except Exception as rest_exc:
                    failed_restores.append({
                        "original": str(original),
                        "staged": str(staged),
                        "error": str(rest_exc),
                    })

            if failed_restores:
                manifest["failed_restores"] = failed_restores
                try:
                    write_recovery_manifest(manifest_path, manifest)
                except Exception:
                    pass
                raise RuntimeError(
                    f"CRITICAL: Rollback failed to restore {len(failed_restores)} files. "
                    f"Quarantine retained at: {staging_dir}. Cause: {exc}"
                ) from exc
            else:
                # All staged files successfully restored
                try:
                    shutil.rmtree(str(staging_dir), ignore_errors=True)
                except Exception:
                    pass
        raise exc


def clear_shared_aspect_cache(project_root: Path | None = None, timeout: float = 10.0) -> dict[str, Any]:
    """Safely clear the shared aspect/sentiment cache using CrossProcessLock."""
    root = (project_root or PROJECT_ROOT).resolve()
    cache_dir = get_aspect_sentiment_cache_dir(root)
    resolved_cache = verify_cache_dir_safety(cache_dir, root)

    lock_path = root / "data" / "cache" / ".aspect_sentiment.lock"
    lock = CrossProcessLock(lock_path, timeout=timeout)

    try:
        lock.acquire(timeout=timeout)
    except TimeoutError:
        raise TimeoutError("Could not acquire cache lock: an extraction task is actively using the cache.")

    deleted_count = 0
    total_bytes = 0
    try:
        if resolved_cache.exists():
            for p in resolved_cache.iterdir():
                if p.is_file() and not is_symlink_or_junction(p):
                    if p.name.endswith(".json") or p.name.endswith(".tmp"):
                        size = p.stat().st_size
                        p.unlink()
                        deleted_count += 1
                        total_bytes += size
    finally:
        lock.release()

    return {"deleted_files": deleted_count, "deleted_bytes": total_bytes}


def run_list(args):
    """Handle the 'list' command."""
    try:
        analyses = list_analyses(user_id=args.user_id, limit=args.limit)
    except Exception as e:
        print(f"\n[ERROR] Database connection failed: {e}", file=sys.stderr)
        print("Ensure MySQL is running and cineinsight_db is accessible.\n", file=sys.stderr)
        sys.exit(1)

    if not analyses:
        print("\nNo analyses found.\n")
        return

    print("\n" + "=" * 90)
    print("                              CINEINSIGHT ANALYSES LIST                              ")
    print("=" * 90)
    print(f"{'ID':<6} | {'OWNER':<18} | {'STATUS':<14} | {'DATE':<20} | {'VIDEO URL'}")
    print("-" * 90)
    for a in analyses:
        owner_str = f"User {a['user_id']} ({a['user_name'][:10]})"
        print(f"{a['analysis_id']:<6} | {owner_str:<18} | {a['status']:<14} | {a['date'][:19]:<20} | {a['video_url']}")
    print("-" * 90)
    print(f"Total analyses displayed: {len(analyses)}\n")


def run_reset(args, confirm_fn: Callable[[], str] | None = None) -> int:
    """Handle the 'reset' command. Returns 0 on success, non-zero on error/cancellation."""
    aid = args.analysis_id
    instance_dir = get_instance_dir()

    # 1. Connect to DB and fetch analysis details for preview
    try:
        conn = db._get_connection()
    except Exception as e:
        print(f"\n[ERROR] Database connection failed: {e}", file=sys.stderr)
        print("Cannot reset analysis without an active database connection.\n", file=sys.stderr)
        return 1

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT a.Analysis_Id, a.User_Id, a.Video_Id, a.Analysis_Date, a.Aspect_Vise_Report,
                      v.YouTube_url, v.Title, u.Name
               FROM analysis a
               LEFT JOIN youtube_video v ON a.Video_Id = v.Video_Id
               LEFT JOIN user u ON a.User_Id = u.User_Id
               WHERE a.Analysis_Id = %s""",
            (aid,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()

    # Explicitly finish preview read transaction
    try:
        conn.commit()
    except Exception:
        print("[ERROR] Could not finish the preview transaction. Reset aborted; no files were moved.", file=sys.stderr)
        try:
            conn.rollback()
        finally:
            conn.close()
        return 1

    if not row:
        conn.close()
        print(f"\n[ERROR] Analysis ID {aid} was not found in the database.\n", file=sys.stderr)
        return 1

    user_id = row["User_Id"]
    url = row["YouTube_url"]
    date_str = str(row["Analysis_Date"])
    user_name = row["Name"] or "Unknown"

    status_str = "unknown"
    if row["Aspect_Vise_Report"]:
        try:
            status_str = json.loads(row["Aspect_Vise_Report"]).get("status", "unknown")
        except Exception:
            pass

    # 2. Worker coordination & lock check
    if is_analysis_active(instance_dir, user_id, aid, check_lock=True):
        conn.close()
        print(f"\n[REFUSED] Analysis {aid} is currently queued or running in a background worker.", file=sys.stderr)
        print("Wait for the analysis to finish or restart the server before resetting.\n", file=sys.stderr)
        return 1

    # 3. Optional shared cache lock check (BEFORE mutation)
    cache_lock = None
    resolved_cache = None
    if args.clear_aspect_cache:
        try:
            cache_dir = get_aspect_sentiment_cache_dir(PROJECT_ROOT)
            resolved_cache = verify_cache_dir_safety(cache_dir, PROJECT_ROOT)
            cache_lock_path = PROJECT_ROOT / "data" / "cache" / ".aspect_sentiment.lock"
            cache_lock = CrossProcessLock(cache_lock_path, timeout=5.0)
            cache_lock.acquire(timeout=5.0)
        except (TimeoutError, Exception) as cache_err:
            conn.close()
            print(f"\n[REFUSED] Could not acquire shared aspect cache lock ({cache_err}).", file=sys.stderr)
            print("Aborting without resetting the analysis or modifying any records.\n", file=sys.stderr)
            return 1

    # 4. Acquire cross-process file lock for this analysis
    analysis_lock = get_analysis_lock(instance_dir, user_id, aid, timeout=0)
    try:
        analysis_lock.acquire(timeout=0)
    except (TimeoutError, OSError):
        if cache_lock:
            cache_lock.release()
        conn.close()
        print(f"\n[REFUSED] Analysis {aid} is currently locked by another worker process.\n", file=sys.stderr)
        return 1

    result = None
    artifacts = None
    try:
        # Recheck status after acquiring lock
        if is_analysis_active(instance_dir, user_id, aid, check_lock=False):
            print(f"\n[REFUSED] Analysis {aid} became active during lock acquisition.\n", file=sys.stderr)
            return 1

        # 5. Find files associated with this analysis
        try:
            artifacts = find_analysis_artifacts(instance_dir, user_id, aid)
        except ValueError as val_err:
            print(f"\n[ERROR] Path safety violation: {val_err}\n", file=sys.stderr)
            return 1

        # 6. Preview what will be removed
        print("\n" + "=" * 76)
        print("                        ANALYSIS RESET PREVIEW                        ")
        print("=" * 76)
        print(f"Analysis ID:    {aid}")
        print(f"Owner:          User {user_id} ({user_name})")
        print(f"Video URL:      {url}")
        print(f"Current Status: {status_str}")
        print(f"Recorded Date:  {date_str}")
        print("\nDatabase records to be removed:")
        print(f"  [-] reasoning_report record for Analysis_Id {aid}")
        print(f"  [-] analysis record for Analysis_Id {aid}")
        print("  [*] youtube_video metadata record will be PRESERVED.")

        print("\nFilesystem artifacts to be removed:")
        task_dir = artifacts.get("task_dir")
        if task_dir:
            print(f"  [-] Task Directory: {task_dir}")
            print("      (Includes task.json, prepared media & CSV, feature vectors, SHAP/reasoning)")
        else:
            print("  [ ] Task Directory: <none found>")

        if artifacts["request_markers"]:
            print(f"  [-] Request identifier markers ({len(artifacts['request_markers'])} file(s)):")
            for m in artifacts["request_markers"]:
                print(f"      * {m}")
        else:
            print("  [ ] Request identifier markers: <none found>")

        if artifacts["report_files"]:
            print(f"  [-] Saved report CSV & JSON files ({len(artifacts['report_files'])} file(s)):")
            for r_file in artifacts["report_files"]:
                print(f"      * {r_file}")
        else:
            print("  [ ] Saved report files: <none found>")

        if args.clear_aspect_cache:
            print("\nShared Aspect/Sentiment Cache:")
            print("  [!] WARNING: --clear-aspect-cache is specified.")
            print("      This will delete all shared cached classifications in data/cache/aspect_sentiment/.")
            print("      This affects future analyses of other videos.")

        print("=" * 76)

        # 7. Confirmation (Explicit RESET requirement)
        if confirm_fn is not None:
            confirm = str(confirm_fn()).strip()
        else:
            try:
                confirm = input("\nType 'RESET' to confirm deletion: ").strip()
            except (EOFError, KeyboardInterrupt):
                confirm = ""

        if confirm != "RESET":
            print("\n[CANCELLED] Reset cancelled. No files or database records were modified.\n")
            return 0

        # 8. Execute staged deletion
        print("\n[*] Resetting analysis records and files...")
        try:
            result = staged_delete_analysis(
                instance_dir=instance_dir,
                user_id=user_id,
                analysis_id=aid,
                artifacts=artifacts,
                db_conn=conn,
            )
        except Exception as stage_err:
            print(f"\n[ERROR] Reset operation failed: {stage_err}\n", file=sys.stderr)
            return 2

        # 9. Clear shared cache if requested (we already hold cache_lock!)
        cache_cleanup_failed = False
        cache_result = None
        if args.clear_aspect_cache and resolved_cache:
            print("[*] Clearing shared aspect/sentiment cache...")
            try:
                deleted_count = 0
                total_bytes = 0
                if resolved_cache.exists():
                    for p in resolved_cache.iterdir():
                        if p.is_file() and not is_symlink_or_junction(p):
                            if p.name.endswith(".json") or p.name.endswith(".tmp"):
                                size = p.stat().st_size
                                p.unlink()
                                deleted_count += 1
                                total_bytes += size
                cache_result = {"deleted_files": deleted_count, "deleted_bytes": total_bytes}
            except Exception as cache_clean_err:
                cache_cleanup_failed = True
                print(f"\n[WARNING] Analysis reset completed; shared cache clearing incomplete: {cache_clean_err}", file=sys.stderr)

        print("\n" + "=" * 76)
        print("                         RESET COMPLETE                              ")
        print("=" * 76)
        print(f"Analysis ID {aid} was successfully reset.")
        print(f"  - Database records removed: {result['analysis_deleted']} analysis, {result['reasoning_deleted']} reasoning")
        print(f"  - Files removed:            {result['files_deleted']}")
        if result.get("cleanup_failed"):
            print(f"  - [WARNING] Database records deleted, but staging cleanup failed.")
            print(f"    Quarantine retained at: {result.get('staging_dir')}")
        if cache_result and not cache_cleanup_failed:
            print(f"  - Shared cache files purged: {cache_result['deleted_files']} ({cache_result['deleted_bytes']} bytes)")
        elif cache_cleanup_failed:
            print(f"  - [WARNING] Analysis reset completed; shared cache clearing incomplete.")

        print("\n[Browser Session Note]")
        print("If you had this video open on the web UI, refresh or return to the Analyze page.")
        print("The browser will detect the reset analysis and provide an action to start a fresh analysis.")
        print("=" * 76 + "\n")
        return 2 if result.get("cleanup_failed") or cache_cleanup_failed else 0

    finally:
        if cache_lock:
            try:
                cache_lock.release()
            except Exception:
                pass
        analysis_lock.release()
        if result and result.get("success") and artifacts:
            task_dir = artifacts.get("task_dir")
            if task_dir and task_dir.exists():
                lock_f = task_dir / ".task.lock"
                if lock_f.exists():
                    try:
                        lock_f.unlink()
                    except OSError:
                        pass
                try:
                    task_dir.rmdir()
                except OSError:
                    pass
        conn.close()


def find_shap_results_csv(task_dir: Path) -> Path | None:
    """Find existing cineinsight_final_results_with_shap.csv in compact or legacy paths."""
    task_dir = Path(task_dir)
    # 1. Compact run directory
    compact = task_dir / "run" / "cineinsight_final_results_with_shap.csv"
    if compact.is_file():
        return compact
    # 2. Legacy inference subdirectories
    legacy_runs = sorted(
        (task_dir / "inference").glob("inference_*"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for run in legacy_runs:
        c = run / "cineinsight_final_results_with_shap.csv"
        if c.is_file():
            return c
    # 3. Flat inference directory
    direct = task_dir / "inference" / "cineinsight_final_results_with_shap.csv"
    if direct.is_file():
        return direct
    return None


def validate_shap_results(df: pd.DataFrame) -> None:
    """Validate that saved predictions and SHAP results are complete, intact, and valid for Gemini reasoning."""
    if df.empty:
        raise ValueError("Saved SHAP results CSV is empty.")

    required = {
        "segment_id", "start", "end", "text", "aspects", "primary_aspect",
        "sentiment_label", "aspect_sentiments", "sentiment_status",
        "sarcasm_prediction", "sarcastic_probability", "shap_status",
        "text_shap_value", "audio_shap_value", "video_shap_value",
        "shap_background", "dominant_modality", "dominant_direction"
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Saved SHAP results CSV is missing required columns: {missing}")

    if df["segment_id"].isna().any() or df["segment_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Saved SHAP results contain missing or empty segment IDs.")
    if df["segment_id"].duplicated().any():
        raise ValueError("Saved SHAP results contain duplicate segment IDs.")

    # Validate predictions
    if not df["sarcasm_prediction"].isin(["Normal", "Sarcastic"]).all():
        raise ValueError("Saved SHAP results contain invalid or missing sarcasm predictions.")

    # Validate probabilities
    probs = pd.to_numeric(df["sarcastic_probability"], errors="coerce")
    if probs.isna().any() or ((probs < 0) | (probs > 1)).any():
        raise ValueError("Saved SHAP results contain non-numeric or out-of-range sarcastic probabilities.")

    # Check sarcastic rows have completed SHAP
    sarcastic_mask = df["sarcasm_prediction"] == "Sarcastic"
    for col in ("text_shap_value", "audio_shap_value", "video_shap_value"):
        vals = pd.to_numeric(df.loc[sarcastic_mask, col], errors="coerce")
        if vals.isna().any():
            raise ValueError(f"Sarcastic segments have missing or non-numeric SHAP values in {col}.")

    # Validate aspect_sentiments JSON
    for _, row in df.iterrows():
        try:
            mapping = json.loads(str(row["aspect_sentiments"]))
            if not isinstance(mapping, dict):
                raise ValueError("aspect_sentiments must be a JSON dictionary.")
        except Exception as exc:
            raise ValueError(f"Segment {row['segment_id']} has invalid aspect_sentiments JSON: {exc}")


def run_recover(args, instance_dir: Path | None = None) -> int:
    """Safely recover a failed or interrupted analysis from its saved predictions and SHAP output.

    Guarantees:
    - Cross-process locking prevents concurrent reset or worker collisions.
    - Validates existing SHAP results without re-downloading media or rerunning models/SHAP.
    - Checks SHAP_GEMINI_API_KEY and SHAP_GEMINI_MODEL from .env.
    - Preserves all original files.
    - Runs only missing Gemini reasoning using repair_reasoning.
    - Saves final report in compact run/ directory (immune to Windows MAX_PATH).
    - Updates analysis record and reasoning_report atomically without duplicate rows.
    - Populates imported_reports library so report is immediately viewable in the UI.
    """
    aid = args.analysis_id
    inst = get_instance_dir(instance_dir)

    conn = db._get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT a.Analysis_Id, a.User_Id, u.Name as User_Name, v.YouTube_url, a.Aspect_Vise_Report "
            "FROM analysis a "
            "LEFT JOIN youtube_video v ON a.Video_Id = v.Video_Id "
            "LEFT JOIN user u ON a.User_Id = u.User_Id "
            "WHERE a.Analysis_Id = %s",
            (aid,)
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not row:
        print(f"\n[ERROR] Analysis ID {aid} not found in database.\n", file=sys.stderr)
        return 1

    user_id = row["User_Id"]
    user_name = row["User_Name"] or "Unknown"
    url = row["YouTube_url"] or ""

    # Acquire cross-process analysis lock to prevent concurrent reset or worker execution
    analysis_lock = get_analysis_lock(inst, user_id, aid, timeout=0)
    if not analysis_lock.acquire(timeout=5.0):
        print(f"\n[REFUSED] Analysis {aid} is currently locked by another worker process.\n", file=sys.stderr)
        return 1

    try:
        # Check if worker is alive & actively processing
        if is_analysis_active(inst, user_id, aid, check_lock=False):
            print(f"\n[REFUSED] Analysis {aid} is actively being processed by a running worker.\n", file=sys.stderr)
            return 1

        owner_hash = hashlib.sha256(str(user_id).encode()).hexdigest()
        task_dir = inst / "analysis_runs" / owner_hash / str(aid)
        if not task_dir.is_dir():
            print(f"\n[ERROR] Task directory not found: {task_dir}\n", file=sys.stderr)
            return 1

        shap_csv = find_shap_results_csv(task_dir)
        if not shap_csv or not shap_csv.is_file():
            print(f"\n[ERROR] No saved predictions & SHAP CSV found for Analysis {aid}.\n", file=sys.stderr)
            return 1

        print("\n" + "=" * 76)
        print("                     CINEINSIGHT PIPELINE RECOVERY                    ")
        print("=" * 76)
        print(f"Analysis ID:    {aid}")
        print(f"Owner:          User {user_id} ({user_name})")
        print(f"Video URL:      {url}")
        print(f"SHAP Artifact:  {shap_csv}")
        print("=" * 76 + "\n")

        print("[1/5] Validating saved predictions and SHAP results...")
        try:
            df = pd.read_csv(shap_csv)
            validate_shap_results(df)
        except Exception as val_err:
            print(f"\n[ERROR] Artifact validation failed: {val_err}\n", file=sys.stderr)
            return 1

        normal_count = int((df["sarcasm_prediction"] == "Normal").sum())
        sarcastic_count = int((df["sarcasm_prediction"] == "Sarcastic").sum())
        shap_completed = int((df["shap_status"] == "completed").sum())
        print(f"      Validation successful: {len(df)} segments total.")
        print(f"      - Normal segments (SHAP skipped): {normal_count}")
        print(f"      - Sarcastic segments:              {sarcastic_count} ({shap_completed} SHAP completed)")
        print("      Earlier pipeline stages (media download, Whisper, feature vectors, SHAP) will NOT be rerun.")

        print("\n[2/5] Loading Gemini reasoning configuration...")
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        skip_gemini = getattr(args, "skip_gemini", False)
        if not skip_gemini:
            try:
                api_key, model_name = inference.reasoning_config(cli_model=getattr(args, "gemini_model", None), enabled=True)
                print(f"      Configuration verified. Model: {model_name}")
            except Exception as cfg_err:
                print(f"\n[ERROR] Gemini configuration check failed: {cfg_err}\n", file=sys.stderr)
                return 1
        else:
            api_key, model_name = "", "disabled"
            print("      Gemini reasoning disabled (--skip-gemini specified).")

        run_dir = task_dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        output_csv = run_dir / "cineinsight_final_explainability_report.csv"
        cache_path = run_dir / "gemini_explanations.json"

        # Preserve the SHAP CSV in the compact run folder if it's not already there
        compact_shap = run_dir / "cineinsight_final_results_with_shap.csv"
        if shap_csv.resolve() != compact_shap.resolve() and not compact_shap.exists():
            shutil.copy2(str(shap_csv), str(compact_shap))

        print(f"\n[3/5] Generating Gemini reasoning explanations...")
        if not skip_gemini:
            def make_client():
                from google import genai
                return genai.Client(
                    api_key=api_key,
                    http_options={"retry_options": {"attempts": 1}, "timeout": 60000}
                )

            try:
                report = inference.repair_reasoning(
                    frame=df,
                    model_name=model_name,
                    cache_path=cache_path,
                    output_path=output_csv,
                    make_client=make_client,
                    progress_fn=lambda msg: print(f"      {msg}")
                )
            except Exception as reason_err:
                print(f"\n[ERROR] Reasoning execution failed: {reason_err}\n", file=sys.stderr)
                return 1
        else:
            report = df.copy()
            report["ai_reasoning"] = "Gemini explanations skipped."
            report["reasoning_status"] = "disabled"
            report["reasoning_model"] = "none"
            report["reasoning_error_code"] = ""
            report["reasoning_error"] = ""
            inference.save_csv(report, output_csv)

        incomplete = (
            report.get("reasoning_status", pd.Series(dtype=str)).isin(["error", "waiting_after_error", "waiting_budget", "pending"]).any() or
            report.get("shap_status", pd.Series(dtype=str)).eq("error").any()
        )
        target_state = "partial" if incomplete else "completed"
        print(f"      Reasoning stage finished with status: {target_state}")

        print("\n[4/5] Saving final report and importing to user report library...")
        if not output_csv.is_file():
            print(f"\n[ERROR] Final CSV was not created: {output_csv}\n", file=sys.stderr)
            return 1

        raw = output_csv.read_bytes()
        summary = parse_report(raw)
        report_id = hashlib.sha256(str(aid).encode() + b"\0" + raw).hexdigest()
        reports_dir = inst / "imported_reports" / owner_hash
        reports_dir.mkdir(parents=True, exist_ok=True)
        summary.update(
            title=url,
            id=report_id,
            analysis_id=aid,
            video_url=url,
            analysis_date="",
            pipeline_status=target_state
        )
        (reports_dir / f"{report_id}.csv").write_bytes(raw)
        write_json(reports_dir / f"{report_id}.json", summary)
        print(f"      Report imported with ID: {report_id}")

        print("\n[5/5] Updating database records and task status...")
        try:
            db.save_final_analysis(user_id, aid, summary, report_id, target_state)
            db_saved = True
            print("      Database analysis and reasoning_report records updated successfully.")
        except Exception as db_err:
            print(f"\n[WARNING] Database update warning: {db_err}", file=sys.stderr)
            db_saved = False
            target_state = "partial"
            summary.update(pipeline_status="partial", database_save_warning=True)
            write_json(reports_dir / f"{report_id}.json", summary)

        # Update task.json
        task_json = task_dir / "task.json"
        if task_json.is_file():
            try:
                t_state = json.loads(task_json.read_text(encoding="utf-8"))
            except Exception:
                t_state = {"analysis_id": aid, "user_id": user_id, "url": url}
            t_state.update(
                status=target_state,
                stage="finished",
                message="Results ready." if target_state == "completed" else "Results available; some explanations or database saving did not complete.",
                db_saved=db_saved,
                result_url=f"/reports/{report_id}",
                download_url=f"/reports/{report_id}/download",
            )
            write_json(task_json, t_state)
            print("      Local task.json state set to finished.")

        # Status.json in run_dir
        status_path = run_dir / "status.json"
        status_path.write_text(json.dumps({"status": target_state, "final_csv": str(output_csv)}), encoding="utf-8")

        if target_state == "completed":
            print("\n" + "=" * 76)
            print("                        RECOVERY COMPLETE                             ")
            print("=" * 76)
            print(f"Analysis ID {aid} was successfully recovered!")
            print(f"Status:       {target_state.upper()}")
            print(f"Report URL:   /reports/{report_id}")
            print(f"Download URL: /reports/{report_id}/download")
            print(f"Final CSV:    {output_csv}")
            print("\nYou can now view the results directly in the CineInsight web UI.")
            print("=" * 76 + "\n")
            return 0
        else:
            print("\n" + "=" * 76)
            print("                        RECOVERY PARTIAL                              ")
            print("=" * 76)
            print(f"Analysis ID {aid} recovery saved partial results.")
            print(f"Status:       {target_state.upper()}")
            print(f"Report URL:   /reports/{report_id}")
            print(f"Download URL: /reports/{report_id}/download")
            print(f"Final CSV:    {output_csv}")
            print("\nPending segments remain. Run recovery again later to continue explanations.")
            print("=" * 76 + "\n")
            return 2
    finally:
        analysis_lock.release()


def main():
    parser = argparse.ArgumentParser(
        description="CineInsight Analysis Management & Reset Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: list
    list_parser = subparsers.add_parser("list", help="List recorded analyses")
    list_parser.add_argument("--user-id", type=int, default=None, help="Filter analyses by user ID")
    list_parser.add_argument("--limit", type=int, default=50, help="Maximum number of analyses to display (default 50)")

    # Subcommand: reset
    reset_parser = subparsers.add_parser("reset", help="Reset a selected analysis")
    reset_parser.add_argument("--analysis-id", type=int, required=True, help="Analysis ID to reset")
    reset_parser.add_argument(
        "--clear-aspect-cache",
        action="store_true",
        help="Also clear the shared aspect/sentiment cache (affects other videos)",
    )

    # Subcommand: recover
    recover_parser = subparsers.add_parser("recover", help="Recover a failed or interrupted analysis from saved SHAP output")
    recover_parser.add_argument("--analysis-id", type=int, required=True, help="Analysis ID to recover")
    recover_parser.add_argument("--gemini-model", default=None, help="Override SHAP_GEMINI_MODEL")
    recover_parser.add_argument("--skip-gemini", action="store_true", help="Complete recovery without calling Gemini (sets reasoning to disabled)")

    args = parser.parse_args()
    if args.command == "list":
        run_list(args)
    elif args.command == "reset":
        code = run_reset(args)
        if code != 0:
            sys.exit(code)
    elif args.command == "recover":
        code = run_recover(args)
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
