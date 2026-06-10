#!/usr/bin/env python3
"""Validate an ecosystem spec JSON before building.

Two layers:
1. Engine preflight (imported from build_sqlite_ecosystem) — structural and
   semantic errors that would fail the build: unknown generators/traits,
   unresolved FK refs, dependency cycles, bad state machines, bad shorthands.
2. Spec lints — documentation and realism gaps that won't fail the build but
   weaken the ecosystem: missing grains/purposes, missing layers, no
   imperfections, fact tables without grains, sensitive data without a
   security model, suspicious distribution parameters.

Diagnostics are collected (not fail-fast) and printed as structured lines:
  ERROR   E_CODE  path  message
  WARNING W_CODE  path  message

Usage:
  python validate_ecosystem_spec.py spec.json [--json results.json]

Exit codes: 0 ok (warnings allowed), 1 errors found, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_sqlite_ecosystem as engine  # noqa: E402

RECOMMENDED_LAYERS = {"source", "staging", "canonical", "xref", "warehouse_fact",
                      "warehouse_dimension", "control", "dq"}
SENSITIVE_CLASSES = {"pii", "phi", "pci", "restricted", "financially_sensitive"}


class Diag:
    def __init__(self, severity: str, code: str, path: str, message: str):
        self.severity, self.code, self.path, self.message = severity, code, path, message

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "path": self.path, "message": self.message}


def lint(spec: dict[str, Any], tables: list) -> list[Diag]:
    diags: list[Diag] = []

    def warn(code: str, path: str, message: str) -> None:
        diags.append(Diag("WARNING", code, path, message))

    if not spec.get("organization", {}).get("name"):
        warn("W_NO_ORG", "/organization/name", "no fictional organization name set")
    if "seed" not in spec:
        warn("W_NO_SEED", "/seed", "no seed declared; builds default to 42 — declare it for clarity")
    if not spec.get("time"):
        warn("W_NO_TIME", "/time", "no time horizon declared; defaults to 2024-01-01..2025-12-31")
    if not spec.get("calendar"):
        warn("W_NO_CALENDAR", "/calendar", "no business calendar; weekday/seasonality shape will use defaults")

    layers = {t.layer for t in tables if t.layer}
    for layer in sorted(RECOMMENDED_LAYERS - layers):
        warn("W_MISSING_LAYER", "/tables", f"no table declares layer '{layer}' — "
             "include it or confirm it's out of scope for this package")

    has_sensitive = False
    for ti, t in enumerate(tables):
        path = f"/tables/{ti}"
        if not t.purpose:
            warn("W_NO_PURPOSE", path, f"{t.key}: missing 'purpose'")
        if ("fact" in t.layer or t.layer == "warehouse_fact") and not t.grain:
            warn("W_NO_GRAIN", path, f"{t.key}: fact table without explicit 'grain'")
        if not t.primary_key:
            warn("W_NO_PK", path, f"{t.key}: missing 'primary_key' (imperfection targeting and "
                 "grain checks need one)")
        if t.source == "generator" and t.layer in {"staging", "canonical", "xref",
                                                   "warehouse_fact", "warehouse_dimension", "mart"}:
            warn("W_LAYER_SHOULD_DERIVE", path,
                 f"{t.key}: layer '{t.layer}' is generator-populated — derive it from source tables "
                 "via a derivation for real lineage instead of parallel-faking it")
        for col in t.columns:
            if str(col.get("classification", "")).lower() in SENSITIVE_CLASSES:
                has_sensitive = True

    if has_sensitive:
        sec = [t for t in tables if t.layer in {"security", "privacy"}
               or str(t.raw.get("schema", "")).lower() in {"security", "privacy"}]
        if not sec:
            warn("W_NO_SECURITY_MODEL", "/tables",
                 "sensitive-classified columns exist but no security/privacy tables are modeled")

    import re as _re
    derivation_targets = set()
    for di, deriv in enumerate(spec.get("derivations", [])):
        sql = deriv.get("sql")
        sql_text = ("\n".join(sql) if isinstance(sql, list) else str(sql or "")).lower()
        for t in tables:
            if t.source != "derivation":
                continue
            # Word-boundary match so 'stg.crm_account' doesn't count a reference
            # to 'stg.crm_account_clean' as populating it.
            for name in (t.key.lower(), t.physical):
                if _re.search(rf"(?<![\w.]){_re.escape(name)}(?![\w])", sql_text):
                    derivation_targets.add(t.key)
                    break
    for ti, t in enumerate(tables):
        if t.source == "derivation" and t.key not in derivation_targets:
            warn("W_DERIVE_NO_SOURCE", f"/tables/{ti}",
                 f"{t.key}: source='derivation' but no derivation SQL references it")

    if not spec.get("imperfections"):
        warn("W_NO_IMPERFECTIONS", "/imperfections",
             "no controlled imperfections — perfectly clean data is the #1 synthetic-data tell")
    if not spec.get("state_machines"):
        warn("W_NO_STATE_MACHINES", "/state_machines",
             "no state machines — statuses without event lifecycles read as random values")
    if not spec.get("controls"):
        warn("W_NO_CONTROLS", "/controls", "no reconciliation controls declared (documentation realism)")
    if not spec.get("dq_rules"):
        warn("W_NO_DQ", "/dq_rules", "no data-quality rules declared (documentation realism)")
    if not spec.get("validation", {}).get("required_views"):
        warn("W_NO_REQUIRED_VIEWS", "/validation/required_views",
             "declare mart/control views here so the database validator gates on them")

    # Distribution parameter sanity.
    for ti, t in enumerate(tables):
        rows_cfg = t.rows_cfg
        if isinstance(rows_cfg, dict) and rows_cfg.get("per_parent") and "max" not in rows_cfg:
            warn("W_NO_CHILD_CAP", f"/tables/{ti}/rows",
                 f"{t.key}: per_parent distribution without 'max' — one hot draw can explode row counts")
        for col in t.columns:
            gen = col.get("gen") or {}
            sigma = gen.get("sigma")
            if sigma is not None and float(sigma) > 2.5:
                warn("W_WILD_SIGMA", f"/tables/{ti}", f"{t.key}.{col.get('name')}: lognormal sigma {sigma} "
                     "is extreme; p99 will be thousands of times the median")
    return diags


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="Path to ecosystem spec JSON")
    parser.add_argument("--json", type=Path, dest="json_out", help="Write diagnostics as JSON")
    args = parser.parse_args(argv)

    if not args.spec.exists():
        print(f"error: spec file not found: {args.spec}", file=sys.stderr)
        return 2

    diags: list[Diag] = []
    tables: list = []
    spec: dict[str, Any] = {}
    try:
        spec = engine.load_spec(args.spec)
    except engine.SpecError as exc:
        diags.append(Diag("ERROR", "E_JSON", "/", str(exc)))

    if spec:
        try:
            tables = engine.preflight(spec)
        except engine.SpecError as exc:
            diags.append(Diag("ERROR", "E_PREFLIGHT", "/", str(exc)))
        # Preflight is fail-fast inside the engine; re-run per-table construction to
        # surface additional independent errors where possible.
        if not tables and isinstance(spec.get("tables"), list):
            for i, raw in enumerate(spec["tables"]):
                try:
                    engine.TableSpec(raw, i, spec)
                except engine.SpecError as exc:
                    message = str(exc)
                    if not any(d.message == message for d in diags):
                        diags.append(Diag("ERROR", "E_TABLE", f"/tables/{i}", message))

    if tables:
        diags.extend(lint(spec, tables))

    errors = [d for d in diags if d.severity == "ERROR"]
    warnings = [d for d in diags if d.severity == "WARNING"]
    for d in diags:
        print(f"{d.severity:7s} {d.code:24s} {d.path:24s} {d.message}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s).")
    if not errors:
        print("Spec is buildable." + (" Address warnings to improve realism." if warnings else ""))

    if args.json_out:
        with args.json_out.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump([d.as_dict() for d in diags], fh, indent=2)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
