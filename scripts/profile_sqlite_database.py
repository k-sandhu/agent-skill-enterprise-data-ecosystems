#!/usr/bin/env python3
"""Profile a built SQLite ecosystem database into a Markdown summary.

Per table: row count, populated-by source, date ranges, null rates, top values
for low-cardinality text columns, and numeric quartiles. Plus build metadata,
imperfection summary, and view row counts.

Usage:
  python profile_sqlite_database.py --db build/org.db [--report profile.md] [--max-tables N]

Exit codes: 0 ok, 2 usage error.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def q1(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def profile_table(conn: sqlite3.Connection, name: str, max_columns: int = 30) -> list[str]:
    lines = [f"### {name}", ""]
    total = q1(conn, f'select count(*) from "{name}"')
    lines.append(f"- Rows: {total:,}")
    if not total:
        lines.append("")
        return lines
    cols = q(conn, f'pragma table_info("{name}")')[:max_columns]
    sample_limit = min(total, 50000)
    col_lines = ["", "| Column | Type | Null % | Distinct | Profile |", "| --- | --- | --- | --- | --- |"]
    for _, col, ctype, *_ in cols:
        nulls = q1(conn, f'select count(*) from (select "{col}" v from "{name}" limit {sample_limit}) where v is null')
        null_pct = 100.0 * nulls / sample_limit
        distinct = q1(conn, f'select count(distinct "{col}") from (select "{col}" from "{name}" limit {sample_limit})')
        profile = ""
        ctype_low = (ctype or "").lower()
        sample_val = q1(conn, f'select "{col}" from "{name}" where "{col}" is not null limit 1')
        looks_date = isinstance(sample_val, str) and len(sample_val) >= 10 and sample_val[4:5] == "-"
        if looks_date:
            lo = q1(conn, f'select min("{col}") from "{name}"')
            hi = q1(conn, f'select max("{col}") from "{name}"')
            profile = f"{str(lo)[:10]} .. {str(hi)[:10]}"
        elif ctype_low in ("integer", "real") and distinct and distinct > 1:
            lo = q1(conn, f'select min("{col}") from "{name}"')
            hi = q1(conn, f'select max("{col}") from "{name}"')
            avg = q1(conn, f'select round(avg("{col}"), 2) from "{name}"')
            profile = f"min {lo}, avg {avg}, max {hi}"
        elif distinct and distinct <= 12:
            tops = q(conn, f'select "{col}", count(*) from "{name}" where "{col}" is not null '
                           f'group by "{col}" order by count(*) desc limit 4')
            profile = ", ".join(f"{v} ({c:,})" for v, c in tops)
        col_lines.append(f"| {col} | {ctype} | {null_pct:.0f}% | {distinct:,} | {profile} |")
    lines.extend(col_lines)
    lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, required=True, help="Path to SQLite database")
    parser.add_argument("--report", type=Path, help="Markdown output path (default: print)")
    parser.add_argument("--max-tables", type=int, default=100, help="Max tables to profile")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    try:
        lines = ["# Database Profile", "", f"- Database: `{args.db}`"]
        build_info = dict(q(conn, "select key, value from meta_build_info")) \
            if q1(conn, "select count(*) from sqlite_master where name='meta_build_info'") else {}
        for key in ("organization", "seed", "as_of_date", "engine_version", "imperfections_logged"):
            if key in build_info:
                lines.append(f"- {key}: {build_info[key]}")
        tables = [r[0] for r in q(conn, "select name from sqlite_master where type='table' "
                                        "and name not like 'sqlite_%' order by name")]
        views = [r[0] for r in q(conn, "select name from sqlite_master where type='view' order by name")]
        total_rows = sum(q1(conn, f'select count(*) from "{t}"') for t in tables)
        lines.append(f"- Tables: {len(tables)} ({total_rows:,} rows) | Views: {len(views)}")
        lines.append("")

        if views:
            lines.append("## Views")
            lines.append("")
            for v in views:
                try:
                    n = q1(conn, f'select count(*) from "{v}"')
                    lines.append(f"- {v}: {n:,} rows")
                except sqlite3.Error as exc:
                    lines.append(f"- {v}: ERROR {exc}")
            lines.append("")

        if q1(conn, "select count(*) from sqlite_master where name='meta_imperfection_log'"):
            lines.append("## Controlled Imperfections")
            lines.append("")
            lines.append("| Imperfection | Type | Table | Rows |")
            lines.append("| --- | --- | --- | --- |")
            for name, itype, table, count in q(
                    conn, "select imperfection_name, imperfection_type, table_name, count(*) "
                          "from meta_imperfection_log group by 1, 2, 3 order by 4 desc"):
                lines.append(f"| {name} | {itype} | {table} | {count:,} |")
            lines.append("")

        lines.append("## Tables")
        lines.append("")
        for t in tables[:args.max_tables]:
            lines.extend(profile_table(conn, t))
    finally:
        conn.close()

    report = "\n".join(lines)
    if args.report:
        with args.report.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(report)
        print(f"Profile written to {args.report}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
