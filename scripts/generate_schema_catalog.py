#!/usr/bin/env python3
"""Generate a Markdown schema catalog from an enterprise ecosystem JSON spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_spec(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def table_name(table: dict[str, Any]) -> str:
    schema = table.get("schema")
    name = table.get("name", "unknown_table")
    return f"{schema}.{name}" if schema else name


def render_catalog(spec: dict[str, Any]) -> str:
    org = spec.get("organization", {})
    title = org.get("name") or spec.get("name") or "Enterprise Data Ecosystem"
    lines: list[str] = [f"# {title} Schema Catalog", ""]

    if org:
        lines.extend(
            [
                "## Organization",
                "",
                f"- Archetype: {org.get('archetype', 'unspecified')}",
                f"- Industry: {org.get('industry', 'unspecified')}",
                f"- Platform: {spec.get('platform', 'unspecified')}",
                "",
            ]
        )

    lines.extend(
        [
            "## Tables",
            "",
            "| Table | Layer | Domain | Purpose | Grain | Primary Key | Sensitivity | Owner |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for table in spec.get("tables", []):
        lines.append(
            "| {table} | {layer} | {domain} | {purpose} | {grain} | {pk} | {sensitivity} | {owner} |".format(
                table=table_name(table),
                layer=table.get("layer", ""),
                domain=table.get("domain", ""),
                purpose=table.get("purpose", ""),
                grain=table.get("grain", ""),
                pk=", ".join(table.get("primary_key", [])) if isinstance(table.get("primary_key"), list) else table.get("primary_key", ""),
                sensitivity=table.get("sensitivity", ""),
                owner=table.get("owner", ""),
            )
        )

    lines.extend(["", "## Columns", ""])
    for table in spec.get("tables", []):
        lines.extend([f"### {table_name(table)}", ""])
        columns = table.get("columns", [])
        if not columns:
            lines.extend(["No columns supplied.", ""])
            continue
        lines.extend(
            [
                "| Column | Type | Nullable | Description | Classification |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for column in columns:
            lines.append(
                "| {name} | {type} | {nullable} | {description} | {classification} |".format(
                    name=column.get("name", ""),
                    type=column.get("type", ""),
                    nullable=str(column.get("nullable", True)).lower(),
                    description=column.get("description", ""),
                    classification=column.get("classification", ""),
                )
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="Path to ecosystem JSON spec")
    parser.add_argument("-o", "--output", type=Path, help="Output Markdown path")
    args = parser.parse_args()

    rendered = render_catalog(load_spec(args.spec))
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
