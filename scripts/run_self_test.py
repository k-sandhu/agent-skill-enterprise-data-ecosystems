#!/usr/bin/env python3
"""End-to-end self-test for the ecosystem engine.

1. Validates the worked example spec (must have zero errors).
2. Builds it twice in separate subprocesses with DIFFERENT PYTHONHASHSEED values
   (actively provoking hash-order nondeterminism) and compares logical per-table
   content hashes — every table must match.
3. Runs the database validator in --strict mode (zero critical AND zero warnings).
4. Runs the profiler to confirm it executes.

Usage:
  python run_self_test.py [--spec path] [--keep] [--scale-multiplier 1.0]

Exit codes: 0 all green, 1 failure, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_SPEC = SCRIPTS.parent / "examples" / "harborline-provisions" / "ecosystem_spec.json"
EXCLUDED_FROM_HASH = {"meta_build_info"}  # contains the wall-clock build timestamp


def run(cmd: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", env=env)


def logical_hashes(db_path: Path) -> dict[str, str]:
    """Per-table sha256 over ordered rows with canonical serialization."""
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    hashes: dict[str, str] = {}
    try:
        tables = [r[0] for r in conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        for table in tables:
            if table in EXCLUDED_FROM_HASH:
                continue
            digest = hashlib.sha256()
            for row in conn.execute(f'select * from "{table}" order by rowid'):
                canonical = "\x1f".join(
                    f"{value:.10g}" if isinstance(value, float) else repr(value) for value in row)
                digest.update(canonical.encode("utf-8"))
            hashes[table] = digest.hexdigest()
    finally:
        conn.close()
    return hashes


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--scale-multiplier", type=float, default=0.3,
                        help="Scale for the test builds (default 0.3 for speed)")
    parser.add_argument("--keep", action="store_true", help="Keep the temp build directory")
    args = parser.parse_args(argv)

    if not args.spec.exists():
        print(f"error: spec not found: {args.spec}", file=sys.stderr)
        return 2

    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="ecosystem_selftest_"))
    print(f"Self-test workspace: {tmp}")
    try:
        # 1. Spec validation
        print("\n[1/4] validate_ecosystem_spec.py ...")
        result = run([sys.executable, str(SCRIPTS / "validate_ecosystem_spec.py"), str(args.spec)])
        print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)")
        if result.returncode != 0:
            failures.append(f"spec validation failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")

        # 2. Deterministic double build with different hash seeds
        print("\n[2/4] double build with PYTHONHASHSEED 1 vs 2 ...")
        builds = []
        for i, hash_seed in enumerate(("1", "2")):
            out_dir = tmp / f"build{i}"
            result = run([sys.executable, str(SCRIPTS / "build_sqlite_ecosystem.py"), str(args.spec),
                          "--out", str(out_dir), "--scale-multiplier", str(args.scale_multiplier),
                          "--force", "--quiet"],
                         env_extra={"PYTHONHASHSEED": hash_seed})
            if result.returncode != 0:
                failures.append(f"build {i} failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
                break
            db_files = list(out_dir.glob("*.db"))
            if not db_files:
                failures.append(f"build {i} produced no .db file in {out_dir}")
                break
            builds.append(db_files[0])
        if len(builds) == 2:
            h0, h1 = logical_hashes(builds[0]), logical_hashes(builds[1])
            if set(h0) != set(h1):
                failures.append(f"table sets differ between builds: {set(h0) ^ set(h1)}")
            else:
                diverged = [t for t in sorted(h0) if h0[t] != h1[t]]
                if diverged:
                    failures.append(f"DETERMINISM FAILURE: {len(diverged)} tables diverge "
                                    f"across hash seeds: {diverged[:5]}")
                else:
                    print(f"deterministic: {len(h0)} tables hash-identical across PYTHONHASHSEED 1 vs 2")

        # 3. Strict database validation
        if builds:
            print("\n[3/4] validate_sqlite_database.py --strict ...")
            result = run([sys.executable, str(SCRIPTS / "validate_sqlite_database.py"),
                          "--db", str(builds[0]), "--spec", str(args.spec), "--strict"])
            verdict_lines = [l for l in result.stdout.splitlines() if l.startswith("## Verdict") or "Realism score" in l]
            for line in verdict_lines:
                print(line)
            if result.returncode != 0:
                failures.append(f"strict validation failed (exit {result.returncode}); "
                                "see findings:\n" + "\n".join(
                                    l for l in result.stdout.splitlines()
                                    if l.startswith("- **")) + f"\n{result.stderr}")

            # 4. Profiler smoke
            print("\n[4/4] profile_sqlite_database.py ...")
            result = run([sys.executable, str(SCRIPTS / "profile_sqlite_database.py"),
                          "--db", str(builds[0]), "--report", str(tmp / "profile.md")])
            if result.returncode != 0:
                failures.append(f"profiler failed (exit {result.returncode}):\n{result.stderr}")
            else:
                print("profiler OK")
    finally:
        if args.keep:
            print(f"\nKeeping workspace: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("SELF-TEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELF-TEST PASSED: spec valid, deterministic across hash seeds, strict validation green, profiler OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
