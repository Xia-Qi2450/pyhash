#!/usr/bin/env python3
r"""
pyhash.py - Recursive, per-directory file checksum maker & verifier.

Walks a target folder (or an entire drive) and, for every directory it
visits, writes a small JSON "checksum log" containing hashes of the files
that live directly in that directory. Run it again in "check" mode later
to find anything that changed, disappeared, or showed up unexpectedly.

Requires:
    tqdm   (progress bar while hashing)      -> pip install tqdm
    halo   (spinner while scanning, optional) -> pip install halo

Usage:
    python pyhash.py hash  <path> [options]
    python pyhash.py check <path> [options]

Examples:
    python pyhash.py hash D:\Photos --algorithm sha256
    python pyhash.py check D:\Photos --report report.json
""" """"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    print("This tool requires 'tqdm'. Install it with:  pip install tqdm")
    sys.exit(1)

try:
    from halo import Halo
    HALO_AVAILABLE = True
except ImportError:
    HALO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Console colors (ANSI, no extra dependency needed for this part)
# ---------------------------------------------------------------------------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    @classmethod
    def disable(cls):
        for attr in ("RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN"):
            setattr(cls, attr, "")


class DummySpinner:
    """Fallback used when halo isn't installed - keeps the same interface."""

    def __init__(self, text=""):
        self.text = text

    def __enter__(self):
        print(f"{C.CYAN}...{C.RESET} {self.text}")
        return self

    def __exit__(self, *exc):
        return False

    def succeed(self, text=None):
        print(f"{C.GREEN}\u2714{C.RESET} {text or self.text}")

    def fail(self, text=None):
        print(f"{C.RED}\u2718{C.RESET} {text or self.text}")


def spinner(text: str):
    if HALO_AVAILABLE:
        return Halo(text=text, spinner="dots")
    return DummySpinner(text)


LOG_FILENAME_DEFAULT = "checksums.json"
CHUNK_SIZE = 1024 * 1024  # 1 MiB read chunks
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv",
    ".idea", ".vscode", "$RECYCLE.BIN", "System Volume Information",
}
SUPPORTED_ALGORITHMS = ("md5", "sha1", "sha256", "sha512", "blake2b")


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------
def hash_file(path: Path, algorithm: str) -> str:
    """Stream a file through the hasher in chunks so large files don't blow up memory."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def truncate(text: str, width: int = 40) -> str:
    return text if len(text) <= width else text[: width - 1] + "\u2026"


def eligible_names(filenames, log_filename, include_hidden, exclude_files):
    result = []
    for name in filenames:
        if name == log_filename:
            continue
        if not include_hidden and name.startswith("."):
            continue
        if any(fnmatch.fnmatch(name, pat) for pat in exclude_files):
            continue
        result.append(name)
    return result


def discover_directories(root: Path, recursive: bool, exclude_dirs, include_hidden):
    """Yield (directory_path, [filenames]) pairs, pruning excluded/hidden dirs."""
    if recursive:
        import os
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in exclude_dirs and (include_hidden or not d.startswith("."))
            ]
            yield Path(dirpath), filenames
    else:
        filenames = [p.name for p in root.iterdir() if p.is_file()]
        yield root, filenames


def resolve_root(raw_path: str) -> Path:
    root = Path(raw_path).expanduser().resolve()
    if not root.exists():
        print(f"{C.RED}Path does not exist:{C.RESET} {root}")
        sys.exit(1)
    if not root.is_dir():
        print(f"{C.RED}Path is not a directory:{C.RESET} {root}")
        sys.exit(1)
    return root


# ---------------------------------------------------------------------------
# hash command
# ---------------------------------------------------------------------------
def run_hash(args):
    root = resolve_root(args.path)
    exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(args.exclude_dirs or [])
    exclude_files = args.exclude_files or []

    with spinner("Scanning directory tree...") as sp:
        dir_files = []
        stale_logs = []  # directories that used to have a log but now have no eligible files
        for dirpath, filenames in discover_directories(root, not args.no_recursive, exclude_dirs, args.include_hidden):
            names = eligible_names(filenames, args.log_name, args.include_hidden, exclude_files)
            if names:
                dir_files.append((dirpath, names))
            elif (dirpath / args.log_name).exists():
                stale_logs.append(dirpath / args.log_name)
        total = sum(len(names) for _, names in dir_files)
        sp.succeed(f"Found {total} file(s) across {len(dir_files)} director{'y' if len(dir_files) == 1 else 'ies'}")

    if total == 0:
        print(f"{C.YELLOW}Nothing to hash.{C.RESET}")
        return

    logs = {dirpath: {"algorithm": args.algorithm, "generated_at": iso_now(), "files": {}} for dirpath, _ in dir_files}
    tasks = [(dirpath, name) for dirpath, names in dir_files for name in names]
    errors = 0

    def work(dirpath: Path, name: str):
        fpath = dirpath / name
        digest = hash_file(fpath, args.algorithm)
        stat = fpath.stat()
        return dirpath, name, {
            "hash": digest,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        }

    with tqdm(total=total, unit="file", desc="Hashing", ncols=90) as bar:
        if args.workers <= 1:
            for dirpath, name in tasks:
                bar.set_postfix_str(truncate(name))
                try:
                    d, n, entry = work(dirpath, name)
                    logs[d]["files"][n] = entry
                except OSError as e:
                    errors += 1
                    tqdm.write(f"{C.RED}  ERROR{C.RESET} {dirpath / name}: {e}")
                bar.update(1)
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(work, d, n): (d, n) for d, n in tasks}
                for fut in as_completed(futures):
                    d, n = futures[fut]
                    bar.set_postfix_str(truncate(n))
                    try:
                        d2, n2, entry = fut.result()
                        logs[d2]["files"][n2] = entry
                    except OSError as e:
                        errors += 1
                        tqdm.write(f"{C.RED}  ERROR{C.RESET} {d / n}: {e}")
                    bar.update(1)

    written = 0
    for dirpath, log_data in logs.items():
        if not log_data["files"]:
            continue
        log_path = dirpath / args.log_name
        try:
            log_path.write_text(json.dumps(log_data, indent=2, sort_keys=True), encoding="utf-8")
            written += 1
        except OSError as e:
            print(f"{C.RED}Failed to write log in {dirpath}: {e}{C.RESET}")

    removed = 0
    for log_path in stale_logs:
        try:
            log_path.unlink()
            removed += 1
        except OSError as e:
            print(f"{C.RED}Failed to remove stale log {log_path}: {e}{C.RESET}")

    print()
    print(f"{C.BOLD}Done.{C.RESET} {C.GREEN}{total - errors} file(s) hashed{C.RESET}, "
          f"{written} log file(s) written ({args.log_name}).")
    if removed:
        print(f"{C.DIM}Removed {removed} stale log file(s) for directories with no matching files.{C.RESET}")
    if errors:
        print(f"{C.RED}{errors} file(s) could not be read.{C.RESET}")


# ---------------------------------------------------------------------------
# check command
# ---------------------------------------------------------------------------
def run_check(args):
    root = resolve_root(args.path)
    exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(args.exclude_dirs or [])
    exclude_files = args.exclude_files or []

    with spinner("Scanning directory tree...") as sp:
        dir_entries = []  # (dirpath, present_names, log_data_or_None, corrupt_bool)
        for dirpath, filenames in discover_directories(root, not args.no_recursive, exclude_dirs, args.include_hidden):
            names = set(eligible_names(filenames, args.log_name, args.include_hidden, exclude_files))
            log_path = dirpath / args.log_name
            log_data, corrupt = None, False
            if log_path.exists():
                try:
                    log_data = json.loads(log_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    corrupt = True
            if names or log_data:
                dir_entries.append((dirpath, names, log_data, corrupt))
        sp.succeed(f"Scanned {len(dir_entries)} director{'y' if len(dir_entries) == 1 else 'ies'}")

    results = {"ok": [], "modified": [], "missing": [], "new": [], "errors": [], "corrupt_logs": [], "no_log_dirs": []}
    hash_tasks = []  # (dirpath, name, expected_hash, algorithm)

    for dirpath, present_names, log_data, corrupt in dir_entries:
        if corrupt:
            results["corrupt_logs"].append(str(dirpath / args.log_name))
            print(f"{C.RED}  CORRUPT LOG{C.RESET} {dirpath / args.log_name}")
            continue
        if log_data is None:
            if present_names:
                results["no_log_dirs"].append(str(dirpath))
            continue

        logged = log_data.get("files", {})
        algo = log_data.get("algorithm", args.algorithm)
        logged_names = set(logged.keys())

        for missing_name in sorted(logged_names - present_names):
            path = dirpath / missing_name
            results["missing"].append(str(path))
            print(f"{C.RED}  MISSING{C.RESET}  {path}")

        for new_name in sorted(present_names - logged_names):
            path = dirpath / new_name
            results["new"].append(str(path))
            print(f"{C.YELLOW}  NEW{C.RESET}      {path}")

        for common_name in logged_names & present_names:
            hash_tasks.append((dirpath, common_name, logged[common_name].get("hash"), algo))

    total = len(hash_tasks)
    if total:
        def work(dirpath, name, expected, algo):
            fpath = dirpath / name
            digest = hash_file(fpath, algo)
            return dirpath, name, digest == expected

        with tqdm(total=total, unit="file", desc="Verifying", ncols=90) as bar:
            if args.workers <= 1:
                for dirpath, name, expected, algo in hash_tasks:
                    bar.set_postfix_str(truncate(name))
                    fpath = dirpath / name
                    try:
                        _, _, ok = work(dirpath, name, expected, algo)
                        target = results["ok"] if ok else results["modified"]
                        target.append(str(fpath))
                        if not ok:
                            tqdm.write(f"{C.RED}  MODIFIED{C.RESET} {fpath}")
                    except OSError as e:
                        results["errors"].append(f"{fpath}: {e}")
                        tqdm.write(f"{C.RED}  ERROR{C.RESET}    {fpath}: {e}")
                    bar.update(1)
            else:
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    futures = {pool.submit(work, d, n, e, a): (d, n) for d, n, e, a in hash_tasks}
                    for fut in as_completed(futures):
                        d, n = futures[fut]
                        fpath = d / n
                        bar.set_postfix_str(truncate(n))
                        try:
                            _, _, ok = fut.result()
                            target = results["ok"] if ok else results["modified"]
                            target.append(str(fpath))
                            if not ok:
                                tqdm.write(f"{C.RED}  MODIFIED{C.RESET} {fpath}")
                        except OSError as e:
                            results["errors"].append(f"{fpath}: {e}")
                            tqdm.write(f"{C.RED}  ERROR{C.RESET}    {fpath}: {e}")
                        bar.update(1)

    # ---- summary ----
    print()
    print(f"{C.BOLD}Summary{C.RESET}")
    print(f"  {C.GREEN}OK{C.RESET}:        {len(results['ok'])}")
    print(f"  {C.RED}Modified{C.RESET}:  {len(results['modified'])}")
    print(f"  {C.RED}Missing{C.RESET}:   {len(results['missing'])}")
    print(f"  {C.YELLOW}New{C.RESET}:       {len(results['new'])}")
    print(f"  {C.RED}Errors{C.RESET}:    {len(results['errors']) + len(results['corrupt_logs'])}")
    if results["no_log_dirs"]:
        print(f"  {C.DIM}Directories with no log: {len(results['no_log_dirs'])}{C.RESET}")

    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report = {"checked_at": iso_now(), "root": str(root), "results": results}
        try:
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"\n{C.CYAN}Report written to {report_path}{C.RESET}")
        except OSError as e:
            print(f"{C.RED}Failed to write report: {e}{C.RESET}")

    problems = len(results["modified"]) + len(results["missing"]) + len(results["errors"]) + len(results["corrupt_logs"])
    if problems == 0:
        print(f"\n{C.GREEN}{C.BOLD}All verified files match their recorded checksums.{C.RESET}")
        sys.exit(0)
    else:
        print(f"\n{C.RED}{C.BOLD}{problems} issue(s) found.{C.RESET}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="pyhash.py",
        description="Recursive, per-directory file checksum maker & verifier.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("path", help="Folder or drive to scan")
        p.add_argument("-a", "--algorithm", choices=SUPPORTED_ALGORITHMS, default="sha256",
                        help="Hash algorithm (default: sha256)")
        p.add_argument("-l", "--log-name", default=LOG_FILENAME_DEFAULT,
                        help=f"Checksum log filename (default: {LOG_FILENAME_DEFAULT})")
        p.add_argument("-nr", "--no-recursive", action="store_true",
                        help="Only scan the top-level folder, not subdirectories")
        p.add_argument("-v", "--include-hidden", action="store_true",
                        help="Include hidden files/directories (names starting with '.')")
        p.add_argument("-xd", "--exclude-dirs", nargs="*", default=[],
                        help="Extra directory names to skip")
        p.add_argument("-xf", "--exclude-files", nargs="*", default=[],
                        help="Glob pattern(s) of filenames to skip, e.g. *.tmp")
        p.add_argument("-w", "--workers", type=int, default=4,
                        help="Parallel hashing threads (default: 4, use 1 for sequential)")
        p.add_argument("-nc", "--no-color", action="store_true", help="Disable colored output")

    p_hash = sub.add_parser("hash", help="Hash files and write per-directory checksum logs")
    add_common(p_hash)

    p_check = sub.add_parser("check", help="Verify files against existing checksum logs")
    add_common(p_check)
    p_check.add_argument("-r","--report", help="Write a JSON summary report to this path")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        C.disable()

    if args.command == "hash":
        run_hash(args)
    elif args.command == "check":
        run_check(args)


if __name__ == "__main__":
    main()
