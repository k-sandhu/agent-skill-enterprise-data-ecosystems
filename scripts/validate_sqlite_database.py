#!/usr/bin/env python3
"""Validate a built SQLite ecosystem database against its spec.

Three verdict tiers (no-flake policy: a check that can fire on a correct build
is never critical):

- CRITICAL  -> exit 1. Integrity, missing objects, unexplained FK violations,
               grain duplicates beyond logged imperfections, PII leaks.
- WARNING   -> exit 0 (exit 1 with --strict). Rate drift, unverifiable logged
               imperfections, empty derivations, row-range misses.
- REALISM   -> scored x/y in the report; each is a statistical signature
               (weekday shape, activity skew, duplicate mass, open pipeline,
               id/date correlation, actor concentration).

Usage:
  python validate_sqlite_database.py --db build/org.db --spec ecosystem_spec.json
      [--report validation_report.md] [--json validation_results.json] [--strict]

Exit codes: 0 ok, 1 critical (or warning with --strict), 2 usage error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_sqlite_ecosystem as engine  # noqa: E402

SAFE_EMAIL_SUFFIXES = ("example.com", "example.org", "example.net", ".test", ".invalid")
TEST_CARD_PREFIXES = ("4111", "5555", "4242", "3782", "6011")


class Finding:
    def __init__(self, severity: str, code: str, message: str, detail: str = ""):
        self.severity = severity  # critical | warning | realism_pass | realism_fail | info
        self.code = code
        self.message = message
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "detail": self.detail}


class Validator:
    def __init__(self, conn: sqlite3.Connection, spec: dict[str, Any], tables: list):
        self.conn = conn
        self.spec = spec
        self.tables = tables
        self.by_key = {t.key: t for t in tables}
        self.findings: list[Finding] = []
        self.as_of = str(spec.get("time", {}).get("as_of_date", "2999-12-31"))
        self.imp_log = self._load_imperfection_log()

    # -- helpers -----------------------------------------------------------

    def q(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self.conn.execute(sql, params).fetchall()

    def q1(self, sql: str, params: tuple = ()) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    def add(self, severity: str, code: str, message: str, detail: str = "") -> None:
        self.findings.append(Finding(severity, code, message, detail))

    def table_exists(self, physical: str) -> bool:
        return self.q1("select count(*) from sqlite_master where name = ? and type in ('table','view')",
                       (physical,)) > 0

    def columns_of(self, physical: str) -> list[str]:
        return [r[1] for r in self.q(f'pragma table_info("{physical}")')]

    def _load_imperfection_log(self) -> list[dict[str, Any]]:
        if not self.table_exists("meta_imperfection_log"):
            return []
        rows = self.q("select imperfection_name, imperfection_type, table_name, pk_value, detail "
                      "from meta_imperfection_log")
        return [{"name": r[0], "type": r[1], "table": r[2], "pk": r[3], "detail": r[4]} for r in rows]

    def logged(self, types: tuple, physical: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self.imp_log if e["type"] in types
                and (physical is None or e["table"] == physical)]

    # -- critical checks -----------------------------------------------------

    def check_integrity(self) -> None:
        result = self.q1("pragma integrity_check")
        if result == "ok":
            self.add("info", "I_INTEGRITY", "integrity_check ok")
        else:
            self.add("critical", "C_INTEGRITY", f"integrity_check failed: {result}")

    def check_required_objects(self) -> None:
        missing_tables, missing_cols = [], []
        for t in self.tables:
            if not self.table_exists(t.physical):
                missing_tables.append(t.key)
                continue
            have = set(self.columns_of(t.physical))
            for c in t.column_names:
                if c not in have:
                    missing_cols.append(f"{t.key}.{c}")
        if missing_tables:
            self.add("critical", "C_MISSING_TABLE", f"{len(missing_tables)} spec tables missing from database",
                     ", ".join(missing_tables[:10]))
        if missing_cols:
            self.add("critical", "C_MISSING_COLUMN", f"{len(missing_cols)} spec columns missing",
                     ", ".join(missing_cols[:10]))
        if not missing_tables and not missing_cols:
            self.add("info", "I_OBJECTS", f"all {len(self.tables)} tables and their columns exist")
        for view in self.spec.get("validation", {}).get("required_views", []):
            if not self.table_exists(view):
                self.add("critical", "C_MISSING_VIEW", f"required view '{view}' missing")
            elif self.q1(f'select count(*) from "{view}"') == 0:
                self.add("warning", "W_EMPTY_VIEW", f"required view '{view}' returns zero rows")

    def check_populated(self) -> None:
        for t in self.tables:
            if t.source == "empty" or not self.table_exists(t.physical):
                continue
            wants_rows = t.source in {"derivation", "state_machine"} or t.rows_cfg
            n = self.q1(f'select count(*) from "{t.physical}"')
            if wants_rows and n == 0:
                sev = "critical" if t.source == "generator" else "warning"
                self.add(sev, "C_EMPTY_TABLE" if sev == "critical" else "W_EMPTY_TABLE",
                         f"{t.key} ({t.source}) has zero rows")

    def check_pk_and_grain(self) -> None:
        for t in self.tables:
            if not self.table_exists(t.physical) or not t.primary_key:
                continue
            pk_cols = ", ".join(f'"{c}"' for c in t.primary_key)
            dupes = self.q1(f'select count(*) from (select {pk_cols} from "{t.physical}" '
                            f'group by {pk_cols} having count(*) > 1)')
            if dupes:
                self.add("critical", "C_PK_DUP", f"{t.key}: {dupes} duplicate primary key groups")
            if t.natural_key:
                nk_cols = ", ".join(f'"{c}"' for c in t.natural_key)
                nk_dupes = self.q1(f'select count(*) from (select {nk_cols} from "{t.physical}" '
                                   f'group by {nk_cols} having count(*) > 1)')
                allowed = len(self.logged(("duplicate_entity", "restatement_reversal",
                                           "duplicate_webhook"), t.physical))
                if nk_dupes > allowed:
                    self.add("critical", "C_GRAIN_DUP",
                             f"{t.key}: {nk_dupes} duplicate natural-key groups but only "
                             f"{allowed} logged duplicate imperfections")
                elif nk_dupes:
                    self.add("info", "I_GRAIN_LOGGED",
                             f"{t.key}: {nk_dupes} natural-key duplicates, all covered by the imperfection log")

    def check_foreign_keys(self) -> None:
        violations = self.q("pragma foreign_key_check")
        by_table: dict[str, int] = {}
        for row in violations:
            by_table[row[0]] = by_table.get(row[0], 0) + 1
        if not violations:
            self.add("info", "I_FK", "foreign_key_check returned zero rows")
            return
        for physical, count in sorted(by_table.items()):
            logged = len(self.logged(("orphan_fk",), physical))
            tspec = next((t for t in self.tables if t.physical == physical), None)
            if count <= logged:
                self.add("info", "I_FK_LOGGED",
                         f"{physical}: {count} FK violations, all within {logged} logged orphan_fk injections")
            elif tspec is not None and tspec.source == "derivation":
                self.add("warning", "W_FK_DERIVED",
                         f"{physical}: {count} FK violations in a derived table "
                         f"(propagated from logged source orphans is expected; verify lineage)")
            else:
                self.add("critical", "C_FK_UNEXPLAINED",
                         f"{physical}: {count} FK violations but only {logged} logged orphan_fk injections")

    def check_pii(self) -> None:
        problems = []
        for t in self.tables:
            if not self.table_exists(t.physical):
                continue
            for col in t.column_names:
                low = col.lower()
                if "email" in low:
                    bad = self.q1(f'select count(*) from (select "{col}" v from "{t.physical}" '
                                  f'where "{col}" is not null limit 2000) '
                                  "where v not like '%example.com' and v not like '%example.org' "
                                  "and v not like '%example.net' and v not like '%.test' and v not like '%.invalid'")
                    if bad:
                        problems.append(f"{t.key}.{col}: {bad} emails outside safe fictional domains")
                elif "phone" in low or low == "fax" or low == "mobile":
                    bad = self.q1(f'select count(*) from (select "{col}" v from "{t.physical}" '
                                  f'where "{col}" is not null limit 2000) where v not like \'%555-01%\'')
                    if bad:
                        problems.append(f"{t.key}.{col}: {bad} phones outside the 555-01xx fictional range")
                elif re.search(r"(^|_)(ssn|sin|social_security)($|_)", low):
                    bad = self.q1(f'select count(*) from "{t.physical}" where "{col}" glob \'[0-9][0-9][0-9]*\'')
                    if bad:
                        problems.append(f"{t.key}.{col}: {bad} SSN-shaped values (use surrogate formats)")
                elif re.search(r"(^|_)(card|pan)(_number)?($|_)", low):
                    rows = self.q(f'select "{col}" from "{t.physical}" where "{col}" is not null limit 2000')
                    for (value,) in rows:
                        digits = re.sub(r"\D", "", str(value))
                        if len(digits) >= 15 and not str(value).startswith("*") and \
                                not any(digits.startswith(p) for p in TEST_CARD_PREFIXES):
                            problems.append(f"{t.key}.{col}: full card-like numbers outside test BINs")
                            break
        if problems:
            for p in problems:
                self.add("critical", "C_PII", p)
        else:
            self.add("info", "I_PII", "PII heuristics clean (scoped to email/phone/ssn/card-named columns)")

    # -- warning checks --------------------------------------------------------

    def check_row_counts(self) -> None:
        # meta_table_stats reconciliation: COUNT(*) minus stats must equal the
        # net rows added/removed by logged post-stat imperfections.
        if self.table_exists("meta_table_stats"):
            for physical, stat_count in self.q("select table_name, row_count from meta_table_stats"):
                if not self.table_exists(physical):
                    continue
                actual = self.q1(f'select count(*) from "{physical}"')
                # Each log entry corresponds to exactly one inserted row
                # (restatement_reversal logs the reversal and restated rows separately).
                added = len(self.logged(("duplicate_entity", "duplicate_webhook",
                                         "restatement_reversal"), physical))
                removed = len(self.logged(("missing_xref",), physical))
                expected = stat_count + added - removed
                if actual != expected:
                    self.add("warning", "W_STATS_DRIFT",
                             f"{physical}: count {actual} != stats {stat_count} + logged net {added - removed}")
        multiplier = 1.0
        if self.table_exists("meta_build_info"):
            raw = self.q1("select value from meta_build_info where key = 'scale_multiplier'")
            if raw:
                multiplier = float(raw)
        ranges = self.spec.get("validation", {}).get("expected_row_ranges", {})
        for key, bounds in ranges.items():
            tspec = self.by_key.get(key)
            if tspec is None or not self.table_exists(tspec.physical):
                continue
            # Ranges are authored for multiplier 1.0; scale to the build's multiplier.
            lo, hi = bounds[0] * multiplier * 0.8, bounds[1] * multiplier * 1.2
            n = self.q1(f'select count(*) from "{tspec.physical}"')
            if not (lo <= n <= hi):
                self.add("warning", "W_ROW_RANGE",
                         f"{key}: {n} rows outside expected range [{lo:.0f}, {hi:.0f}] "
                         f"(spec range x multiplier {multiplier})")
            else:
                self.add("info", "I_ROW_RANGE", f"{key}: {n} rows within expected range")

    def check_imperfection_rates(self) -> None:
        for idx, imp in enumerate(self.spec.get("imperfections", [])):
            name = imp.get("name", f"imp_{idx}")
            entries = [e for e in self.imp_log if e["name"] == name]
            tkey = str(imp.get("table", ""))
            tspec = self.by_key.get(tkey)
            if tspec is None or not self.table_exists(tspec.physical):
                continue
            n_rows = self.q1(f'select count(*) from "{tspec.physical}"')
            expected = float(imp.get("rate", 0)) * max(n_rows, 1)
            if expected < 5:
                self.add("info", "I_RATE_SMALL",
                         f"imperfection '{name}': expected count {expected:.1f} too small to rate-check")
                continue
            if not entries:
                self.add("warning", "W_IMP_MISSING", f"imperfection '{name}' produced zero logged entries")
            elif not (0.4 * expected <= len(entries) <= 2.5 * expected):
                self.add("warning", "W_IMP_RATE",
                         f"imperfection '{name}': {len(entries)} logged vs ~{expected:.0f} expected")
            else:
                self.add("info", "I_IMP_RATE", f"imperfection '{name}': {len(entries)} logged (rate plausible)")

    def check_imperfections_observable(self) -> None:
        """Forward probes: sampled logged imperfections must be visible in data."""
        groups: dict[tuple, list[dict[str, Any]]] = {}
        for e in self.imp_log:
            groups.setdefault((e["type"], e["table"]), []).append(e)
        for (itype, physical), entries in sorted(groups.items()):
            if not self.table_exists(physical):
                continue
            tspec = next((t for t in self.tables if t.physical == physical), None)
            if tspec is None or not tspec.primary_key:
                continue
            pk = tspec.primary_key[0]
            sample = entries[:20]
            failures = 0
            for e in sample:
                if itype == "missing_xref":
                    if self.q1(f'select count(*) from "{physical}" where cast("{pk}" as text) = ?',
                               (e["pk"],)):
                        failures += 1  # row should be gone
                else:
                    if not self.q1(f'select count(*) from "{physical}" where cast("{pk}" as text) = ?',
                                   (e["pk"],)):
                        failures += 1  # row should exist
            if failures:
                self.add("warning", "W_IMP_UNOBSERVABLE",
                         f"{itype} on {physical}: {failures}/{len(sample)} logged entries not observable in data")
            else:
                self.add("info", "I_IMP_OBSERVABLE",
                         f"{itype} on {physical}: {len(sample)} sampled log entries verified in data")

    def check_derivations(self) -> None:
        stats = {}
        if self.table_exists("meta_derivation_stats"):
            for name, total in self.q("select derivation_name, sum(rows_affected) "
                                      "from meta_derivation_stats group by derivation_name"):
                stats[name] = total
        for di, deriv in enumerate(self.spec.get("derivations", [])):
            name = deriv.get("name", f"derivation_{di}")
            sql = deriv.get("sql")
            sql_text = "\n".join(sql) if isinstance(sql, list) else str(sql)
            is_view = bool(re.match(r"(?is)^\s*create\s+(temp\s+)?view", sql_text.strip()))
            affected = stats.get(name)
            expect = deriv.get("expect", {})
            if not is_view and affected == 0:
                self.add("warning", "W_DERIVATION_EMPTY", f"derivation '{name}' affected zero rows")
            floor = expect.get("at_least_rows")
            if floor is not None and affected is not None and affected < floor:
                self.add("warning", "W_DERIVATION_FLOOR",
                         f"derivation '{name}': {affected} rows < declared floor {floor}")

    def check_state_machines(self) -> None:
        for mi, machine in enumerate(self.spec.get("state_machines", [])):
            tkey = str(machine.get("table"))
            tspec = self.by_key.get(tkey)
            if tspec is None or not self.table_exists(tspec.physical):
                continue
            status_col = machine.get("status_column", "status")
            states = set(machine.get("states", []))
            rogue = self.q(f'select distinct "{status_col}" from "{tspec.physical}" '
                           f'where "{status_col}" is not null')
            bad = [r[0] for r in rogue if r[0] not in states]
            if bad:
                self.add("critical", "C_ROGUE_STATUS",
                         f"{tkey}.{status_col} contains values outside declared states: {bad[:5]}")
            terminal_sources = {t.get("from") for t in machine.get("transitions", [])}
            non_terminal = [s for s in states if s in terminal_sources]
            if non_terminal:
                open_share = self.q1(
                    f'select 1.0 * sum(case when "{status_col}" in ({", ".join(repr(s) for s in non_terminal)}) '
                    f'then 1 else 0 end) / count(*) from "{tspec.physical}"') or 0
                if open_share == 0:
                    self.add("warning", "W_NO_OPEN_PIPELINE",
                             f"{tkey}: every entity reached a terminal state — a real as-of snapshot has open items")
            history = machine.get("history_table")
            hspec = self.by_key.get(str(history)) if history else None
            if hspec is not None and self.table_exists(hspec.physical):
                cols = hspec.column_names
                bad_order = self.q1(
                    f'select count(*) from (select "{cols[0]}" eid, "{cols[3]}" t, '
                    f'lag("{cols[3]}") over (partition by "{cols[0]}" order by "{cols[1]}") prev '
                    f'from "{hspec.physical}") where prev is not null and t < prev')
                allowed = len(self.logged(("out_of_order_events",), hspec.physical))
                if bad_order > allowed:
                    self.add("warning", "W_EVENT_ORDER",
                             f"{history}: {bad_order} out-of-order events vs {allowed} logged injections")

    def check_dates(self) -> None:
        for t in self.tables:
            if not self.table_exists(t.physical):
                continue
            for col in t.column_names:
                if col in ("created_at", "updated_at", "ingested_at", "source_updated_at"):
                    late_logged = len(self.logged(("late_arrival",), t.physical))
                    future = self.q1(f'select count(*) from "{t.physical}" '
                                     f'where "{col}" > ?', (self.as_of + " 23:59:59",))
                    if future > late_logged:
                        self.add("warning", "W_FUTURE_DATES",
                                 f"{t.key}.{col}: {future} values beyond as_of "
                                 f"({late_logged} logged late arrivals)")
            if "created_at" in t.column_names and "updated_at" in t.column_names:
                bad = self.q1(f'select count(*) from "{t.physical}" '
                              'where updated_at is not null and created_at is not null and updated_at < created_at')
                if bad:
                    self.add("warning", "W_UPDATED_BEFORE_CREATED",
                             f"{t.key}: {bad} rows with updated_at < created_at")

    # -- realism scorecard -------------------------------------------------------

    def realism(self, code: str, ok: bool, message: str) -> None:
        self.add("realism_pass" if ok else "realism_fail", code, message)

    def check_realism(self) -> None:
        cal = self.spec.get("calendar", {})
        weights = cal.get("weekday_weights")
        # 1. Weekday shape on high-volume calendar-driven date columns.
        if weights:
            expected_weekend = (weights[5] + weights[6]) / sum(weights)
            for t in self.tables:
                if t.source != "generator" or not self.table_exists(t.physical):
                    continue
                date_cols = [c["name"] for c in t.columns
                             if (c.get("gen") or {}).get("type") == "date" and not (c.get("gen") or {}).get("sorted")]
                if not date_cols:
                    continue
                n = self.q1(f'select count(*) from "{t.physical}"')
                if n < 2000:
                    continue
                col = date_cols[0]
                weekend = self.q1(f'select 1.0 * sum(case when strftime(\'%w\', "{col}") in (\'0\',\'6\') '
                                  f'then 1 else 0 end) / count(*) from "{t.physical}" where "{col}" is not null') or 0
                ok = weekend <= max(expected_weekend * 2.5, 0.08)
                self.realism("R_WEEKDAY", ok,
                             f"{t.key}.{col}: weekend share {weekend:.1%} vs configured ~{expected_weekend:.1%}")
        # 2. Activity skew: zipf fk columns concentrate volume.
        for t in self.tables:
            if not self.table_exists(t.physical):
                continue
            for c in t.columns:
                gen = c.get("gen") or {}
                if gen.get("type") == "fk" and gen.get("weighting") == "zipf":
                    col = c["name"]
                    total = self.q1(f'select count(*) from "{t.physical}" where "{col}" is not null')
                    if not total or total < 1000:
                        continue
                    distinct = self.q1(f'select count(distinct "{col}") from "{t.physical}"')
                    top_n = max(1, distinct // 10)
                    top_share = self.q1(
                        f'select 1.0 * sum(c) / {total} from (select count(*) c from "{t.physical}" '
                        f'where "{col}" is not null group by "{col}" order by c desc limit {top_n})') or 0
                    self.realism("R_SKEW", top_share >= 0.2,
                                 f"{t.key}.{col}: top-decile parents carry {top_share:.1%} of rows")
        # 3. Duplicate mass on money expression columns (price quantization).
        for t in self.tables:
            if t.source != "generator" or not self.table_exists(t.physical):
                continue
            for c in t.columns:
                gen = c.get("gen") or {}
                if gen.get("type") == "expression" and str(c.get("type", "")).lower() == "decimal":
                    col = c["name"]
                    total = self.q1(f'select count(*) from "{t.physical}" where "{col}" is not null')
                    if not total or total < 2000:
                        continue
                    top_share = self.q1(
                        f'select 1.0 * sum(c) / {total} from (select count(*) c from "{t.physical}" '
                        f'where "{col}" is not null group by "{col}" order by c desc limit 20)') or 0
                    self.realism("R_DUP_MASS", top_share >= 0.03,
                                 f"{t.key}.{col}: top-20 exact values carry {top_share:.1%} of rows "
                                 "(real amount columns repeat)")
        # 4. id/date correlation on sorted columns.
        for t in self.tables:
            if t.source != "generator" or not self.table_exists(t.physical) or len(t.primary_key) != 1:
                continue
            sorted_cols = [c["name"] for c in t.columns if (c.get("gen") or {}).get("sorted")]
            if not sorted_cols:
                continue
            pk, col = t.primary_key[0], sorted_cols[0]
            disorder = self.q1(
                f'select count(*) from (select "{col}" v, lag("{col}") over (order by "{pk}") prev '
                f'from "{t.physical}") where prev is not null and v < prev')
            n = self.q1(f'select count(*) from "{t.physical}"')
            dup_allow = len(self.logged(("duplicate_entity",), t.physical)) + 2
            self.realism("R_ID_DATE", disorder <= dup_allow,
                         f"{t.key}: {disorder} of {n} ids out of {col} order (sequence/date correlation)")
        # 5. Actor concentration.
        for t in self.tables:
            if t.source != "generator" or not self.table_exists(t.physical):
                continue
            if "created_by" in t.column_names:
                n = self.q1(f'select count(*) from "{t.physical}"')
                if n < 300:
                    continue
                top = self.q1(f'select count(*) from "{t.physical}" group by created_by '
                              'order by count(*) desc limit 1') or 0
                distinct = self.q1(f'select count(distinct created_by) from "{t.physical}"') or 1
                self.realism("R_ACTOR", top >= 2.0 * n / distinct,
                             f"{t.key}.created_by: top actor {top}/{n} rows across {distinct} actors")
        # 6. Business-hours clustering on human timestamps.
        hours = cal.get("business_hours", [8, 18])
        for t in self.tables:
            if t.source != "generator" or not self.table_exists(t.physical):
                continue
            ts_cols = [c["name"] for c in t.columns
                       if (c.get("gen") or {}).get("type") == "timestamp"
                       and (c.get("gen") or {}).get("business_hours", True) is not False]
            if not ts_cols:
                continue
            n = self.q1(f'select count(*) from "{t.physical}"')
            if n < 500:
                continue
            col = ts_cols[0]
            in_hours = self.q1(
                f'select 1.0 * sum(case when cast(strftime(\'%H\', "{col}") as integer) '
                f'between {int(hours[0])} and {int(hours[1]) - 1} then 1 else 0 end) / count(*) '
                f'from "{t.physical}" where "{col}" is not null') or 0
            self.realism("R_BIZ_HOURS", in_hours >= 0.6,
                         f"{t.key}.{col}: {in_hours:.0%} of timestamps inside business hours")

    # -- run --------------------------------------------------------------------

    def run(self) -> None:
        self.check_integrity()
        self.check_required_objects()
        self.check_populated()
        self.check_pk_and_grain()
        self.check_foreign_keys()
        self.check_pii()
        self.check_row_counts()
        self.check_imperfection_rates()
        self.check_imperfections_observable()
        self.check_derivations()
        self.check_state_machines()
        self.check_dates()
        self.check_realism()


def render_report(validator: Validator, db_path: str) -> str:
    f = validator.findings
    crit = [x for x in f if x.severity == "critical"]
    warn = [x for x in f if x.severity == "warning"]
    rpass = [x for x in f if x.severity == "realism_pass"]
    rfail = [x for x in f if x.severity == "realism_fail"]
    info = [x for x in f if x.severity == "info"]
    build_info = {}
    if validator.table_exists("meta_build_info"):
        build_info = dict(validator.q("select key, value from meta_build_info"))

    lines = ["# Ecosystem Validation Report", ""]
    lines.append(f"- Database: `{db_path}`")
    for key in ("organization", "seed", "scale_multiplier", "as_of_date", "engine_version", "built_at_utc"):
        if key in build_info:
            lines.append(f"- {key}: {build_info[key]}")
    lines.append("")
    verdict = "FAIL (critical findings)" if crit else "PASS"
    lines.append(f"## Verdict: {verdict}")
    lines.append(f"- Critical: {len(crit)}  |  Warnings: {len(warn)}  |  "
                 f"Realism score: {len(rpass)}/{len(rpass) + len(rfail)}")
    lines.append("")
    for title, items in (("Critical findings", crit), ("Warnings", warn),
                         ("Realism signatures — failed", rfail)):
        lines.append(f"## {title}")
        lines.append("")
        if items:
            for x in items:
                lines.append(f"- **{x.code}** {x.message}" + (f" — {x.detail}" if x.detail else ""))
        else:
            lines.append("- none")
        lines.append("")
    lines.append("## Realism signatures — passed")
    lines.append("")
    for x in rpass:
        lines.append(f"- {x.code}: {x.message}")
    lines.append("")
    lines.append("## Informational")
    lines.append("")
    for x in info:
        lines.append(f"- {x.code}: {x.message}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, required=True, help="Path to built SQLite database")
    parser.add_argument("--spec", type=Path, required=True, help="Path to ecosystem spec JSON")
    parser.add_argument("--report", type=Path, help="Markdown report output path")
    parser.add_argument("--json", type=Path, dest="json_out", help="JSON results output path")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on warnings too (used by self-test)")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 2
    if not args.spec.exists():
        print(f"error: spec not found: {args.spec}", file=sys.stderr)
        return 2

    try:
        spec = engine.load_spec(args.spec)
        tables = engine.preflight(spec)
    except engine.SpecError as exc:
        print(f"SPEC ERROR: {exc}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    try:
        validator = Validator(conn, spec, tables)
        validator.run()
        report = render_report(validator, str(args.db))
    finally:
        conn.close()
    if args.report:
        with args.report.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(report)
    if args.json_out:
        with args.json_out.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump({"db": str(args.db), "findings": [x.as_dict() for x in validator.findings]},
                      fh, indent=2)
    print(report)

    has_critical = any(x.severity == "critical" for x in validator.findings)
    has_warning = any(x.severity in ("warning", "realism_fail") for x in validator.findings)
    if has_critical:
        return 1
    if args.strict and has_warning:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
