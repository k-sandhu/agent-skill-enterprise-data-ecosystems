#!/usr/bin/env python3
"""Read-only MCP server over a built enterprise data ecosystem.

This module is copied verbatim into ``<build>/mcp/server.py`` by
``scripts/generate_mcp_server.py``. It is intentionally self-contained:

  * Python 3.9+ standard library only -- no ``mcp``/FastMCP SDK, no third-party
    packages, no network access of any kind.
  * Transport is stdio: newline-delimited JSON-RPC 2.0. stdout carries protocol
    bytes exclusively; all logging goes to stderr.
  * Strictly read-only. Defense in depth: a read-only SQLite URI, a
    deny-by-default authorizer, statement vetting, row/byte caps, and a
    per-call query timeout. There are no write tools.

Everything ecosystem-specific is read from ``mcp_manifest.json`` (next to this
file) plus the SQLite database it points at. The database and the documentation
artifacts are SYNTHETIC and FICTIONAL -- see the disclaimer in the manifest.

Run ``python server.py --help`` for the CLI. See references/mcp-server.md in the
agent-skill-enterprise-data-ecosystems repository for the full protocol, tool,
and safety documentation.

Exit codes: 0 clean shutdown (stdin EOF); 2 usage error (missing manifest/db).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC error codes used by this server.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
RESOURCE_NOT_FOUND = -32002

# SQLite authorizer action codes, resolved with the same forward/back-compatible
# getattr pattern the engine uses in build_sqlite_ecosystem.py. The numeric
# fallbacks are the stable values from the SQLite C API.
SQLITE_OK = getattr(sqlite3, "SQLITE_OK", 0)
SQLITE_DENY = getattr(sqlite3, "SQLITE_DENY", 1)
SQLITE_IGNORE = getattr(sqlite3, "SQLITE_IGNORE", 2)
_ALLOWED_ACTIONS = {
    getattr(sqlite3, "SQLITE_SELECT", 21),
    getattr(sqlite3, "SQLITE_READ", 20),
    getattr(sqlite3, "SQLITE_FUNCTION", 31),
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}

_MISSING = object()


class ToolError(Exception):
    """A tool-level failure that becomes ``isError: true`` content, not a
    JSON-RPC protocol error. The server loop never crashes on one of these."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Make a SQLite cell JSON-serializable. Only BLOBs need help; everything
    else (NULL/int/float/str) is already valid JSON."""
    if isinstance(value, bytes):
        return "base64:" + base64.b64encode(value).decode("ascii")
    return value


def _strip_leading_sql_comments(sql: str) -> str:
    """Remove leading whitespace plus ``--`` line comments and ``/* */`` block
    comments so the first real keyword of a statement can be inspected."""
    text = sql
    while True:
        stripped = text.lstrip()
        if stripped.startswith("--"):
            newline = stripped.find("\n")
            text = "" if newline == -1 else stripped[newline + 1:]
            continue
        if stripped.startswith("/*"):
            end = stripped.find("*/")
            text = "" if end == -1 else stripped[end + 2:]
            continue
        return stripped


def _first_statement_and_rest(sql: str) -> tuple[str, str]:
    """Split ``sql`` after its first complete statement using SQLite's own
    lexer (``complete_statement`` understands string literals and comments, so
    a ``;`` inside a quoted string does not end the statement). Returns
    ``(first_statement, remainder)``."""
    ensured = sql if sql.rstrip().endswith(";") else sql + ";"
    buffer = ""
    for index, char in enumerate(ensured):
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            return buffer, ensured[index + 1:]
    return ensured, ""


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class EcosystemServer:
    """A read-only MCP server backed by one ecosystem manifest + SQLite file."""

    def __init__(self, manifest_path: Path, db_override: Optional[Path], verbose: bool):
        self.manifest_path = manifest_path.resolve()
        self.manifest_dir = self.manifest_path.parent
        self.verbose = verbose
        self.initialized = False

        with self.manifest_path.open("r", encoding="utf-8") as handle:
            self.manifest = json.load(handle)

        self.limits = self.manifest.get("limits", {})
        self.timeout_seconds = float(self.limits.get("query_timeout_seconds", 5))
        self.query_default_rows = int(self.limits.get("query_default_rows", 200))
        self.query_max_rows = int(self.limits.get("query_max_rows", 1000))
        self.sample_max_rows = int(self.limits.get("sample_max_rows", 100))
        self.response_max_bytes = int(self.limits.get("response_max_bytes", 1_000_000))

        # Resolve the database path. The manifest stores it relative to the
        # manifest's own directory so the package relocates as a unit.
        if db_override is not None:
            self.db_path = db_override.resolve()
        else:
            self.db_path = (self.manifest_dir / self.manifest["database"]).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(f"database not found: {self.db_path}")

        # Table lookups: logical key (erp.customer) and physical name
        # (erp_customer) both resolve to the same manifest record.
        self.tables = self.manifest.get("tables", [])
        self.by_key: dict[str, dict[str, Any]] = {}
        self.by_physical: dict[str, dict[str, Any]] = {}
        for table in self.tables:
            self.by_key[table["key"]] = table
            self.by_physical[table["physical"]] = table

        # One read-only connection, opened once and reused. mode=ro is the
        # outermost guard; the authorizer and statement vetting are the inner
        # ones.
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.conn.text_factory = str
        self.conn.set_authorizer(self._authorizer)
        # Wall-clock timeout, enforced via the progress handler. _deadline is
        # only armed while a tool is touching the database.
        self._deadline: Optional[float] = None
        self._timed_out = False
        self.conn.set_progress_handler(self._progress_handler, 10000)

        self.tool_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "get_ecosystem_overview": self._tool_overview,
            "list_tables": self._tool_list_tables,
            "describe_table": self._tool_describe_table,
            "sample_rows": self._tool_sample_rows,
            "query": self._tool_query,
            "get_lineage": self._tool_get_lineage,
            "list_imperfections": self._tool_list_imperfections,
            "get_table_profile": self._tool_get_table_profile,
            "list_controls": self._tool_list_controls,
            "list_dq_rules": self._tool_list_dq_rules,
            "get_build_info": self._tool_build_info,
        }

    # -- infrastructure ----------------------------------------------------

    def log(self, message: str) -> None:
        if self.verbose:
            print(f"[mcp-server] {message}", file=sys.stderr, flush=True)

    def _authorizer(self, action: int, arg1: Any, arg2: Any, dbname: Any, source: Any) -> int:
        """Deny-by-default. Only the handful of actions a read-only SELECT needs
        are allowed; ATTACH/DETACH/PRAGMA and every write/DDL action are denied.
        Installed once at startup and never cleared while serving."""
        if action in _ALLOWED_ACTIONS:
            return SQLITE_OK
        return SQLITE_DENY

    def _progress_handler(self) -> int:
        # Returning non-zero aborts the running statement (raises
        # OperationalError), which the tool handlers translate into a timeout
        # message. Only fires while a deadline is armed.
        if self._deadline is not None and time.monotonic() > self._deadline:
            self._timed_out = True
            return 1
        return 0

    def _run_db(self, fn: Callable[[], Any]) -> Any:
        """Run a DB closure under the wall-clock timeout, translating an aborted
        statement into a ToolError."""
        self._timed_out = False
        self._deadline = time.monotonic() + self.timeout_seconds
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if self._timed_out:
                raise ToolError(
                    f"query exceeded the {int(self.timeout_seconds)} second limit") from exc
            raise ToolError(f"SQL error: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise ToolError(f"database error: {exc}") from exc
        finally:
            self._deadline = None

    # -- table resolution --------------------------------------------------

    def _resolve_table(self, raw: Any) -> dict[str, Any]:
        """Resolve a logical key (erp.customer) or physical name (erp_customer)
        to a manifest table record, or raise ToolError listing close matches."""
        if not isinstance(raw, str) or not raw.strip():
            raise ToolError("argument 'table' is required and must be a string "
                            "(a logical key like 'erp.customer' or a physical name).")
        name = raw.strip()
        if name in self.by_key:
            return self.by_key[name]
        if name in self.by_physical:
            return self.by_physical[name]
        # Unknown: surface the five closest table keys (substring first, then a
        # difflib fallback so there is always guidance).
        lowered = name.lower()
        keys = sorted(self.by_key)
        close = [k for k in keys if lowered in k.lower() or k.lower() in lowered]
        if len(close) < 5:
            import difflib
            for match in difflib.get_close_matches(name, keys, n=5, cutoff=0.3):
                if match not in close:
                    close.append(match)
        if not close:
            close = keys[:5]
        raise ToolError(f"unknown table '{name}'. Closest matches: {close[:5]}")

    # -- tool implementations ---------------------------------------------

    def _build_info_dict(self) -> dict[str, str]:
        return {key: value for key, value in self._run_db(
            lambda: self.conn.execute("select key, value from meta_build_info").fetchall())}

    def _table_row_counts(self) -> dict[str, int]:
        rows = self._run_db(
            lambda: self.conn.execute("select table_name, row_count from meta_table_stats").fetchall())
        return {name: count for name, count in rows}

    def _tool_overview(self, args: dict[str, Any]) -> dict[str, Any]:
        info = self._build_info_dict()
        counts = self._table_row_counts()
        imperfections = self._run_db(
            lambda: self.conn.execute("select count(*) from meta_imperfection_log").fetchone())[0]
        tables_per_layer: dict[str, int] = {}
        for table in self.tables:
            layer = table.get("layer") or "(unspecified)"
            tables_per_layer[layer] = tables_per_layer.get(layer, 0) + 1
        return {
            "organization": self.manifest.get("organization", {}),
            "time_horizon": self.manifest.get("time", {}),
            "engine_version": info.get("engine_version", self.manifest.get("engine_version")),
            "seed": info.get("seed"),
            "scale_multiplier": info.get("scale_multiplier"),
            "table_count": len(self.tables),
            "tables_per_layer": tables_per_layer,
            "total_rows": sum(counts.values()),
            "imperfections_logged": imperfections,
            "control_count": len(self.manifest.get("controls", [])),
            "dq_rule_count": len(self.manifest.get("dq_rules", [])),
            "disclaimer": self.manifest.get("disclaimer", ""),
        }

    def _tool_list_tables(self, args: dict[str, Any]) -> dict[str, Any]:
        schema = args.get("schema")
        layer = args.get("layer")
        counts = self._table_row_counts()
        out = []
        for table in self.tables:
            key = table["key"]
            table_schema = key.split(".", 1)[0]
            if schema and table_schema != schema:
                continue
            if layer and table.get("layer") != layer:
                continue
            out.append({
                "table": key,
                "physical_name": table["physical"],
                "layer": table.get("layer"),
                "purpose": table.get("purpose"),
                "grain": table.get("grain"),
                "row_count": counts.get(table["physical"]),
                "source": table.get("source"),
            })
        out.sort(key=lambda row: row["table"])
        return {"tables": out, "count": len(out)}

    def _tool_describe_table(self, args: dict[str, Any]) -> dict[str, Any]:
        table = self._resolve_table(args.get("table"))
        return {
            "table": table["key"],
            "physical_name": table["physical"],
            "layer": table.get("layer"),
            "purpose": table.get("purpose"),
            "grain": table.get("grain"),
            "source": table.get("source"),
            "source_system": table.get("source_system"),
            "primary_key": table.get("primary_key", []),
            "natural_key": table.get("natural_key", []),
            "traits": table.get("traits", []),
            "columns": table.get("columns", []),
        }

    def _tool_sample_rows(self, args: dict[str, Any]) -> dict[str, Any]:
        table = self._resolve_table(args.get("table"))
        limit = _clamp_int(args.get("limit", 10), 1, self.sample_max_rows, default=10)
        physical = table["physical"]

        def run() -> dict[str, Any]:
            cursor = self.conn.execute(
                f'select * from "{physical}" order by rowid limit ?', (limit,))
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [[_jsonable(cell) for cell in row] for row in cursor.fetchall()]
            return {"columns": columns, "rows": rows, "row_count": len(rows)}

        return self._run_db(run)

    def _tool_query(self, args: dict[str, Any]) -> dict[str, Any]:
        sql = args.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ToolError("argument 'sql' is required and must be a non-empty string.")
        limit = _clamp_int(args.get("limit", self.query_default_rows), 1,
                           self.query_max_rows, default=self.query_default_rows)
        self._vet_select(sql)

        def run() -> dict[str, Any]:
            cursor = self.conn.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            # Fetch one extra row to detect truncation by the row limit.
            fetched = cursor.fetchmany(limit + 1)
            truncated = len(fetched) > limit
            fetched = fetched[:limit]

            kept: list[list[Any]] = []
            overhead = 256 + sum(len(str(col)) + 8 for col in columns)
            size = overhead
            for row in fetched:
                jrow = [_jsonable(cell) for cell in row]
                row_bytes = len(json.dumps(jrow, ensure_ascii=False).encode("utf-8")) + 1
                if kept and size + row_bytes > self.response_max_bytes:
                    truncated = True
                    break
                kept.append(jrow)
                size += row_bytes
            return {"columns": columns, "rows": kept, "row_count": len(kept),
                    "truncated": truncated}

        return self._run_db(run)

    def _vet_select(self, sql: str) -> None:
        """Reject anything that is not a single read-only SELECT/WITH statement.
        The authorizer is the real guard against writes; this gives a clearer
        message and blocks multi-statement input outright."""
        first, rest = _first_statement_and_rest(sql)
        if rest.strip():
            raise ToolError("only a single statement is allowed; remove the trailing "
                            "statement(s) after the first ';'.")
        head = _strip_leading_sql_comments(first)
        if not head:
            raise ToolError("empty query.")
        keyword = re.match(r"(?is)^(select|with)\b", head)
        if not keyword:
            raise ToolError("only read-only SELECT/WITH queries are accepted "
                            "(no INSERT/UPDATE/DELETE/DROP/PRAGMA/ATTACH).")

    def _tool_get_lineage(self, args: dict[str, Any]) -> dict[str, Any]:
        table = self._resolve_table(args.get("table"))
        direction = args.get("direction", "both")
        if direction not in ("upstream", "downstream", "both"):
            raise ToolError("argument 'direction' must be 'upstream', 'downstream', or 'both'.")
        key = table["key"]
        edges = self.manifest.get("lineage", [])
        result: dict[str, Any] = {"table": key, "upstream": [], "downstream": []}
        if direction in ("upstream", "both"):
            result["upstream"] = _walk_lineage(edges, key, "to", "from")
        if direction in ("downstream", "both"):
            result["downstream"] = _walk_lineage(edges, key, "from", "to")
        return result

    def _tool_list_imperfections(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _clamp_int(args.get("limit", 20), 1, 100, default=20)
        clauses: list[str] = []
        params: list[Any] = []
        if args.get("table") is not None:
            physical = self._resolve_table(args.get("table"))["physical"]
            clauses.append("table_name = ?")
            params.append(physical)
        if args.get("type") is not None:
            clauses.append("imperfection_type = ?")
            params.append(str(args.get("type")))
        where = (" where " + " and ".join(clauses)) if clauses else ""

        def run() -> dict[str, Any]:
            total = self.conn.execute(
                f"select count(*) from meta_imperfection_log{where}", params).fetchone()[0]
            by_type = dict(self.conn.execute(
                f"select imperfection_type, count(*) from meta_imperfection_log{where} "
                "group by imperfection_type", params).fetchall())
            by_table = dict(self.conn.execute(
                f"select table_name, count(*) from meta_imperfection_log{where} "
                "group by table_name", params).fetchall())
            example_rows = self.conn.execute(
                "select imperfection_name, imperfection_type, table_name, pk_value, detail "
                f"from meta_imperfection_log{where} order by log_id limit ?",
                params + [limit]).fetchall()
            examples = [
                {"imperfection_name": r[0], "imperfection_type": r[1], "table_name": r[2],
                 "pk_value": r[3], "detail": r[4]} for r in example_rows]
            return {"total": total, "by_type": by_type, "by_table": by_table,
                    "examples": examples,
                    "note": "These are intentional, logged defects injected at "
                            "configured rates so validation can reconcile them. They "
                            "are a designed feature of this synthetic ecosystem, not "
                            "real data errors."}

        return self._run_db(run)

    def _tool_get_table_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        table = self._resolve_table(args.get("table"))
        physical = table["physical"]
        columns = [c["name"] for c in table.get("columns", [])]

        def run() -> dict[str, Any]:
            row_count = self.conn.execute(f'select count(*) from "{physical}"').fetchone()[0]
            skip_distinct = row_count > 2_000_000
            if not columns:
                return {"table": table["key"], "physical_name": physical,
                        "row_count": row_count, "columns": []}
            select_parts: list[str] = []
            for col in columns:
                quoted = f'"{col}"'
                select_parts.append(f"sum(case when {quoted} is null then 1 else 0 end)")
                select_parts.append("null" if skip_distinct else f"count(distinct {quoted})")
                select_parts.append(f"min({quoted})")
                select_parts.append(f"max({quoted})")
            agg = self.conn.execute(
                f'select {", ".join(select_parts)} from "{physical}"').fetchone()
            profile = []
            for index, col in enumerate(columns):
                base = index * 4
                nulls = agg[base] or 0
                distinct = agg[base + 1]
                profile.append({
                    "name": col,
                    "null_count": nulls,
                    "null_pct": round(100.0 * nulls / row_count, 4) if row_count else 0.0,
                    "distinct_count": distinct,
                    "min": _jsonable(agg[base + 2]),
                    "max": _jsonable(agg[base + 3]),
                })
            result: dict[str, Any] = {"table": table["key"], "physical_name": physical,
                                      "row_count": row_count, "columns": profile}
            if skip_distinct:
                result["note"] = ("distinct counts skipped: table exceeds 2,000,000 rows.")
            return result

        return self._run_db(run)

    def _tool_list_controls(self, args: dict[str, Any]) -> dict[str, Any]:
        controls = self.manifest.get("controls", [])
        return {"controls": controls, "count": len(controls),
                "required_views": self.manifest.get("required_views", [])}

    def _tool_list_dq_rules(self, args: dict[str, Any]) -> dict[str, Any]:
        rules = self.manifest.get("dq_rules", [])
        return {"dq_rules": rules, "count": len(rules)}

    def _tool_build_info(self, args: dict[str, Any]) -> dict[str, Any]:
        info = self._build_info_dict()
        return {
            "meta_build_info": info,
            "engine_version": self.manifest.get("engine_version"),
            "database_bytes": self.db_path.stat().st_size,
            "sqlite_library_version": sqlite3.sqlite_version,
        }

    # -- tool catalogue (tools/list) --------------------------------------

    def tool_catalogue(self) -> list[dict[str, Any]]:
        no_args = {"type": "object", "properties": {}}
        table_arg = {"type": "object",
                     "properties": {"table": {"type": "string",
                                              "description": "Logical key (e.g. 'erp.customer') "
                                                             "or physical name (e.g. 'erp_customer')."}},
                     "required": ["table"]}
        return [
            {"name": "get_ecosystem_overview",
             "description": "High-level summary of this synthetic ecosystem: organization, "
                            "time horizon, build seed/multiplier, table counts per layer, total "
                            "rows, and counts of logged imperfections, controls, and DQ rules.",
             "inputSchema": no_args},
            {"name": "list_tables",
             "description": "List tables with their layer, purpose, grain, source, and live row "
                            "count. Optionally filter by schema or warehouse layer.",
             "inputSchema": {"type": "object", "properties": {
                 "schema": {"type": "string", "description": "Filter to one schema prefix, e.g. 'erp'."},
                 "layer": {"type": "string", "description": "Filter to one warehouse layer."}}}},
            {"name": "describe_table",
             "description": "Full schema for one table: keys, traits, source system, and every "
                            "column with type, nullability, sensitivity, and FK target.",
             "inputSchema": table_arg},
            {"name": "sample_rows",
             "description": "Return the first rows of a table in deterministic rowid order. "
                            "limit defaults to 10 and is clamped to [1, 100].",
             "inputSchema": {"type": "object", "properties": {
                 "table": table_arg["properties"]["table"],
                 "limit": {"type": "integer", "description": "Rows to return (1-100, default 10)."}},
                 "required": ["table"]}},
            {"name": "query",
             "description": "Run a read-only SQL query. Only a single SELECT or WITH statement is "
                            "accepted (no INSERT/UPDATE/DELETE/DDL/PRAGMA/ATTACH). Results are "
                            "capped by 'limit' (default 200, max 1000) and a 1 MB byte cap; "
                            "'truncated' reports whether either cap applied.",
             "inputSchema": {"type": "object", "properties": {
                 "sql": {"type": "string", "description": "A single read-only SELECT/WITH statement."},
                 "limit": {"type": "integer", "description": "Max rows (1-1000, default 200)."}},
                 "required": ["sql"]}},
            {"name": "get_lineage",
             "description": "Transitive data lineage for a table, derived from the spec's "
                            "derivations and dataflows. Each entry names the upstream/downstream "
                            "table and the derivation or dataflow it travels through.",
             "inputSchema": {"type": "object", "properties": {
                 "table": table_arg["properties"]["table"],
                 "direction": {"type": "string", "enum": ["upstream", "downstream", "both"],
                               "description": "Default 'both'."}},
                 "required": ["table"]}},
            {"name": "list_imperfections",
             "description": "Summarize the intentional, logged data-quality imperfections: totals "
                            "by type and table, plus example rows. Optionally filter by table or "
                            "imperfection type. limit (default 20, max 100) caps examples only.",
             "inputSchema": {"type": "object", "properties": {
                 "table": table_arg["properties"]["table"],
                 "type": {"type": "string", "description": "Filter to one imperfection type."},
                 "limit": {"type": "integer", "description": "Example rows (1-100, default 20)."}}}},
            {"name": "get_table_profile",
             "description": "Compute a live column profile for a table: row count and per-column "
                            "null %, distinct count, and min/max. Distinct counts are skipped for "
                            "tables over 2,000,000 rows.",
             "inputSchema": table_arg},
            {"name": "list_controls",
             "description": "List the business/reconciliation controls declared in the spec, with "
                            "the validation result views they map to.",
             "inputSchema": no_args},
            {"name": "list_dq_rules",
             "description": "List the data-quality rules declared in the spec (dataset, rule type, "
                            "condition, severity, expected failure rate).",
             "inputSchema": no_args},
            {"name": "get_build_info",
             "description": "Build provenance: meta_build_info contents, engine version, database "
                            "file size in bytes, and the SQLite library version.",
             "inputSchema": no_args},
        ]

    # -- resources ---------------------------------------------------------

    def _existing_resources(self) -> list[dict[str, Any]]:
        out = []
        for resource in self.manifest.get("resources", []):
            path = (self.manifest_dir / resource["path"])
            if path.exists():
                out.append(resource)
        return out

    def resource_list(self) -> list[dict[str, Any]]:
        listed = []
        for resource in self._existing_resources():
            entry = {"uri": resource["uri"], "mimeType": resource.get("mimeType", "text/plain")}
            entry["name"] = resource.get("name") or resource["uri"].split("/")[-1]
            if resource.get("description"):
                entry["description"] = resource["description"]
            listed.append(entry)
        return listed

    def resource_read(self, uri: str) -> dict[str, Any]:
        for resource in self.manifest.get("resources", []):
            if resource["uri"] == uri:
                path = (self.manifest_dir / resource["path"])
                if not path.exists():
                    raise _RpcError(RESOURCE_NOT_FOUND, f"Resource not found: {uri}")
                text = path.read_text(encoding="utf-8")
                return {"contents": [{"uri": uri,
                                      "mimeType": resource.get("mimeType", "text/plain"),
                                      "text": text}]}
        raise _RpcError(RESOURCE_NOT_FOUND, f"Resource not found: {uri}")

    # -- prompts -----------------------------------------------------------

    def prompt_list(self) -> list[dict[str, Any]]:
        return [
            {"name": "tour-this-ecosystem",
             "description": "Guided first look at this synthetic ecosystem's data estate.",
             "arguments": []},
            {"name": "investigate-imperfections",
             "description": "Trace intentional data-quality defects and the rules that catch them.",
             "arguments": [{"name": "table", "description": "Optional logical key to focus on.",
                            "required": False}]},
        ]

    def prompt_get(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        org = self.manifest.get("organization", {}).get("name", "this organization")
        if name == "tour-this-ecosystem":
            text = (
                f"You are connected to a read-only MCP server for {org}, a SYNTHETIC and "
                "fictional enterprise data ecosystem. Give me a tour:\n"
                "1. Call get_ecosystem_overview to learn the organization, time horizon, and scale.\n"
                "2. Call list_tables once per layer (use the 'layer' filter) to see how the "
                "estate is organized from source systems through to the warehouse marts.\n"
                "3. Call sample_rows on one mart/warehouse table and one source fact table to see "
                "real values.\n"
                "4. Summarize what this organization's data estate contains and how it is layered. "
                "State clearly in your summary that everything is synthetic test data, not real "
                "organizational data or PII.")
            return {"description": "Guided first look at this ecosystem.",
                    "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        if name == "investigate-imperfections":
            table = arguments.get("table")
            focus = (f" Focus on the table '{table}'." if table else "")
            filter_hint = (f" passing table='{table}'" if table else "")
            text = (
                f"You are connected to a read-only MCP server for {org} (SYNTHETIC data)."
                f"{focus} Investigate its intentional data-quality imperfections:\n"
                f"1. Call list_imperfections{filter_hint} to see the totals by type and table.\n"
                "2. Pick two imperfection types from the results.\n"
                "3. For each, use the query tool to find affected rows (the examples include "
                "pk_value and table_name to start from).\n"
                "4. Call list_dq_rules and list_controls to find the rule or control that should "
                "catch each defect.\n"
                "5. Use get_lineage on the affected table to explain how each defect propagates "
                "into (or is filtered out of) the derived/warehouse layers.\n"
                "Remember these are designed, logged defects in synthetic data, not real errors.")
            return {"description": "Investigate intentional imperfections.",
                    "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        raise _RpcError(INVALID_PARAMS, f"Unknown prompt: {name}")

    # -- JSON-RPC dispatch -------------------------------------------------

    def instructions(self) -> str:
        org = self.manifest.get("organization", {})
        time_block = self.manifest.get("time", {})
        name = org.get("name", "an organization")
        archetype = org.get("archetype", "unspecified archetype")
        industry = org.get("industry", "unspecified industry")
        start = time_block.get("start_date", "?")
        end = time_block.get("end_date", "?")
        as_of = time_block.get("as_of_date", end)
        disclaimer = self.manifest.get("disclaimer", "")
        return (
            f"This server exposes a read-only enterprise data ecosystem for {name} "
            f"({archetype}; {industry}), spanning {start} to {end} (as of {as_of}). "
            f"{disclaimer} Use the read-only tools to explore tables, run SELECT queries, "
            "trace lineage, inspect intentional data-quality imperfections, and read the "
            "embedded documentation. Nothing here is real organizational data or real PII.")

    def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        self.initialized = True
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "serverInfo": {"name": self.manifest.get("server_name", "ecosystem-mcp-server"),
                           "version": str(self.manifest.get("engine_version", "0"))},
            "instructions": self.instructions(),
        }

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Return a result object for a request method, or raise _RpcError."""
        if method == "initialize":
            return self.handle_initialize(params)
        if method == "ping":
            return {}
        if not self.initialized:
            raise _RpcError(INVALID_PARAMS, "Server not initialized")
        if method == "tools/list":
            return {"tools": self.tool_catalogue()}
        if method == "tools/call":
            return self.handle_tools_call(params)
        if method == "resources/list":
            return {"resources": self.resource_list()}
        if method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str):
                raise _RpcError(INVALID_PARAMS, "resources/read requires a string 'uri'.")
            return self.resource_read(uri)
        if method == "prompts/list":
            return {"prompts": self.prompt_list()}
        if method == "prompts/get":
            name = params.get("name")
            if not isinstance(name, str):
                raise _RpcError(INVALID_PARAMS, "prompts/get requires a string 'name'.")
            return self.prompt_get(name, params.get("arguments") or {})
        raise _RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        handler = self.tool_handlers.get(name) if isinstance(name, str) else None
        if handler is None:
            raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _tool_error_result("'arguments' must be an object.")
        try:
            payload = handler(arguments)
        except ToolError as exc:
            return _tool_error_result(str(exc))
        except _RpcError:
            raise
        except Exception as exc:  # never let a tool crash the loop
            return _tool_error_result(f"tool '{name}' failed: {exc}")
        return {"content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                "isError": False}

    # -- main loop ---------------------------------------------------------

    def serve(self, stdin: Any, write: Callable[[str], None]) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            self._handle_line(line, write)

    def _handle_line(self, line: str, write: Callable[[str], None]) -> None:
        try:
            message = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            write(_error_envelope(None, PARSE_ERROR, "Parse error"))
            return
        if not isinstance(message, dict):
            write(_error_envelope(None, INVALID_REQUEST, "Invalid Request"))
            return

        method = message.get("method")
        is_request = "id" in message
        message_id = message.get("id")

        if not isinstance(method, str):
            if is_request:
                write(_error_envelope(message_id, INVALID_REQUEST, "Invalid Request"))
            return

        # Notifications (no id) never get a response. notifications/initialized
        # is expected; anything else is silently ignored.
        if not is_request:
            self.log(f"notification: {method}")
            return

        try:
            result = self.dispatch(method, message.get("params") or {})
            write(_result_envelope(message_id, result))
        except _RpcError as exc:
            write(_error_envelope(message_id, exc.code, exc.message))
        except Exception as exc:  # defensive: never crash the loop
            self.log(f"internal error handling {method}: {exc}")
            write(_error_envelope(message_id, INVALID_REQUEST, f"Internal error: {exc}"))

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass


# ---------------------------------------------------------------------------
# Module-level helpers used by the server
# ---------------------------------------------------------------------------


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _tool_error_result(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _result_envelope(message_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": message_id, "result": result}, ensure_ascii=False)


def _error_envelope(message_id: Any, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": message_id,
                       "error": {"code": code, "message": message}}, ensure_ascii=False)


def _walk_lineage(edges: list[dict[str, Any]], start: str, match_field: str,
                  yield_field: str) -> list[dict[str, Any]]:
    """Breadth-first transitive closure over lineage edges. ``match_field`` is
    the edge end that must equal the current node; ``yield_field`` is the other
    end we travel to. Returns ``[{table, via}]`` in stable order, recording the
    edge that first reached each node."""
    ordered_edges = sorted(edges, key=lambda e: (e.get("from", ""), e.get("to", ""), e.get("via", "")))
    visited = {start}
    frontier = [start]
    found: list[dict[str, Any]] = []
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            for edge in ordered_edges:
                if edge.get(match_field) == node:
                    target = edge.get(yield_field)
                    if target and target not in visited:
                        visited.add(target)
                        found.append({"table": target, "via": edge.get("via")})
                        nxt.append(target)
        frontier = nxt
    found.sort(key=lambda item: item["table"])
    return found


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    # stdout carries protocol bytes only; reconfigure both streams to UTF-8 so
    # the server is byte-clean on Windows hosts.
    for stream in (sys.stdout, sys.stdin, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    parser = argparse.ArgumentParser(description="Read-only MCP server over a built ecosystem.")
    default_manifest = Path(__file__).resolve().parent / "mcp_manifest.json"
    parser.add_argument("--manifest", type=Path, default=default_manifest,
                        help="Path to mcp_manifest.json (default: next to this script).")
    parser.add_argument("--db", type=Path, default=None,
                        help="Override the database path from the manifest.")
    parser.add_argument("--verbose", action="store_true", help="Log to stderr.")
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"error: manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    try:
        server = EcosystemServer(args.manifest, args.db, args.verbose)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: invalid manifest {args.manifest}: {exc}", file=sys.stderr)
        return 2

    server.log(f"serving {server.manifest.get('server_name')} over {server.db_path}")

    def write(text: str) -> None:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    try:
        server.serve(sys.stdin, write)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
