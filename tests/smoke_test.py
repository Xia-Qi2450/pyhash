#!/usr/bin/env python3
"""
smoke_test.py - End-to-end regression check for pyhash.py.

Builds a throwaway directory tree, runs `hash`, then mutates files and runs
`check`, asserting the tool reports exactly what it should (OK / MODIFIED /
MISSING / NEW) and exits with the right status code.

No extra dependencies beyond what pyhash.py itself needs. Run it
directly:

    python tests/smoke_test.py

Exits 0 on success, 1 on any failed assertion - suitable for CI.
"""

import json
import shutil
import subprocess
import sys
import tempfile
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


def main():
    tmp = Path(tempfile.mkdtemp(prefix="pyhash_smoke_"))
    try:
        # --- build a small tree ---
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
