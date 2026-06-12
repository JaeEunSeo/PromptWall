"""
사용법:
python3 execute_gold.py --current-user-client-id 1
"""
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SCENARIO_PATH = PROJECT_ROOT / "data" / "financial" / "scenario_gold_query.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "financial" / "financial.sqlite"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "execution" / "financial" / "execute_gold_results.json"


def normalize_sqlite_value(value: Any) -> Any:
    """SQLite 결과값을 JSON 직렬화 가능한 형태로 변환한다. bytes는 hex 문자열로 변환."""
    if isinstance(value, bytes):
        return value.hex()
    return value


def is_select_query(sql: str) -> bool:
    """SQL 문이 SELECT(또는 WITH ... SELECT) 쿼리인지 판별한다."""
    cleaned = sql.strip().lower()
    return cleaned.startswith("select") or cleaned.startswith("with")


def execute_select(db_path: Path, sql: str) -> list[dict[str, Any]]:
    """SELECT 쿼리를 읽기 전용 모드로 실행하고, 결과를 딕셔너리 리스트로 반환한다."""
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


def process_scenario(
    scenario: dict[str, Any],
    db_path: Path,
    current_user_client_id: int | None,
) -> dict[str, Any]:
    """단일 시나리오의 gold query를 처리하여 출력 형식에 맞는 결과 딕셔너리를 반환한다.

    - DENY: {scenario_id, status, category, reason}
    - ALLOW + SELECT: {scenario_id, status, sql, view}
    - ALLOW + UPDATE/DELETE/INSERT: {scenario_id, status, sql}
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

    sql = gold_query
    if "{current_user_client_id}" in sql:
        if current_user_client_id is None:
            return {
                "scenario_id": scenario_id,
                "status": "ERROR",
                "sql": sql,
                "error": "current_user_client_id is required but not provided",
            }
        sql = sql.replace("{current_user_client_id}", str(current_user_client_id))

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
    current_user_client_id: int | None = None,
) -> list[dict[str, Any]]:
    """시나리오 JSON의 모든 역할·시나리오를 순회하며 gold query를 실행/처리한 결과 리스트를 반환한다."""
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenarios_by_role: dict[str, list[dict[str, Any]]] = data["scenarios"]

    results: list[dict[str, Any]] = []
    for role, scenarios in scenarios_by_role.items():
        for scenario in scenarios:
            result = process_scenario(scenario, db_path, current_user_client_id)
            results.append(result)

    return results


def parse_args() -> argparse.Namespace:
    """커맨드라인 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="Execute gold SQL queries from scenario_gold_query.json and save results."
    )
    parser.add_argument(
        "--scenario-path",
        type=Path,
        default=DEFAULT_SCENARIO_PATH,
        help="Path to the scenario gold query JSON file.",
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
        "--current-user-client-id",
        type=int,
        default=None,
        help="Runtime value for {current_user_client_id} placeholder (needed for customer role scenarios).",
    )
    return parser.parse_args()


def main() -> None:
    """전체 gold query를 실행하고, 결과를 JSON 파일로 저장한 뒤 요약 통계를 출력한다."""
    args = parse_args()
    results = execute_all_gold(
        scenario_path=args.scenario_path,
        db_path=args.db,
        current_user_client_id=args.current_user_client_id,
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
