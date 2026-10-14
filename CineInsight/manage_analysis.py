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

from services import db_service as db
from services.analysis_worker import (
    owner_dir,
    get_analysis_lock,
    is_analysis_active,
    is_worker_alive,
)
from src.extractors.cache_lock import CrossProcessLock
from manage_cache import (
    verify_cache_dir_safety,
    get_aspect_sentiment_cache_dir,
    is_symlink_or_junction,
)


def get_instance_dir(root: Path | None = None) -> Path:
    """Return resolved instance directory."""
    r = (root or PROJECT_ROOT).resolve()
    return (r / "instance").resolve()


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
        # Phase 1: Quarantine files by moving to staging
        for f in set(artifacts.get("all_files", [])):
            if f.name == ".task.lock":
                continue
            safe_source = verify_safe_path(f, allowed_roots)
            if safe_source.is_file():
                rel_name = safe_source.relative_to(instance_dir)
                dest = staging_dir / rel_name
                verify_safe_path(dest, [staging_base])
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(safe_source), str(dest))
                staged_items.append((safe_source, dest))
                manifest["items"].append({
                    "original": str(safe_source),
                    "staged": str(dest),
                })

        manifest["phase"] = "staged"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

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

            db_conn.commit()
            db_committed = True
        except Exception as db_exc:
            db_conn.rollback()
            raise db_exc
        finally:
            cursor.close()

        # Update manifest to db_committed
        manifest["phase"] = "db_committed"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

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
                    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
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
        pass

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
        return 0

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

    args = parser.parse_args()
    if args.command == "list":
        run_list(args)
    elif args.command == "reset":
        code = run_reset(args)
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
