#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIO_PATH = PROJECT_ROOT / "data" / "medical" / "scenario_gold_query_medical.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "medical" / "synthea.sqlite"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "execution" / "medical" / "execute_gold_results_medical.json"


def normalize_sqlite_value(value: Any) -> Any:
    """Convert SQLite values into JSON-serializable values."""
    if isinstance(value, bytes):
        return value.hex()
    return value


def is_select_query(sql: str) -> bool:
    """Return True if the SQL query is a SELECT/WITH query."""
    cleaned = sql.strip().lower()
    return cleaned.startswith("select") or cleaned.startswith("with")


def execute_select(db_path: Path, sql: str) -> list[dict[str, Any]]:
    """Execute a SELECT query in read-only mode and return rows as dictionaries."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(sql)
        if cursor.description is None:
            raise ValueError("SELECT query did not return rows.")
        return [
            {key: normalize_sqlite_value(row[key]) for key in row.keys()}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def _replace_placeholders(
    sql: str,
    scenario_id: str,
    current_user_patient_id: str | None,
    current_user_provider_id: str | None,
) -> str | dict[str, Any]:
    """Replace medical runtime placeholders if present."""
    if "{current_user_patient_id}" in sql:
        if current_user_patient_id is None:
            return {
                "scenario_id": scenario_id,
                "status": "ERROR",
                "sql": sql,
                "error": "current_user_patient_id is required but not provided",
            }
        sql = sql.replace("{current_user_patient_id}", str(current_user_patient_id))

    if "{current_user_provider_id}" in sql:
        if current_user_provider_id is None:
            return {
                "scenario_id": scenario_id,
                "status": "ERROR",
                "sql": sql,
                "error": "current_user_provider_id is required but not provided",
            }
        sql = sql.replace("{current_user_provider_id}", str(current_user_provider_id))

    return sql


def process_scenario(
    scenario: dict[str, Any],
    db_path: Path,
    current_user_patient_id: str | None,
    current_user_provider_id: str | None,
) -> dict[str, Any]:
    """Process one scenario and return an output record in execute_gold format.

    - DENY: {scenario_id, status, category, reason}
    - ALLOW + SELECT: {scenario_id, status, sql, view}
    - ALLOW + UPDATE/DELETE/INSERT: {scenario_id, status, sql}
    - ERROR: {scenario_id, status, sql, error}
    """
    scenario_id = scenario["scenario_id"]
    expected_result = scenario["expected_result"].upper()

    if expected_result == "DENY":
        return {
            "scenario_id": scenario_id,
            "status": "DENY",
            "category": scenario["category"],
            "reason": scenario["reason_en"],
        }

    gold_query: str | None = scenario.get("gold_query")
    if gold_query is None:
        return {
            "scenario_id": scenario_id,
            "status": "DENY",
            "category": scenario.get("category", "unknown"),
            "reason": scenario.get("reason_en", "gold_query is null"),
        }

    sql_or_error = _replace_placeholders(
        gold_query,
        scenario_id,
        current_user_patient_id,
        current_user_provider_id,
    )
    if isinstance(sql_or_error, dict):
        return sql_or_error
    sql = sql_or_error

    if is_select_query(sql):
        try:
            view = execute_select(db_path, sql)
        except Exception as exc:
            return {
                "scenario_id": scenario_id,
                "status": "ALLOW",
                "sql": sql,
                "error": str(exc),
            }
        return {
            "scenario_id": scenario_id,
            "status": "ALLOW",
            "sql": sql,
            "view": view,
        }

    return {
        "scenario_id": scenario_id,
        "status": "ALLOW",
        "sql": sql,
    }


def execute_all_gold(
    scenario_path: Path = DEFAULT_SCENARIO_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    current_user_patient_id: str | None = None,
    current_user_provider_id: str | None = None,
) -> list[dict[str, Any]]:
    """Execute all scenarios from the medical gold-query JSON file."""
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenarios_by_role: dict[str, list[dict[str, Any]]] = data["scenarios"]

    results: list[dict[str, Any]] = []
    for _, scenarios in scenarios_by_role.items():
        for scenario in scenarios:
            result = process_scenario(
                scenario,
                db_path,
                current_user_patient_id,
                current_user_provider_id,
            )
            results.append(result)

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute gold SQL queries from scenario_gold_query_medical.json and save results."
    )
    parser.add_argument(
        "--scenario-path",
        type=Path,
        default=DEFAULT_SCENARIO_PATH,
        help="Path to the medical scenario gold query JSON file.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite DB path for executing SELECT queries.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to save the execution results JSON.",
    )
    parser.add_argument(
        "--current-user-patient-id",
        type=str,
        default=None,
        help="Runtime value for {current_user_patient_id} placeholder.",
    )
    parser.add_argument(
        "--current-user-provider-id",
        type=str,
        default=None,
        help="Runtime value for {current_user_provider_id} placeholder.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = execute_all_gold(
        scenario_path=args.scenario_path,
        db_path=args.db,
        current_user_patient_id=args.current_user_patient_id,
        current_user_provider_id=args.current_user_provider_id,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    allow_select = sum(1 for r in results if r["status"] == "ALLOW" and "view" in r)
    allow_modify = sum(
        1 for r in results if r["status"] == "ALLOW" and "view" not in r and "error" not in r
    )
    deny = sum(1 for r in results if r["status"] == "DENY")
    error = sum(1 for r in results if "error" in r)

    print(f"Total scenarios: {len(results)}")
    print(f"  ALLOW + SELECT (with view): {allow_select}")
    print(f"  ALLOW + UPDATE/DELETE/INSERT: {allow_modify}")
    print(f"  DENY: {deny}")
    if error:
        print(f"  ERROR: {error}")
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
