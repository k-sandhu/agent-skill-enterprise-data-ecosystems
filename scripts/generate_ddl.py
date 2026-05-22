#!/usr/bin/env python3
"""Generate simple SQL DDL from an enterprise ecosystem JSON spec."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SUPPORTED_PLATFORMS = {"postgresql", "snowflake", "bigquery", "sqlserver", "databricks", "sqlite"}


TYPE_MAP = {
    "postgresql": {
        "string": "text",
        "integer": "integer",
        "bigint": "bigint",
        "decimal": "numeric(18,2)",
        "boolean": "boolean",
        "date": "date",
        "timestamp": "timestamp",
        "json": "jsonb",
    },
    "snowflake": {
        "string": "varchar",
        "integer": "number(38,0)",
        "bigint": "number(38,0)",
        "decimal": "number(18,2)",
        "boolean": "boolean",
        "date": "date",
        "timestamp": "timestamp_ntz",
        "json": "variant",
    },
    "bigquery": {
        "string": "string",
        "integer": "int64",
        "bigint": "int64",
        "decimal": "numeric",
        "boolean": "bool",
        "date": "date",
        "timestamp": "timestamp",
        "json": "json",
    },
    "sqlserver": {
        "string": "nvarchar(max)",
        "integer": "int",
        "bigint": "bigint",
        "decimal": "decimal(18,2)",
        "boolean": "bit",
        "date": "date",
        "timestamp": "datetime2",
        "json": "nvarchar(max)",
    },
    "databricks": {
        "string": "string",
        "integer": "int",
        "bigint": "bigint",
        "decimal": "decimal(18,2)",
        "boolean": "boolean",
        "date": "date",
        "timestamp": "timestamp",
        "json": "string",
    },
    "sqlite": {
        "string": "text",
        "integer": "integer",
        "bigint": "integer",
        "decimal": "real",
        "boolean": "integer",
        "date": "text",
        "timestamp": "text",
        "json": "text",
    },
}


def load_spec(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def normalize_platform(platform: str | None) -> str:
    value = (platform or "postgresql").lower()
    aliases = {"postgres": "postgresql", "postgresql": "postgresql", "sql_server": "sqlserver", "sql server": "sqlserver"}
    value = aliases.get(value, value)
    if value not in SUPPORTED_PLATFORMS:
        raise SystemExit(f"Unsupported platform '{platform}'. Supported: {', '.join(sorted(SUPPORTED_PLATFORMS))}")
    return value


def safe_identifier(identifier: str, platform: str) -> str:
    if not identifier:
        return "unnamed"
    if platform == "bigquery":
        return f"`{identifier}`"
    if platform == "sqlserver":
        return f"[{identifier}]"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
        return identifier
    return '"' + identifier.replace('"', '""') + '"'


def sqlite_identifier(table: dict[str, Any]) -> str:
    schema = table.get("schema")
    name = table.get("name", "unknown_table")
    raw_name = f"{schema}_{name}" if schema else name
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", raw_name)
    if not re.match(r"^[A-Za-z_]", normalized):
        normalized = f"_{normalized}"
    return normalized.lower()


def column_type(column: dict[str, Any], platform: str) -> str:
    raw_type = str(column.get("type", "string")).lower()
    return TYPE_MAP[platform].get(raw_type, column.get("type", "text"))


def qualified_name(table: dict[str, Any], platform: str) -> str:
    schema = table.get("schema")
    name = table.get("name", "unknown_table")
    if platform == "sqlite":
        return safe_identifier(sqlite_identifier(table), platform)
    if schema and platform not in {"sqlite"}:
        return f"{safe_identifier(schema, platform)}.{safe_identifier(name, platform)}"
    return safe_identifier(name, platform)


def render_ddl(spec: dict[str, Any], platform: str) -> str:
    statements: list[str] = []
    schemas = sorted({table.get("schema") for table in spec.get("tables", []) if table.get("schema")})

    if platform == "sqlite":
        statements.append("pragma foreign_keys = on;")
        statements.append("")

    if platform not in {"sqlite", "bigquery"}:
        for schema in schemas:
            statements.append(f"create schema if not exists {safe_identifier(schema, platform)};")
        if schemas:
            statements.append("")

    for table in spec.get("tables", []):
        column_lines: list[str] = []
        for column in table.get("columns", []):
            nullable = "" if column.get("nullable", True) else " not null"
            column_lines.append(f"  {safe_identifier(column.get('name', 'unnamed_column'), platform)} {column_type(column, platform)}{nullable}")

        primary_key = table.get("primary_key")
        if primary_key and platform not in {"bigquery"}:
            pk_columns = primary_key if isinstance(primary_key, list) else [primary_key]
            rendered_pk = ", ".join(safe_identifier(col, platform) for col in pk_columns)
            column_lines.append(f"  primary key ({rendered_pk})")

        if not column_lines:
            column_lines.append("  row_id integer")

        statements.append(f"create table {qualified_name(table, platform)} (\n" + ",\n".join(column_lines) + "\n);")
        statements.append("")

    return "\n".join(statements).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="Path to ecosystem JSON spec")
    parser.add_argument("-p", "--platform", help="DDL platform; defaults to spec.platform or postgresql")
    parser.add_argument("-o", "--output", type=Path, help="Output SQL path")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    platform = normalize_platform(args.platform or spec.get("platform"))
    rendered = render_ddl(spec, platform)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
