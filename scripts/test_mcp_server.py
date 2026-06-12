#!/usr/bin/env python3
"""Test client and verification battery for the generated MCP server.

Importable from sibling scripts (run_self_test.py / validate_all_examples.py)
and runnable directly:

  python scripts/test_mcp_server.py --build <dir> [--spec <spec.json>] [--smoke]

  * --smoke runs the fast per-example check (used in CI by validate_all_examples).
  * the default runs the full battery plus the generator determinism check.

Exit codes: 0 all checks pass, 1 a check failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from build_sqlite_ecosystem import TableSpec, load_spec  # noqa: E402

TOOL_NAMES = {
    "get_ecosystem_overview", "list_tables", "describe_table", "sample_rows",
    "query", "get_lineage", "list_imperfections", "get_table_profile",
    "list_controls", "list_dq_rules", "get_build_info",
}


# ---------------------------------------------------------------------------
# Test client
# ---------------------------------------------------------------------------


class MCPTestClient:
    """Drives ``<build>/mcp/server.py`` over stdio, matching responses by id."""

    def __init__(self, build_dir: Path, request_timeout: float = 30.0):
        self.server_path = Path(build_dir) / "mcp" / "server.py"
        if not self.server_path.exists():
            raise FileNotFoundError(f"server not generated: {self.server_path}")
        self.request_timeout = request_timeout
        self.proc = subprocess.Popen(
            [sys.executable, str(self.server_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", bufsize=1)
        self._next_id = 0
        self._stdout_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stderr_lines: list[str] = []
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._err_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._err_reader.start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:  # type: ignore[union-attr]
            self._stdout_queue.put(line)
        self._stdout_queue.put(None)

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:  # type: ignore[union-attr]
            self._stderr_lines.append(line)

    def stderr_text(self) -> str:
        return "".join(self._stderr_lines)

    # -- low-level framing --------------------------------------------------

    def send_raw(self, line: str) -> None:
        self.proc.stdin.write(line + "\n")  # type: ignore[union-attr]
        self.proc.stdin.flush()  # type: ignore[union-attr]

    def _send(self, message: dict[str, Any]) -> None:
        self.send_raw(json.dumps(message))

    def read_response(self, timeout: Optional[float] = None) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout or self.request_timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for a server response")
            try:
                line = self._stdout_queue.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("timed out waiting for a server response")
            if line is None:
                raise EOFError("server closed stdout")
            line = line.strip()
            if line:
                return json.loads(line)

    def notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def request(self, method: str, params: Optional[dict[str, Any]] = None,
                timeout: Optional[float] = None) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        deadline = time.monotonic() + (timeout or self.request_timeout)
        while True:
            response = self.read_response(timeout=max(0.01, deadline - time.monotonic()))
            if response.get("id") == message_id:
                return response
            # Ignore anything that is not our reply (no server notifications expected).

    # -- convenience --------------------------------------------------------

    def initialize(self, protocol_version: str = "2025-06-18") -> dict[str, Any]:
        response = self.request("initialize", {"protocolVersion": protocol_version,
                                               "capabilities": {},
                                               "clientInfo": {"name": "mcp-test-client",
                                                              "version": "1"}})
        self.notify("notifications/initialized")
        return response

    def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None,
                  timeout: Optional[float] = None) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}},
                            timeout=timeout)

    @staticmethod
    def is_error(response: dict[str, Any]) -> bool:
        return bool(response.get("result", {}).get("isError"))

    @staticmethod
    def tool_text(response: dict[str, Any]) -> str:
        return response["result"]["content"][0]["text"]

    @classmethod
    def tool_payload(cls, response: dict[str, Any]) -> Any:
        return json.loads(cls.tool_text(response))

    def close(self) -> int:
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            return self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                return self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                return self.proc.wait()

    def __enter__(self) -> "MCPTestClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _db_path(build_dir: Path) -> Path:
    dbs = sorted(Path(build_dir).glob("*.db"))
    if not dbs:
        raise FileNotFoundError(f"no .db found in {build_dir}")
    return dbs[0]


def _ro_conn(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_spec(build_dir: Path, spec_path: Optional[Path]) -> Path:
    if spec_path is not None:
        return spec_path
    copy = Path(build_dir) / "ecosystem_spec.json"
    if not copy.exists():
        raise FileNotFoundError(f"no spec given and no {copy} written by the generator")
    return copy


# ---------------------------------------------------------------------------
# Smoke check (fast, per-example in CI)
# ---------------------------------------------------------------------------


def run_smoke(build_dir: Path) -> list[str]:
    failures: list[str] = []
    client = MCPTestClient(build_dir, request_timeout=10)
    try:
        init = client.initialize()
        if "result" not in init or "serverInfo" not in init["result"]:
            failures.append("initialize did not return serverInfo")
        listed = client.request("tools/list")
        names = {tool["name"] for tool in listed["result"]["tools"]}
        if names != TOOL_NAMES:
            failures.append(f"tools/list mismatch: missing={TOOL_NAMES - names}, "
                            f"extra={names - TOOL_NAMES}")
        tables = client.call_tool("list_tables")
        if client.is_error(tables) or not client.tool_payload(tables)["tables"]:
            failures.append("list_tables returned no tables")
        q = client.call_tool("query", {"sql": "select 1"})
        if client.is_error(q) or client.tool_payload(q)["rows"] != [[1]]:
            failures.append(f"query 'select 1' failed: {client.tool_text(q)}")
    except (TimeoutError, EOFError, KeyError, json.JSONDecodeError) as exc:
        failures.append(f"smoke exception: {exc}\n{client.stderr_text()[-800:]}")
    finally:
        exit_code = client.close()
    if exit_code not in (0, None):
        failures.append(f"server exited with code {exit_code} on stdin EOF")
    return failures


# ---------------------------------------------------------------------------
# Full battery (self-test)
# ---------------------------------------------------------------------------


def run_full_battery(build_dir: Path, spec_path: Optional[Path] = None) -> list[str]:
    build_dir = Path(build_dir)
    spec_path = _resolved_spec(build_dir, spec_path)
    spec = load_spec(spec_path)
    tables = [TableSpec(raw, i, spec) for i, raw in enumerate(spec.get("tables", []))]
    manifest = json.loads((build_dir / "mcp" / "mcp_manifest.json").read_text(encoding="utf-8"))
    db_path = _db_path(build_dir)
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    # Initialization gating on a throwaway process: a real request before
    # initialize must be rejected.
    gate = MCPTestClient(build_dir)
    try:
        early = gate.request("tools/list")
        check(early.get("error", {}).get("code") == -32602,
              f"[gate] tools/list before initialize should be -32602, got {early.get('error')}")
    finally:
        gate.close()

    client = MCPTestClient(build_dir)
    try:
        # 1. Handshake.
        init = client.initialize()
        result = init["result"]
        check(result["serverInfo"]["name"] == manifest["server_name"],
              f"[1] serverInfo.name {result['serverInfo']['name']} != manifest "
              f"{manifest['server_name']}")
        check(result["protocolVersion"] in {"2024-11-05", "2025-03-26", "2025-06-18"},
              f"[1] negotiated version not supported: {result['protocolVersion']}")
        check("synthetic" in result.get("instructions", "").lower(),
              "[1] instructions must mention 'synthetic'")

        # 2. Overview org name matches the spec.
        overview = client.tool_payload(client.call_tool("get_ecosystem_overview"))
        spec_org = spec.get("organization", {}).get("name")
        check(overview["organization"]["name"] == spec_org,
              f"[2] overview org {overview['organization']['name']} != spec {spec_org}")

        # 3. list_tables count + row counts match meta_table_stats.
        conn = _ro_conn(db_path)
        try:
            stats = {name: count for name, count in conn.execute(
                "select table_name, row_count from meta_table_stats")}
        finally:
            conn.close()
        listed = client.tool_payload(client.call_tool("list_tables"))
        check(listed["count"] == len(manifest["tables"]),
              f"[3] list_tables count {listed['count']} != manifest tables "
              f"{len(manifest['tables'])}")
        mismatched = [row["physical_name"] for row in listed["tables"]
                      if row["row_count"] is not None
                      and stats.get(row["physical_name"]) != row["row_count"]]
        check(not mismatched, f"[3] row counts disagree with meta_table_stats: {mismatched[:5]}")

        # 4. describe_table on a known generator table: pk + columns match spec.
        sample_table = next((t for t in tables if t.primary_key and t.columns), tables[0])
        described = client.tool_payload(
            client.call_tool("describe_table", {"table": sample_table.key}))
        check(described["primary_key"] == list(sample_table.primary_key),
              f"[4] describe_table pk {described['primary_key']} != spec "
              f"{list(sample_table.primary_key)}")
        described_cols = [c["name"] for c in described["columns"]]
        check(described_cols == list(sample_table.column_names),
              f"[4] describe_table columns differ for {sample_table.key}")

        # 5. sample_rows is byte-identical across two identical calls.
        first = client.tool_text(client.call_tool("sample_rows", {"table": sample_table.key, "limit": 5}))
        second = client.tool_text(client.call_tool("sample_rows", {"table": sample_table.key, "limit": 5}))
        check(first == second, "[5] sample_rows not deterministic across identical calls")

        # 6. query happy path matches a direct count.
        populated = next((name for name, count in stats.items() if count and count > 0), None)
        if populated:
            conn = _ro_conn(db_path)
            try:
                direct = conn.execute(f'select count(*) from "{populated}"').fetchone()[0]
            finally:
                conn.close()
            q = client.tool_payload(client.call_tool(
                "query", {"sql": f'select count(*) as n from "{populated}"'}))
            check(q["rows"][0][0] == direct,
                  f"[6] query count {q['rows'][0][0]} != direct {direct} for {populated}")
        else:
            failures.append("[6] no populated table to count")

        # 7. Negative battery: every write/DDL/multi-statement is isError, never a
        #    crash, and the database bytes are unchanged afterward.
        target = populated or manifest["tables"][0]["physical"]
        hash_before = _file_sha256(db_path)
        negatives = [
            ("INSERT", f'insert into "{target}" default values'),
            ("UPDATE", f'update "{target}" set rowid = rowid'),
            ("DELETE", f'delete from "{target}"'),
            ("DROP", f'drop table "{target}"'),
            ("PRAGMA", "pragma journal_mode=wal"),
            ("ATTACH", "attach database ':memory:' as x"),
            ("MULTI", "select 1; select 2"),
            ("COMMENT_WRITE", f'/* hi */ delete from "{target}"'),
            ("CTE_INSERT", f'with x as (select 1) insert into "{target}" default values'),
        ]
        for label, sql in negatives:
            response = client.call_tool("query", {"sql": sql})
            check("result" in response and client.is_error(response),
                  f"[7] {label} should be isError, got {response.get('result') or response.get('error')}")
        hash_after = _file_sha256(db_path)
        check(hash_before == hash_after,
              "[7] database file changed during the negative battery!")

        # 8. Timeout: a pathological cross-join aborts with the time-limit message.
        biggest = max(stats.items(), key=lambda kv: kv[1] or 0)[0] if stats else target
        t0 = time.monotonic()
        cross = client.call_tool(
            "query", {"sql": f'select count(*) from "{biggest}" a, "{biggest}" b, "{biggest}" c'},
            timeout=20)
        elapsed = time.monotonic() - t0
        check(client.is_error(cross) and "limit" in client.tool_text(cross).lower(),
              f"[8] cross-join should hit the time limit, got {client.tool_text(cross)[:100]}")
        check(elapsed < 15, f"[8] timeout took too long: {elapsed:.1f}s")

        # 9. Clamps.
        clamped = client.tool_payload(client.call_tool(
            "query", {"sql": f'select * from "{biggest}"', "limit": 999999}))
        check(clamped["row_count"] <= 1000, f"[9] query not clamped: {clamped['row_count']} rows")
        if (stats.get(biggest) or 0) > 1000:
            check(clamped["truncated"], "[9] large result should report truncated=true")
        sampled = client.tool_payload(client.call_tool(
            "sample_rows", {"table": biggest, "limit": 10000}))
        check(sampled["row_count"] <= 100, f"[9] sample_rows not clamped: {sampled['row_count']}")

        # 10. list_imperfections total matches a direct count.
        conn = _ro_conn(db_path)
        try:
            direct_imp = conn.execute("select count(*) from meta_imperfection_log").fetchone()[0]
        finally:
            conn.close()
        imp = client.tool_payload(client.call_tool("list_imperfections"))
        check(imp["total"] == direct_imp,
              f"[10] imperfection total {imp['total']} != direct {direct_imp}")

        # 11. get_lineage on a derived table returns at least one upstream edge.
        derived = next((t["key"] for t in manifest["tables"]
                        if t.get("source") == "derivation"
                        and any(e["to"] == t["key"] for e in manifest["lineage"])), None)
        if derived:
            lineage = client.tool_payload(client.call_tool(
                "get_lineage", {"table": derived, "direction": "upstream"}))
            check(len(lineage["upstream"]) >= 1,
                  f"[11] {derived} should have upstream lineage")
        else:
            failures.append("[11] no derived table with lineage to test")

        # 12. resources: every listed resource is readable; spec parses as JSON.
        resources = client.request("resources/list")["result"]["resources"]
        check(len(resources) >= 1, "[12] resources/list is empty")
        for resource in resources:
            read = client.request("resources/read", {"uri": resource["uri"]})
            check("result" in read and read["result"]["contents"],
                  f"[12] resource not readable: {resource['uri']}")
        spec_read = client.request("resources/read", {"uri": "ecosystem://spec"})
        try:
            json.loads(spec_read["result"]["contents"][0]["text"])
        except (KeyError, json.JSONDecodeError) as exc:
            failures.append(f"[12] ecosystem://spec did not parse as JSON: {exc}")

        # 13. prompts.
        prompts = client.request("prompts/list")["result"]["prompts"]
        check(len(prompts) == 2, f"[13] expected 2 prompts, got {len(prompts)}")
        for prompt in prompts:
            got = client.request("prompts/get", {"name": prompt["name"], "arguments": {}})
            check(bool(got.get("result", {}).get("messages")),
                  f"[13] prompts/get {prompt['name']} returned no messages")

        # 14. Protocol errors.
        unknown_method = client.request("does/not/exist")
        check(unknown_method.get("error", {}).get("code") == -32601,
              f"[14] unknown method should be -32601, got {unknown_method.get('error')}")
        client.send_raw("this is not json")
        parse_err = client.read_response()
        check(parse_err.get("error", {}).get("code") == -32700 and parse_err.get("id") is None,
              f"[14] bad JSON should be -32700 with null id, got {parse_err}")
        bogus_resource = client.request("resources/read", {"uri": "ecosystem://nope"})
        check(bogus_resource.get("error", {}).get("code") == -32002,
              f"[14] bogus resource should be -32002, got {bogus_resource.get('error')}")
        unknown_tool = client.call_tool("not_a_tool")
        check(unknown_tool.get("error", {}).get("code") == -32602,
              f"[14] unknown tool should be -32602, got {unknown_tool.get('error')}")
    except (TimeoutError, EOFError) as exc:
        failures.append(f"battery aborted: {exc}\n{client.stderr_text()[-800:]}")
    finally:
        exit_code = client.close()

    # 15. EOF: closing stdin exits cleanly.
    check(exit_code == 0, f"[15] server exit code on EOF was {exit_code}, expected 0")
    return failures


# ---------------------------------------------------------------------------
# Generator determinism check
# ---------------------------------------------------------------------------


def run_determinism_check(build_dir: Path, spec_path: Optional[Path] = None) -> list[str]:
    """Generate the package twice from copies of the same build and assert the
    three emitted files are byte-identical."""
    build_dir = Path(build_dir)
    spec_path = _resolved_spec(build_dir, spec_path)
    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="mcp_determinism_"))
    try:
        digests: list[dict[str, str]] = []
        for index in range(2):
            target = tmp / f"build{index}"
            shutil.copytree(build_dir, target)
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "generate_mcp_server.py"), str(spec_path),
                 "--build", str(target), "--force", "--quiet"],
                capture_output=True, encoding="utf-8", errors="replace", env=dict(os.environ))
            if proc.returncode != 0:
                failures.append(f"determinism: generation {index} failed: {proc.stderr or proc.stdout}")
                return failures
            digests.append({name: _file_sha256(target / "mcp" / name)
                            for name in ("server.py", "mcp_manifest.json", "README.md")})
        for name in ("server.py", "mcp_manifest.json", "README.md"):
            if digests[0][name] != digests[1][name]:
                failures.append(f"determinism: {name} differs across two generations")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", type=Path, required=True, help="Build directory with mcp/.")
    parser.add_argument("--spec", type=Path, default=None,
                        help="Spec path (default: <build>/ecosystem_spec.json).")
    parser.add_argument("--smoke", action="store_true", help="Run the fast smoke check only.")
    args = parser.parse_args(argv)

    if not (args.build / "mcp" / "server.py").exists():
        print(f"error: no generated server in {args.build}; run generate_mcp_server.py first",
              file=sys.stderr)
        return 2

    if args.smoke:
        failures = run_smoke(args.build)
        label = "SMOKE"
    else:
        failures = run_full_battery(args.build, args.spec)
        failures += run_determinism_check(args.build, args.spec)
        label = "FULL BATTERY"

    if failures:
        print(f"MCP {label} FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"MCP {label} PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
