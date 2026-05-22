#!/usr/bin/env python3
"""Validate a realistic enterprise data ecosystem JSON spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


IMPORTANT_LAYERS = {"source", "canonical", "xref", "warehouse_fact", "warehouse_dimension", "mart", "control", "dq"}
SENSITIVE_CLASSES = {"pii", "phi", "pci", "restricted", "financially_sensitive"}


def load_spec(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def table_name(table: dict[str, Any]) -> str:
    schema = table.get("schema")
    name = table.get("name", "unknown_table")
    return f"{schema}.{name}" if schema else name


def normalized_layer(table: dict[str, Any]) -> str:
    return str(table.get("layer", "")).lower().replace("-", "_").replace(" ", "_")


def validate(spec: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    tables = spec.get("tables", [])
    if not tables:
        return ["Spec has no tables."]

    layers = {normalized_layer(table) for table in tables}
    for layer in sorted(IMPORTANT_LAYERS - layers):
        warnings.append(f"Missing recommended layer: {layer}.")

    for table in tables:
        name = table_name(table)
        layer = normalized_layer(table)
        if not table.get("purpose"):
            warnings.append(f"{name} is missing purpose.")
        if ("fact" in layer or layer == "warehouse_fact") and not table.get("grain"):
            warnings.append(f"{name} is a fact-like table without explicit grain.")
        if not table.get("primary_key"):
            warnings.append(f"{name} is missing primary_key.")
        if layer in {"canonical", "mdm"} and not any(col.get("name") in {"effective_start_date", "valid_from"} for col in table.get("columns", [])):
            warnings.append(f"{name} is canonical/MDM but lacks effective dating columns.")

    has_sensitive = False
    for table in tables:
        for column in table.get("columns", []):
            classification = str(column.get("classification", "")).lower()
            if classification in SENSITIVE_CLASSES:
                has_sensitive = True

    if has_sensitive:
        security_tables = [table for table in tables if normalized_layer(table) in {"security", "privacy"} or str(table.get("schema", "")).lower() in {"security", "privacy"}]
        if not security_tables:
            warnings.append("Sensitive columns exist but no security/privacy tables are modeled.")

    if not spec.get("dataflows"):
        warnings.append("Spec has no dataflows.")
    if not spec.get("controls"):
        warnings.append("Spec has no controls/reconciliation rules.")
    if not spec.get("dq_rules"):
        warnings.append("Spec has no data-quality rules.")
    if not spec.get("imperfections"):
        warnings.append("Spec has no controlled imperfections.")

    xref_tables = [table for table in tables if normalized_layer(table) == "xref" or str(table.get("schema", "")).lower() == "xref"]
    canonical_tables = [table for table in tables if normalized_layer(table) == "canonical" or str(table.get("schema", "")).lower() in {"core", "canonical"}]
    if canonical_tables and not xref_tables:
        warnings.append("Canonical tables exist but no xref/source identifier tables are modeled.")

    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="Path to ecosystem JSON spec")
    args = parser.parse_args()

    warnings = validate(load_spec(args.spec))
    if warnings:
        print("Validation warnings:")
        for warning in warnings:
            print(f"- {warning}")
        raise SystemExit(1)

    print("Validation passed.")


if __name__ == "__main__":
    main()
