#!/usr/bin/env python3
"""End-to-end self-test for the ecosystem engine.

1. Validates the worked example spec (must have zero errors).
2. Builds it twice in separate subprocesses with DIFFERENT PYTHONHASHSEED values
   (actively provoking hash-order nondeterminism) and compares logical per-table
   content hashes — every table must match.
3. Runs the database validator in --strict mode (zero critical AND zero warnings).
4. Runs the profiler to confirm it executes.
5. Generates the read-only MCP server package, runs the full MCP battery
   (handshake, every tool, the read-only negative battery with a db-hash check,
   the query timeout, clamps, lineage, resources, prompts, protocol errors),
   and a double-generation byte-determinism check on the emitted package.
6. Rebuilds with high-rate copy-style imperfections (duplicate_entity,
   duplicate_webhook, restatement_reversal) appended to one integer-PK table —
   thousands of synthetic PKs per stream. Guards the collision-free allocator:
   random draws from the old 1e6-wide range birthday-collide at this volume and
   crash the build with a UNIQUE constraint failure.

Usage:
  python run_self_test.py [--spec path] [--keep] [--scale-multiplier 1.0]

Exit codes: 0 all green, 1 failure, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import test_mcp_server

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
                # Type-tagged, full-fidelity float repr: rounding would mask real
                # divergence, and float 2.0 must not collide with int 2.
                canonical = "\x1f".join(
                    f"f:{value!r}" if isinstance(value, float) else repr(value) for value in row)
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
        print("\n[1/6] validate_ecosystem_spec.py ...")
        result = run([sys.executable, str(SCRIPTS / "validate_ecosystem_spec.py"), str(args.spec)])
        print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)")
        if result.returncode != 0:
            failures.append(f"spec validation failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")

        # 2. Deterministic double build with different hash seeds
        print("\n[2/6] double build with PYTHONHASHSEED 1 vs 2 ...")
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
            print("\n[3/6] validate_sqlite_database.py --strict ...")
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
            print("\n[4/6] profile_sqlite_database.py ...")
            result = run([sys.executable, str(SCRIPTS / "profile_sqlite_database.py"),
                          "--db", str(builds[0]), "--report", str(tmp / "profile.md")])
            if result.returncode != 0:
                failures.append(f"profiler failed (exit {result.returncode}):\n{result.stderr}")
            else:
                print("profiler OK")

            # 5. MCP server: generate the package, run the full battery, and the
            # double-generation byte-determinism check.
            print("\n[5/6] generate_mcp_server.py + MCP battery ...")
            build_dir = builds[0].parent
            result = run([sys.executable, str(SCRIPTS / "generate_mcp_server.py"), str(args.spec),
                          "--build", str(build_dir), "--force", "--quiet"])
            if result.returncode != 0:
                failures.append(f"MCP generation failed (exit {result.returncode}):\n"
                                f"{result.stdout}\n{result.stderr}")
            else:
                battery = test_mcp_server.run_full_battery(build_dir, args.spec)
                determinism = test_mcp_server.run_determinism_check(build_dir, args.spec)
                if battery or determinism:
                    failures.append("MCP battery failed:\n  " + "\n  ".join(battery + determinism))
                else:
                    print("MCP server OK: 11 tools, read-only safety stack holds, "
                          "package byte-deterministic across two generations")

        # 6. High-volume copy-imperfection PK regression: every copy-style
        # injector must allocate collision-free synthetic integer PKs. Rates are
        # chosen so each sentinel range (80M dup-entity, 85M dup-webhook,
        # 70M/75M restatement) receives thousands of new PKs — the volume at
        # which the pre-allocator random draw collided with ~99% probability.
        print("\n[6/6] high-volume copy-imperfection PK regression ...")
        if args.spec.resolve() != DEFAULT_SPEC.resolve():
            print("skipped: regression targets a table of the default example spec")
        else:
            target = "erp.sales_order_line"
            spec_data = json.loads(args.spec.read_text(encoding="utf-8"))
            spec_data.setdefault("imperfections", []).extend([
                {"name": "regress_pk_duplicate_entity", "type": "duplicate_entity",
                 "table": target, "rate": 0.3, "stage": "post_derivation"},
                {"name": "regress_pk_duplicate_webhook", "type": "duplicate_webhook",
                 "table": target, "rate": 0.25, "stage": "post_derivation"},
                {"name": "regress_pk_restatement", "type": "restatement_reversal",
                 "table": target, "rate": 0.15, "stage": "post_derivation"},
            ])
            schema_name, _, table_name = target.partition(".")
            table_entry = next(t for t in spec_data["tables"]
                               if t["schema"] == schema_name and t["name"] == table_name)
            pk_column = table_entry["primary_key"][0]
            reg_spec = tmp / "regression_spec.json"
            reg_spec.write_text(json.dumps(spec_data), encoding="utf-8")
            out_dir = tmp / "build_regression"
            # Fixed scale (not args.scale_multiplier) so the volume thresholds hold.
            result = run([sys.executable, str(SCRIPTS / "build_sqlite_ecosystem.py"), str(reg_spec),
                          "--out", str(out_dir), "--scale-multiplier", "0.3", "--force", "--quiet"])
            db_files = list(out_dir.glob("*.db")) if result.returncode == 0 else []
            if result.returncode != 0 or not db_files:
                failures.append("PK regression build failed — synthetic-PK collision is back? "
                                f"(exit {result.returncode}):\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
            else:
                conn = sqlite3.connect(f"file:{db_files[0].as_posix()}?mode=ro", uri=True)
                try:
                    copy_counts = dict(conn.execute(
                        "select imperfection_name, count(*) from meta_imperfection_log "
                        "where imperfection_name like 'regress_pk_%' group by 1"))
                    physical = target.replace(".", "_")
                    pk_dupes = conn.execute(
                        f'select count(*) - count(distinct "{pk_column}") from "{physical}"').fetchone()[0]
                finally:
                    conn.close()
                # restatement inserts two rows (reversal + restated) per sampled PK,
                # one per sentinel range, so it needs double the floor.
                volume_floor = {"regress_pk_duplicate_entity": 3000,
                                "regress_pk_duplicate_webhook": 3000,
                                "regress_pk_restatement": 6000}
                thin = {n: copy_counts.get(n, 0) for n, floor in volume_floor.items()
                        if copy_counts.get(n, 0) < floor}
                if thin:
                    failures.append(f"PK regression volume too low to prove anything: {thin} — "
                                    "raise rates or table size so each stream stays past the "
                                    "birthday-collision threshold of the old allocator")
                elif pk_dupes:
                    failures.append(f"PK regression: {pk_dupes} duplicate values of "
                                    f"{physical}.{pk_column} after copy imperfections")
                else:
                    print(f"PK regression OK: {sum(copy_counts.values())} synthetic-PK copies "
                          f"on {target}, all {pk_column} values unique")
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
    print("SELF-TEST PASSED: spec valid, deterministic across hash seeds, strict validation green, "
          "profiler OK, MCP server battery green, PK regression green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
