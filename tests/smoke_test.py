#!/usr/bin/env python3
"""
smoke_test.py - End-to-end regression check for pyhash.py.

Builds a throwaway directory tree, runs `hash`, then mutates files and runs
`check`, asserting the tool reports exactly what it should (OK / MODIFIED /
MISSING / NEW / MOVED) and exits with the right status code. Also covers
--quick (cached-hash reuse) and move/rename detection.

No extra dependencies beyond what pyhash.py itself needs. Run it directly:

    python tests/smoke_test.py

Exits 0 on success, 1 on any failed assertion - suitable for CI.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "pyhash.py"

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"  FAIL: {message}")
    else:
        print(f"  ok:   {message}")


def run(*args):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


def basic_hash_and_check(tmp):
    (tmp / "sub").mkdir()
    (tmp / "a.txt").write_text("hello world")
    (tmp / "sub" / "b.txt").write_text("nested file")

    print("1. Initial hash")
    rc, out, err = run("hash", str(tmp), "--workers", "1", "--no-color")
    check(rc == 0, "hash command exits 0")
    check((tmp / "checksums.json").exists(), "root checksums.json created")
    check((tmp / "sub" / "checksums.json").exists(), "sub/checksums.json created")

    log = json.loads((tmp / "checksums.json").read_text())
    check("a.txt" in log.get("files", {}), "a.txt present in root log")
    check(log.get("algorithm") == "sha256", "default algorithm is sha256")

    print("2. Check against unmodified tree (expect clean)")
    rc, out, err = run("check", str(tmp), "--workers", "1", "--no-color")
    check(rc == 0, "check exits 0 when nothing changed")
    check("Modified:  0" in out, "no modified files reported")
    check("Missing:   0" in out, "no missing files reported")

    print("3. Mutate: edit, delete, add")
    (tmp / "a.txt").write_text("hello world - EDITED")
    (tmp / "sub" / "b.txt").unlink()
    (tmp / "new_file.txt").write_text("surprise")

    rc, out, err = run("check", str(tmp), "--workers", "1", "--no-color")
    check(rc == 1, "check exits 1 when issues are present")
    check("MODIFIED" in out and "a.txt" in out, "a.txt reported as modified")
    check("MISSING" in out and "b.txt" in out, "b.txt reported as missing")
    check("NEW" in out and "new_file.txt" in out, "new_file.txt reported as new")

    print("4. Re-hash should self-heal (sub/ log removed, since b.txt is gone)")
    rc, out, err = run("hash", str(tmp), "--workers", "1", "--no-color")
    check(rc == 0, "re-hash exits 0")
    check(not (tmp / "sub" / "checksums.json").exists(),
          "stale sub/checksums.json removed after re-hash (no files left there)")

    rc, out, err = run("check", str(tmp), "--workers", "1", "--no-color")
    check(rc == 0, "check is clean again after re-hash")


def quick_mode(tmp):
    print("5. --quick: initial hash")
    (tmp / "q1.txt").write_text("quick file one")
    (tmp / "q2.txt").write_text("quick file two")
    rc, out, err = run("hash", str(tmp), "--workers", "1", "--no-color")
    check(rc == 0, "quick-mode setup hash exits 0")

    print("6. --quick with nothing changed (expect everything reused)")
    rc, out, err = run("hash", str(tmp), "--quick", "--workers", "1", "--no-color")
    check(rc == 0, "--quick exits 0")
    check("0 file(s) hashed" in out, "--quick re-hashes nothing when unchanged")
    check("unchanged (skipped via --quick)" in out, "--quick reports skipped count")

    print("7. --quick with one file changed (expect exactly one re-hash)")
    time.sleep(1.1)  # ensure mtime resolution ticks over
    (tmp / "q1.txt").write_text("quick file one - EDITED")
    rc, out, err = run("hash", str(tmp), "--quick", "--workers", "1", "--no-color")
    check(rc == 0, "--quick with a change exits 0")
    check("1 file(s) hashed" in out, "--quick re-hashes only the changed file")

    rc, out, err = run("check", str(tmp), "--workers", "1", "--no-color")
    check(rc == 0, "check confirms --quick correctly updated the changed file's hash")


def move_detection(tmp):
    print("8. Move detection: setup two pre-logged directories")
    (tmp / "moves").mkdir()
    (tmp / "moves" / "src").mkdir()
    (tmp / "moves" / "dst").mkdir()
    (tmp / "moves" / "src" / "keepme.txt").write_text("stays put")
    (tmp / "moves" / "src" / "moveme.txt").write_text("gets relocated")
    (tmp / "moves" / "dst" / "other.txt").write_text("already here")
    run("hash", str(tmp / "moves"), "--workers", "1", "--no-color")

    print("9. Move a file between two already-logged directories")
    shutil.move(str(tmp / "moves" / "src" / "moveme.txt"), str(tmp / "moves" / "dst" / "moveme_renamed.txt"))
    rc, out, err = run("check", str(tmp / "moves"), "--workers", "1", "--no-color")
    check(rc == 0, "check exits 0 for a pure move - nothing was actually lost")
    check("MOVED" in out, "move is reported as MOVED")
    check("moveme.txt" in out and "moveme_renamed.txt" in out, "MOVED line shows both old and new paths")
    check("Missing:   0" in out, "moved file is not double-counted as missing")
    check("New:       0" in out, "moved file is not double-counted as new")

    print("10. --no-detect-moves falls back to MISSING + NEW")
    rc, out, err = run("check", str(tmp / "moves"), "--no-detect-moves", "--workers", "1", "--no-color")
    check("MISSING" in out, "--no-detect-moves reports MISSING")
    check("NEW" in out, "--no-detect-moves reports NEW")
    check("MOVED" not in out, "--no-detect-moves never prints MOVED")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="pyhash_smoke_"))
    try:
        basic_hash_and_check(tmp)
        quick_mode(tmp)
        move_detection(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} failure(s).")
        sys.exit(1)
    print("All smoke tests passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()