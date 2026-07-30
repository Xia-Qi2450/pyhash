# pyhash

[![Making sure that the code still functions](https://github.com/Xia-Qi2450/pyhash/actions/workflows/ci.yml/badge.svg)](https://github.com/Xia-Qi2450/pyhash/actions/workflows/ci.yml) [![Build & Release the app](https://github.com/Xia-Qi2450/pyhash/actions/workflows/release.yml/badge.svg)](https://github.com/Xia-Qi2450/pyhash/actions/workflows/release.yml) [![GitHub Release](https://img.shields.io/github/v/release/Xia-Qi2450/pyhash)](https://github.com/Xia-Qi2450/pyhash/releases)

A recursive, per-directory file checksum maker & verifier. Point it at any folder or a whole drive (may take longer depending on your drive speed) and it hashes every file, writing a small (or big) `checksums.json` log **inside each directory it visits** — so the logs stay right next to the files they describe.

Run it again later in `check` mode to find anything that's changed, corrupted, gone missing, or shown up unexpectedly.

Uses `tqdm` for a live progress bar while hashing, and `halo` for a spinner during the initial directory scan (falls back to a message if `halo` isn't installed).

---

## Install

### Option 1: Download a prebuilt executable (recommended)

Prebuilt standalone executables are available for:

- Windows
- Linux (Ubuntu)
- macOS

Download the latest release from the **Releases** page and run it directly — no Python installation or dependencies required.

> **Note**: Since the macOS build isn't code signed or notarized, Gatekeeper may block it on first launch. If that happens, right-click → Open, or remove the quarantine attribute if you're comfortable using Terminal. Remember to run `chmod +x path/to/executable` so that you can run it normally from the terminal.

### Option 2: Run from source

```bash
pip install tqdm halo
```

(`halo` is optional, the tool still works without it, just with a plainer "scanning..." message instead of a spinner. But honestly... just install `halo`, it's way cooler anyway.)

---

## Usage

### Hash a folder / drive

**Windows**:

```bash
python pyhash.py hash "D:\Photos"
```

**Mac/Darwin**:

```bash
python3 pyhash.py hash "/Volumes/drivename"
```

**Linux**:

```bash
python pyhash.py hash "/media/drivename"
```

This looks through every subdirectory and writes a `checksums.json` in each one containing the algorithm used, a timestamp, and each file's hash, size, and modified time. You can read this obviously but please don't go around randomly editing something in that `JSON` file.

Re-running `hash` fully refreshes every log including removing logs for directories whose tracked files have all been deleted. We don't want random `checksums.json` lying around in dead directories right?

---

## Standalone executables

The bundled executables include Python and all required dependencies, so you can simply download the version for your operating system and start hashing immediately.

Current builds are available for:

| Operating System | Architecture |
| ------------------ | -------------- |
| Windows | x64 |
| Ubuntu Linux | x64 |
| macOS | Apple Silicon (arm64) |

Every release is automatically built using GitHub Actions.

---

### Verify against existing logs

```bash
python pyhash.py check "D:\Photos" --report report.json
```

Compares every file against its recorded hash and reports:

- **OK** — hash matches, your files are safe
- **MODIFIED** — file content has changed, possible corruption if you didn't edit them
- **MISSING** — file is listed in the log but no longer exists, it probably got deleted
- **NEW** — file exists but isn't in the log yet, rerun with the `hash` argument to add it to the checksum

Exits with status code `1` if anything is modified, missing, or errors out, and `0` if everything checks out clean — handy for scripting or scheduled integrity checks. Pass `--report path.json` to also save a full machine readable summary.

---

## Common options

| Flag | Description |
| --- | --- |
| `-q`/`--quick` | *(hash only)* quickens the hashing process by skipping files whose size and modified time match the existing log. Added as a quality-of-life feature. |
| `-a`/`--algorithm {md5,sha1,sha256,sha512,blake2b}` | Hash algorithm (default: `sha256`). Change to whichever that tickles your fancy (actually don't do that) |
| `-l`/`--log-name NAME` | Checksum log filename (default: `checksums.json`). If you name it `egfbweafbakeb.json`, I'm judging you |
| `-nr`/`--no-recursive` | Only scan the top-level folder. Generally makes it faster |
| `-v`/`--include-hidden` | Include dotfiles / dot-directories. If you want your hidden files to be also hashed |
| `-xd`/`--exclude-dirs NAME [NAME ...]` | Extra directory names to skip. `4K Homework` gotta be one of them |
| `-xf`/`--exclude-files PATTERN [PATTERN ...]` | Glob pattern(s) (a bit like `.gitignore` files) to skip, e.g. `*.tmp` |
| `-w`/`--workers N` | Parallel hashing threads (default: `4`, use `1` for sequential or if you want it to be slow) |
| `-nc`/`--no-color` | Disable colored output if your terminal is old and doesn't support ANSI |
| `-r`/`--report PATH` | *(check only)* write a JSON summary report for checking. |

By default, common not so important directories (`.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `$RECYCLE.BIN`, `System Volume Information`, etc.) are skipped automatically, you don't need to add them.

---

## Examples

**Hashing**:

```terminal
✔ Found 231 file(s) across 35 directories
Hashing: 100%|███████████████████████| 231/231 [00:00<00:00, 789.04file/s, 1-3_combat.ogg]

Done. 231 file(s) hashed, 35 log file(s) written (checksums.json).
```

**Checking**:

```terminal
✔ Scanned 35 directories
Verifying: 100%|████████████████████| 231/231 [00:00<00:00, 1183.77file/s, 1-3_combat.ogg]

Summary
  OK:        231
  Modified:  0
  Missing:   0
  New:       0
  Errors:    0

Report written to /path/to/your/report.json

All verified files match their recorded checksums.
```

**Example `checksums.json`**:

```json
{
  "algorithm": "sha256",
  "generated_at": "2026-07-25T09:25:47+00:00",
  "files": {
    "1-3_combat.ogg": {
      "hash": "d2486419d19bb0022cbcfdc9f2b4c797fbd225d7f816b048439b0124f867d57a",
      "modified": "2026-07-16T14:06:39+00:00",
      "size": 10290135
  }
}
```

Yes that is "[Heaven Pierce Her - Castle Vein (Combat)](https://ultrakill.wiki.gg/images/1-3_Combat.ogg)" from [ULTRAKILL](https://store.steampowered.com/app/1229490/ULTRAKILL/).

---

## License

This project is licensed under the MIT License. Always gotta love free and open-source software.
