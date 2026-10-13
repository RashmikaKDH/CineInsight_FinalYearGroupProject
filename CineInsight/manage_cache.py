#!/usr/bin/env python3
"""CineInsight Cache Management Utility.

Terminal-only command to inspect and clear the Gemini aspect/sentiment cache.
Coordinates with the extraction pipeline via a shared cross-process lock.

Usage:
    python manage_cache.py status
    python manage_cache.py clear --type aspect-sentiment
"""
import argparse
import sys
from pathlib import Path

# Always resolve paths relative to this script, independent of working directory
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from src.extractors.llm_aspect_extractor import CACHE_DIR as _EXTRACTOR_CACHE_DIR
except ImportError:
    _EXTRACTOR_CACHE_DIR = Path("data/cache/aspect_sentiment")

try:
    from src.extractors.cache_lock import get_cache_lock, CrossProcessLock
except ImportError:
    from cache_lock import get_cache_lock, CrossProcessLock


def is_symlink_or_junction(path: Path) -> bool:
    """Check if path is a symlink or Windows directory junction."""
    try:
        if path.is_symlink():
            return True
        if hasattr(path, "is_junction") and path.is_junction():
            return True
    except OSError:
        pass
    return False


def get_aspect_sentiment_cache_dir(project_root: Path | None = None) -> Path:
    """Get absolute path to aspect_sentiment cache directory relative to project root."""
    root = (project_root or SCRIPT_DIR).resolve()
    cdir = Path(_EXTRACTOR_CACHE_DIR)
    if cdir.is_absolute():
        return cdir.resolve()
    return (root / cdir).resolve()


def verify_cache_dir_safety(cache_dir: Path, allowed_root: Path | None = None) -> Path:
    """Verify that the cache directory is safe to inspect/clear.

    Guards against:
    - Path traversal or resolving outside allowed project root
    - Symlinks and junctions
    - Targeting critical directories like project root, videos, CSVs, or logs
    """
    resolved_cache = cache_dir.resolve()
    root = (allowed_root or SCRIPT_DIR).resolve()

    # Must be inside allowed root
    if not resolved_cache.is_relative_to(root):
        raise ValueError(
            f"Path safety violation: Cache directory '{resolved_cache}' is outside '{root}'"
        )

    # Must not be the root itself or its parent
    if resolved_cache == root or resolved_cache == root.parent:
        raise ValueError(
            f"Path safety violation: Cache directory cannot be project root or system root: '{resolved_cache}'"
        )

    # Reject symlinks and junctions
    if is_symlink_or_junction(cache_dir) or is_symlink_or_junction(resolved_cache):
        raise ValueError(
            f"Path safety violation: Symlink or junction rejected: '{cache_dir}'"
        )

    # Must be an aspect_sentiment cache folder
    if not any("aspect_sentiment" in p.lower() for p in resolved_cache.parts):
        raise ValueError(
            f"Path safety violation: Target '{resolved_cache}' is not an aspect_sentiment cache directory"
        )

    return resolved_cache


def get_cached_files(cache_dir: Path, allowed_root: Path | None = None) -> list[Path]:
    """Retrieve and verify cached classification files inside the cache directory.

    Only matches valid classification files (.json, .tmp) directly within
    the verified directory. Rejects any symlinks, nested subdirectories,
    or files resolving outside the cache folder.
    """
    if not cache_dir.exists():
        return []

    resolved_cache = verify_cache_dir_safety(cache_dir, allowed_root)
    valid_files = []

    for entry in cache_dir.iterdir():
        # Reject symlinks and junctions
        if is_symlink_or_junction(entry):
            raise ValueError(
                f"Path safety violation: Symlink or junction entry found: '{entry.name}'"
            )

        resolved_entry = entry.resolve()

        # Must be a direct child of resolved_cache
        if not resolved_entry.is_relative_to(resolved_cache) or resolved_entry.parent != resolved_cache:
            raise ValueError(
                f"Path safety violation: File '{entry}' resolves outside cache directory: '{resolved_entry}'"
            )

        # Strictly regular files matching cache extension (.json or .tmp atomic write remnants)
        if entry.is_file() and not entry.is_dir():
            if entry.name.endswith(".json") or entry.name.endswith(".tmp"):
                valid_files.append(entry)

    return sorted(valid_files, key=lambda f: f.name)


def format_size(size_bytes: int) -> str:
    """Format byte count into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        kb = size_bytes / 1024.0
        return f"{kb:.2f} KB ({size_bytes:,} bytes)"
    else:
        mb = size_bytes / (1024.0 * 1024.0)
        return f"{mb:.2f} MB ({size_bytes:,} bytes)"


def run_status(
    cache_dir: Path | None = None,
    lock_path: Path | None = None,
    allowed_root: Path | None = None,
) -> int:
    """Show cache absolute path, file count, total size, and shared lock status."""
    target_dir = cache_dir or get_aspect_sentiment_cache_dir(allowed_root)
    abs_path = target_dir.resolve()

    print("=== CineInsight Cache Status ===")
    print(f"Cache Type:      aspect-sentiment")
    print(f"Absolute Path:   {abs_path}")

    if not abs_path.exists():
        print(f"Status:          Missing (directory does not exist)")
        print(f"File Count:      0 files")
        print(f"Total Size:      0 bytes")
        return 0

    try:
        verify_cache_dir_safety(target_dir, allowed_root)
        files = get_cached_files(target_dir, allowed_root)
    except ValueError as exc:
        print(f"Status:          Error ({exc})")
        return 1

    file_count = len(files)
    total_size = sum(f.stat().st_size for f in files)

    lpath = lock_path or (abs_path.parent / f".{abs_path.name}.lock")
    lock = get_cache_lock(lpath)
    lock_state = "Locked (active extraction in progress)" if lock.is_locked() else "Unlocked (idle)"

    status_str = "Empty" if file_count == 0 else "Active"
    print(f"Status:          {status_str}")
    print(f"File Count:      {file_count} cached classification file(s)")
    print(f"Total Size:      {format_size(total_size)}")
    print(f"Lock Status:     {lock_state}")
    return 0


def run_clear(
    cache_dir: Path | None = None,
    lock_path: Path | None = None,
    allowed_root: Path | None = None,
    confirm_input_fn=input,
) -> int:
    """Clear cached classification files with user confirmation and interprocess locking."""
    target_dir = cache_dir or get_aspect_sentiment_cache_dir(allowed_root)
    abs_path = target_dir.resolve()

    print("=== CineInsight Cache Clear ===")
    print(f"Cache Type:      aspect-sentiment")
    print(f"Absolute Path:   {abs_path}")

    if not abs_path.exists():
        print("Status:          Directory does not exist. Nothing to clear.")
        return 0

    try:
        verify_cache_dir_safety(target_dir, allowed_root)
        files = get_cached_files(target_dir, allowed_root)
    except ValueError as exc:
        print(f"Safety Error:    {exc}")
        return 1

    file_count = len(files)
    total_size = sum(f.stat().st_size for f in files)

    if file_count == 0:
        print("Status:          Cache is empty. Nothing to clear.")
        return 0

    print(f"Files to Remove: {file_count} cached classification file(s)")
    print(f"Total Size:      {format_size(total_size)}")
    print()
    print("Safety & Preservation Guarantee:")
    print("  - Deletes only cached classification files inside the verified cache folder.")
    print("  - Preserves videos, WAV files, initial/final CSVs, reports, and debug logs.")
    print("  - Subsequent analysis will make new Gemini requests for cleared entries.")
    print()

    try:
        confirmation = confirm_input_fn("Type 'CLEAR' to confirm: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nClearing cancelled. No files were removed.")
        return 1

    if confirmation != "CLEAR":
        print(f"Confirmation '{confirmation}' did not match 'CLEAR'. Clearing cancelled. No files were removed.")
        return 1

    lpath = lock_path or (abs_path.parent / f".{abs_path.name}.lock")
    lock = get_cache_lock(lpath)

    if lock.is_locked():
        print("[Lock] An active extraction is currently holding the cache lock. Waiting for it to finish...")

    with lock:
        # Re-check files inside the lock in case of concurrent writes
        files_to_delete = get_cached_files(target_dir, allowed_root)
        deleted_count = 0
        deleted_bytes = 0

        for file_path in files_to_delete:
            if is_symlink_or_junction(file_path):
                raise ValueError(f"Path safety violation: Refusing to delete symlink/junction: {file_path}")
            size = file_path.stat().st_size
            file_path.unlink()
            deleted_count += 1
            deleted_bytes += size

        print(f"\n[Success] Cleared {deleted_count} file(s) ({format_size(deleted_bytes)} freed).")
        print("Next analysis will make new Gemini requests for previously cached segments.")

    return 0


def main(args=None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage CineInsight Gemini Aspect/Sentiment Cache",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status subcommand
    status_parser = subparsers.add_parser("status", help="Show cache path, file count, and size")
    status_parser.add_argument(
        "--type",
        default="aspect-sentiment",
        choices=["aspect-sentiment"],
        help="Cache type to check (default: aspect-sentiment)",
    )

    # clear subcommand
    clear_parser = subparsers.add_parser("clear", help="Clear cached aspect/sentiment classifications")
    clear_parser.add_argument(
        "--type",
        default="aspect-sentiment",
        choices=["aspect-sentiment"],
        help="Cache type to clear (default: aspect-sentiment)",
    )

    parsed = parser.parse_args(args)

    if parsed.command == "status":
        return run_status()
    elif parsed.command == "clear":
        return run_clear()

    return 0


if __name__ == "__main__":
    sys.exit(main())
