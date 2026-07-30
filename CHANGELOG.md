# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [1.1.0] - 2026-07-30

### Added

- `--quick` / `-q` flag on `hash` — when a directory already has a
  checksum log, files whose size and modified time still match the log
  are trusted as unchanged and skipped, instead of being re-read and
  re-hashed. Only new or actually-changed files are hashed. Falls back to
  a full hash automatically if the cached log is missing, corrupt, or was
  written with a different algorithm.
- Move/rename detection in `check` — a missing file and a new file whose
  hashes match exactly are now reported as `MOVED: old_path -> new_path`
  instead of as an unrelated `MISSING` + `NEW` pair. A pure move does not
  affect the command's exit code, since nothing was actually lost. Can be
  disabled with `--no-detect-moves` / `-nm` to restore the previous
  MISSING + NEW behavior. Note: only pairs against new files inside
  directories that already have a log — a file moved into a brand-new,
  never-hashed directory is not detected as a move.
- `tests/smoke_test.py` extended with coverage for `--quick` (full reuse,
  partial reuse after a real change) and move detection (both threaded
  and sequential paths, plus `--no-detect-moves`).

### Fixed

- Removed a stray leftover string-literal artifact after the module
  docstring.

## [1.0.0] - 2026-07-25

Initial release.

### Added

- `hash` command — recursively scans a folder or drive and writes a
  `checksums.json` log **inside every directory it visits**, containing
  each file's hash, size, and modified time.
- `check` command — re-hashes files and compares them against the logs,
  reporting `OK`, `MODIFIED`, `MISSING`, and `NEW` per file, plus a summary
  and a nonzero exit code when issues are found.
- Self-healing logs: re-running `hash` refreshes every log and removes
  stale logs for directories whose tracked files have all been deleted.
- Support for five hash algorithms: `md5`, `sha1`, `sha256` (default),
  `sha512`, `blake2b`.
- Threaded hashing via `--workers` for faster scans on large drives.
- Directory/file exclusion via `--exclude-dirs` and `--exclude-files`
  (glob patterns), with common noise directories (`.git`, `node_modules`,
  `__pycache__`, `.venv`, `$RECYCLE.BIN`, etc.) excluded by default.
- `--no-recursive` and `--include-hidden` flags for finer scan control.
- Optional `--report` flag on `check` to export a full JSON summary.
- Halo spinner during directory scanning, tqdm progress bar during
  hashing/verifying, and color-coded terminal output (auto-disabled for
  non-TTY output or via `--no-color`).
- `tests/smoke_test.py` — end-to-end regression test covering hashing,
  clean verification, and modified/missing/new detection.
- GitHub Actions CI workflow running the smoke test across
  Ubuntu/Windows/macOS and Python 3.10/3.13.
- GitHub Actions release workflow building standalone executables
  (Windows/macOS/Linux) via PyInstaller and attaching them to tagged
  releases.
