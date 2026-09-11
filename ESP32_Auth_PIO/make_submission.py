#!/usr/bin/env python3
"""Build the submission archive, and refuse to build one that leaks credentials.

    make submission            # -> ../../project2_submission.zip

The archive is the project tree without the things that must not be handed in
or are not worth handing in:

    .git/                      history, which still contains an old credential
    src/config.h               the live WiFi SSID and password (git-ignored, but
                               present in the working tree, so a plain zip of the
                               tree would ship it)
    .pio/                      build output, with those credentials compiled in
    .venv/, .venv_pio/         virtual environments
    .claude/, .agent/          editor and assistant tooling, not project content
    __pycache__/, .native/     build caches
    test_log.csv               scratch output from an interactive run

results/ IS included: the report cites a dataset, and a reader who cannot see it
cannot check any number in the document.

After zipping, the archive is unpacked and searched for the literal SSID and
password read from src/config.h. If either appears, the archive is deleted and
this exits non-zero -- a check that cannot be forgotten at the moment it matters.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent          # project2/
ROOT = PROJECT.parent                                     # repository root
OUT = ROOT / "project2_submission.zip"
CONFIG = PROJECT / "ESP32_Auth_PIO" / "src" / "config.h"

EXCLUDE_DIRS = {".git", ".venv", ".venv_pio", ".pio", ".claude", ".agent",
                "__pycache__", ".native", ".obsidian"}
EXCLUDE_FILES = {"config.h", "test_log.csv", "mock.pid"}


def credentials() -> list[tuple[str, str]]:
    """The literal values the archive must not contain, from config.h."""
    if not CONFIG.exists():
        return []
    text = CONFIG.read_text()
    out = []
    for field in ("WIFI_SSID", "WIFI_PASSWORD"):
        m = re.search(rf'#define\s+{field}\s+"([^"]*)"', text)
        if m and m.group(1):
            out.append((field, m.group(1)))
    return out


def wanted(path: Path) -> bool:
    rel = path.relative_to(PROJECT)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    return path.name not in EXCLUDE_FILES


def main() -> int:
    secrets = credentials()
    if not secrets:
        print(f"WARNING: no credentials found in {CONFIG}; the leak check will "
              "not run. Continuing.", file=sys.stderr)

    files = [p for p in PROJECT.rglob("*") if p.is_file() and wanted(p)]
    if not files:
        print("No files to archive.", file=sys.stderr)
        return 1

    OUT.unlink(missing_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            z.write(f, Path("project2") / f.relative_to(PROJECT))

    # Unpack and grep, rather than trusting the exclusion list to be complete.
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(OUT) as z:
            z.extractall(tmp)
        for field, value in secrets:
            hits = subprocess.run(["grep", "-rl", "-F", "--", value, tmp],
                                  capture_output=True, text=True).stdout.split()
            if hits:
                OUT.unlink(missing_ok=True)
                print(f"REFUSED: {len(hits)} file(s) in the archive contain the "
                      f"{field} from config.h:", file=sys.stderr)
                for h in hits[:10]:
                    print(f"  {Path(h).relative_to(tmp)}", file=sys.stderr)
                return 1

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUT}  ({len(files)} files, {size_mb:.1f} MB)")
    for field, _ in secrets:
        print(f"  checked: no {field} from config.h appears in the archive")
    print("  included: results/ (the datasets the report cites)")
    print("  excluded: " + ", ".join(sorted(EXCLUDE_DIRS | EXCLUDE_FILES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
