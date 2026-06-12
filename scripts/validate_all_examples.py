#!/usr/bin/env python3
"""Build and strict-validate every worked example under examples/.

For each examples/*/ecosystem_spec.json:
1. validate_ecosystem_spec.py must exit 0 (zero errors).
2. build_sqlite_ecosystem.py builds it into a temp directory.
3. validate_sqlite_database.py --strict must exit 0 (zero critical, zero
   warnings, full realism score).
4. generate_mcp_server.py emits the MCP package and test_mcp_server.run_smoke
   confirms the server initializes, lists 11 tools, and answers a query.

Usage:
  python scripts/validate_all_examples.py [--scale-multiplier 0.3] [--only saas,banking] [--keep]

Exit codes: 0 all examples green, 1 any failure, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import test_mcp_server

SCRIPTS = Path(__file__).resolve().parent
EXAMPLES = SCRIPTS.parent / "examples"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                          env=dict(os.environ))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale-multiplier", type=float, default=0.3,
                        help="Build scale for validation runs (default 0.3 for speed)")
    parser.add_argument("--only", help="Comma-separated example dir names to limit the run")
    parser.add_argument("--keep", action="store_true", help="Keep the temp build directory")
    args = parser.parse_args(argv)

    specs = sorted(EXAMPLES.glob("*/ecosystem_spec.json"))
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        specs = [s for s in specs if s.parent.name in wanted]
    if not specs:
        print("error: no examples found", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="ecosystem_examples_"))
    results: list[tuple[str, bool, str]] = []
    try:
        for spec in specs:
            name = spec.parent.name
            t0 = time.time()
            print(f"=== {name} ===")

            proc = run([sys.executable, str(SCRIPTS / "validate_ecosystem_spec.py"), str(spec)])
            if proc.returncode != 0:
                results.append((name, False, "spec validation failed:\n" + proc.stdout[-2000:]))
                print("  SPEC FAIL")
                continue

            out_dir = tmp / name
            proc = run([sys.executable, str(SCRIPTS / "build_sqlite_ecosystem.py"), str(spec),
                        "--out", str(out_dir), "--scale-multiplier", str(args.scale_multiplier),
                        "--force", "--quiet"])
            if proc.returncode != 0:
                results.append((name, False, "build failed:\n" + (proc.stderr or proc.stdout)[-2000:]))
                print("  BUILD FAIL")
                continue
            db_files = list(out_dir.glob("*.db"))
            if not db_files:
                results.append((name, False, f"no .db produced in {out_dir}"))
                print("  BUILD FAIL (no db)")
                continue

            proc = run([sys.executable, str(SCRIPTS / "validate_sqlite_database.py"),
                        "--db", str(db_files[0]), "--spec", str(spec), "--strict"])
            elapsed = time.time() - t0
            if proc.returncode != 0:
                findings = "\n".join(line for line in proc.stdout.splitlines()
                                     if line.startswith("- **"))
                results.append((name, False, f"strict validation failed:\n{findings[-2000:]}"))
                print(f"  STRICT FAIL ({elapsed:.0f}s)")
            else:
                # Generate the read-only MCP server package and smoke-test it.
                gen = run([sys.executable, str(SCRIPTS / "generate_mcp_server.py"), str(spec),
                           "--build", str(out_dir), "--force", "--quiet"])
                if gen.returncode != 0:
                    results.append((name, False, "MCP generation failed:\n"
                                    + (gen.stderr or gen.stdout)[-2000:]))
                    print("  MCP GEN FAIL")
                    continue
                smoke = test_mcp_server.run_smoke(out_dir)
                if smoke:
                    results.append((name, False, "MCP smoke failed:\n  " + "\n  ".join(smoke)))
                    print("  MCP SMOKE FAIL")
                    continue
                summary = json.loads((out_dir / "build_summary.json").read_text(encoding="utf-8"))
                score = next((line for line in proc.stdout.splitlines() if "Realism score" in line), "")
                results.append((name, True, f"{summary['total_rows']:,} rows"))
                print(f"  PASS ({elapsed:.0f}s, {summary['total_rows']:,} rows){score and ' | ' + score.strip('- ')}")
    finally:
        if args.keep:
            print(f"Keeping workspace: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    failures = [r for r in results if not r[1]]
    print()
    print(f"{len(results) - len(failures)}/{len(results)} examples green "
          f"(multiplier {args.scale_multiplier}).")
    for name, _, detail in failures:
        print(f"\nFAILED {name}:\n{detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
