#!/usr/bin/env python3
"""Generate a synthetic data seed plan from an enterprise ecosystem JSON spec."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_LAYER_ORDER = [
    "reference",
    "app",
    "party",
    "legal",
    "geo",
    "source",
    "raw",
    "staging",
    "canonical",
    "xref",
    "mdm",
    "operational",
    "event",
    "transaction",
    "balance",
    "warehouse_dimension",
    "warehouse_fact",
    "mart",
    "semantic",
    "control",
    "dq",
    "workflow",
    "audit",
    "document",
    "security",
    "privacy",
    "integration",
    "manual",
    "ml",
]


def load_spec(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def table_name(table: dict[str, Any]) -> str:
    schema = table.get("schema")
    name = table.get("name", "unknown_table")
    return f"{schema}.{name}" if schema else name


def layer_rank(layer: str) -> int:
    normalized = (layer or "").lower()
    if normalized in DEFAULT_LAYER_ORDER:
        return DEFAULT_LAYER_ORDER.index(normalized)
    for index, known in enumerate(DEFAULT_LAYER_ORDER):
        if known in normalized:
            return index
    return len(DEFAULT_LAYER_ORDER)


def expected_rows(table: dict[str, Any], scale: str) -> str:
    if table.get("expected_row_count"):
        return str(table["expected_row_count"])
    layer = str(table.get("layer", "")).lower()
    if "dimension" in layer or layer in {"reference", "app", "semantic"}:
        return {"small": "10-500", "medium": "100-5,000", "large": "1,000-50,000"}.get(scale, "100-5,000")
    if "fact" in layer or layer in {"event", "transaction", "raw", "staging"}:
        return {"small": "1,000-50,000", "medium": "50,000-5,000,000", "large": "5,000,000+"}.get(scale, "50,000-5,000,000")
    return {"small": "100-5,000", "medium": "5,000-250,000", "large": "250,000+"}.get(scale, "5,000-250,000")


def render_seed_plan(spec: dict[str, Any], scale: str) -> str:
    org = spec.get("organization", {})
    title = org.get("name") or spec.get("name") or "Enterprise Data Ecosystem"
    tables = sorted(spec.get("tables", []), key=lambda t: (layer_rank(str(t.get("layer", ""))), table_name(t)))
    by_layer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for table in tables:
        by_layer[str(table.get("layer", "unspecified"))].append(table)

    lines = [f"# {title} Synthetic Data Seed Plan", "", f"Scale: {scale}", ""]
    lines.extend(
        [
            "## Generation Sequence",
            "",
            "| Step | Layer | Tables | Row Count Guidance |",
            "| --- | --- | --- | --- |",
        ]
    )

    step = 1
    for layer in sorted(by_layer, key=layer_rank):
        names = ", ".join(table_name(table) for table in by_layer[layer])
        counts = "; ".join(f"{table_name(table)}: {expected_rows(table, scale)}" for table in by_layer[layer])
        lines.append(f"| {step} | {layer} | {names} | {counts} |")
        step += 1

    lines.extend(["", "## State Machines", ""])
    state_machines = spec.get("state_machines", [])
    if state_machines:
        for machine in state_machines:
            lines.append(f"- {machine.get('name', 'Unnamed')}: " + " -> ".join(machine.get("states", [])))
    else:
        lines.append("- Define state transitions for each operational flow before generating statuses.")

    lines.extend(["", "## Controlled Imperfections", ""])
    imperfections = spec.get("imperfections", [])
    if imperfections:
        for item in imperfections:
            if isinstance(item, dict):
                lines.append(f"- {item.get('name', 'Imperfection')}: {item.get('rate', 'rate unspecified')} in {item.get('dataset', 'dataset unspecified')}; {item.get('scenario', '')}")
            else:
                lines.append(f"- {item}")
    else:
        lines.append("- Add missing mappings, late records, duplicate records, manual overrides, and reconciliation breaks appropriate to realism level.")

    lines.extend(["", "## Validation", ""])
    lines.extend(
        [
            "- Validate primary and foreign keys.",
            "- Validate state transition order.",
            "- Validate roll-forward balances where applicable.",
            "- Validate source-to-canonical crosswalk coverage.",
            "- Validate expected DQ failures and reconciliation breaks are traceable.",
            "- Validate sensitive fields are fictional, classified, and masked where required.",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="Path to ecosystem JSON spec")
    parser.add_argument("--scale", choices=["small", "medium", "large"], default="medium")
    parser.add_argument("-o", "--output", type=Path, help="Output Markdown path")
    args = parser.parse_args()

    rendered = render_seed_plan(load_spec(args.spec), args.scale)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
