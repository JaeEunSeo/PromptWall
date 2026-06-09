#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gold-vs-prediction answer checker — 위치 기반(positional) 값 비교 버전.

answer_checker.py와 동일한 평가 절차를 따르되, SELECT 결과 비교 시
컬럼명(alias)을 무시하고 **컬럼 위치(순서)** 기준으로 값만 비교한다.

예) gold: SELECT COUNT(*) AS record_count  →  (77,)
    pred: SELECT COUNT(*) AS row_count     →  (77,)
    → 컬럼명은 다르지만 위치별 값이 같으므로 match=true

제한:
  - SELECT 절의 컬럼 순서가 다르면 불일치로 판정된다.
    예) gold: SELECT a, b  vs  pred: SELECT b, a  → mismatch
  - 컬럼 개수가 다르면 즉시 불일치.

사용:
  python answer_checker_positional.py \
      --gold ../data/financial/scenario_gold_query.json \
      --pred predictions.jsonl \
      --db ../data/financial/financial.sqlite \
      --output report.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

ID_KEYS = ("scenario_id", "id", "sample_id", "qid")
GOLD_STATUS_KEYS = ("expected_result", "gold_status", "expected", "status")
PRED_STATUS_KEYS = ("pred_status", "status", "result")
GOLD_SQL_KEYS = ("gold_query", "gold_sql", "sql")
PRED_SQL_KEYS = ("pred_sql", "sql")

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "financial" / "financial.sqlite"


# ── I/O ────────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {line_no} of {path}: {e}") from e
    return items


def load_records(path: Path) -> List[Dict[str, Any]]:
    """gold/pred 파일을 평탄한 레코드 리스트로 로드 (gold·pred 공용)."""
    text = path.read_text(encoding="utf-8").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return load_jsonl(path)

    if isinstance(obj, dict) and "scenarios" in obj:
        scen = obj["scenarios"]
        items: List[Dict[str, Any]] = []
        if isinstance(scen, dict):
            for role_items in scen.values():
                items.extend(role_items)
        elif isinstance(scen, list):
            items.extend(scen)
        return items
    if isinstance(obj, list):
        return obj
    return [obj]


def save_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=False) + "\n")


def first_key(record: Mapping[str, Any], keys: Sequence[str], default=None):
    for k in keys:
        if k in record and record[k] is not None:
            return record[k]
    return default


def index_by_id(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for i, item in enumerate(items):
        sid = str(first_key(item, ID_KEYS, default=str(i)))
        idx[sid] = item
    return idx


# ── 값 정규화 + 위치 기반 멀티셋 비교 ──────────────────────────────────────

def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            if math.isnan(value):
                return "__NaN__"
            if value.is_integer():
                return int(value)
        return value
    if isinstance(value, str):
        s = value.strip()
        if s:
            try:
                if "." in s or "e" in s.lower():
                    f = float(s)
                    return int(f) if f.is_integer() else f
                return int(s)
            except ValueError:
                pass
        return s
    if isinstance(value, list):
        return [normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): normalize_value(v) for k, v in value.items()}
    return value


def row_to_value_tuple(row: dict) -> tuple:
    """행의 값을 컬럼 순서(삽입 순서) 그대로 정규화된 튜플로 변환한다."""
    return tuple(
        json.dumps(normalize_value(v), ensure_ascii=False, sort_keys=True, default=str)
        for v in row.values()
    )


def rows_to_positional_multiset(rows: Sequence[dict]) -> Counter:
    """행 목록을 위치 기반 값 튜플의 멀티셋으로 변환한다."""
    return Counter(row_to_value_tuple(row) for row in rows)


def compare_results_positional(
    gold_cols: List[str],
    pred_cols: List[str],
    gold_rows: Sequence[dict],
    pred_rows: Sequence[dict],
) -> Tuple[bool, str]:
    """위치 기반 값 비교. 컬럼명은 무시하고 컬럼 개수와 위치별 값만 비교한다."""
    if len(gold_cols) != len(pred_cols):
        return False, (
            f"column_count_mismatch gold={len(gold_cols)} pred={len(pred_cols)} "
            f"(gold_cols={gold_cols} pred_cols={pred_cols})"
        )

    gold_c = rows_to_positional_multiset(gold_rows)
    pred_c = rows_to_positional_multiset(pred_rows)

    if gold_c == pred_c:
        alias_note = ""
        if gold_cols != pred_cols:
            alias_note = f" (alias_differs: gold={gold_cols} pred={pred_cols})"
        return True, f"result match{alias_note}"

    missing = sum((gold_c - pred_c).values())
    extra = sum((pred_c - gold_c).values())
    parts = []
    if missing:
        parts.append(f"missing_rows={missing}")
    if extra:
        parts.append(f"extra_rows={extra}")
    if gold_cols != pred_cols:
        parts.append(f"alias_differs: gold={gold_cols} pred={pred_cols}")
    return False, "; ".join(parts) or "result mismatch"


# ── SQL 실행 ─────────────────────────────────────────────────────────────────

def substitute_placeholders(sql: str, subs: Mapping[str, str]) -> str:
    for ph, val in subs.items():
        sql = sql.replace(ph, str(val))
    return sql


def run_sql(
    con: sqlite3.Connection, sql: str, subs: Mapping[str, str],
) -> Tuple[List[str] | None, List[dict] | None, str | None]:
    """SQL 실행 → (cols, rows, error). 변경 연산은 rollback하여 DB를 보존."""
    if not sql or not sql.strip():
        return None, None, "empty_sql"
    sql = substitute_placeholders(sql, subs)
    cur = con.cursor()
    try:
        cur.execute(sql)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        else:
            cols = ["rowcount"]
            rows = [{"rowcount": cur.rowcount}]
        return cols, rows, None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"
    finally:
        con.rollback()


def get_placeholder_values(con: sqlite3.Connection) -> Dict[str, str]:
    """행 수준 필터 placeholder를 채울 실제 ID를 DB에서 가져온다."""
    subs: Dict[str, str] = {}
    # medical
    for table, ph in [("patients", "{current_user_patient_id}"),
                      ("providers", "{current_user_provider_id}")]:
        try:
            r = con.execute(f"SELECT Id FROM {table} LIMIT 1").fetchone()
            if r:
                subs[ph] = r[0]
        except Exception:
            pass
    # financial
    for table, ph in [("client", "{current_user_client_id}")]:
        try:
            r = con.execute(f"SELECT client_id FROM {table} LIMIT 1").fetchone()
            if r:
                subs[ph] = str(r[0])
        except Exception:
            pass
    return subs


# ── 메인 채점 ────────────────────────────────────────────────────────────────

def check_one(
    gold: Mapping[str, Any] | None,
    pred: Mapping[str, Any] | None,
    con: sqlite3.Connection,
    subs: Mapping[str, str],
) -> Dict[str, Any]:
    gold_status = str(first_key(gold or {}, GOLD_STATUS_KEYS, "")).upper()
    pred_status = str(first_key(pred or {}, PRED_STATUS_KEYS, "")).upper()

    base = {
        "gold_status": gold_status or None,
        "pred_status": pred_status or None,
    }

    if gold is None:
        return {**base, "match": False, "status_match": False,
                "result_match": None, "reason": "missing_gold_case"}
    if pred is None:
        return {**base, "match": False, "status_match": False,
                "result_match": None, "reason": "missing_prediction_case"}

    status_match = (gold_status == pred_status)
    if not status_match:
        return {**base, "match": False, "status_match": False,
                "result_match": None,
                "reason": f"status_mismatch (gold={gold_status} pred={pred_status})"}

    if gold_status == "DENY":
        return {**base, "match": True, "status_match": True,
                "result_match": None, "reason": "deny match"}

    gold_sql = first_key(gold, GOLD_SQL_KEYS)
    pred_sql = first_key(pred, PRED_SQL_KEYS)

    gold_cols, gold_rows, gold_err = run_sql(con, gold_sql or "", subs)
    pred_cols, pred_rows, pred_err = run_sql(con, pred_sql or "", subs)

    if gold_err:
        return {**base, "match": False, "status_match": True,
                "result_match": False, "reason": f"gold_sql_error: {gold_err}"}
    if pred_err:
        return {**base, "match": False, "status_match": True,
                "result_match": False, "reason": f"pred_sql_error: {pred_err}",
                "gold_row_count": len(gold_rows or [])}

    result_match, reason = compare_results_positional(
        gold_cols or [], pred_cols or [],
        gold_rows or [], pred_rows or [],
    )
    return {**base, "match": (status_match and result_match),
            "status_match": True, "result_match": result_match,
            "reason": reason,
            "gold_row_count": len(gold_rows or []),
            "pred_row_count": len(pred_rows or [])}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ALLOW/DENY 일치 + (ALLOW 시) 위치 기반 값 비교 채점기")
    parser.add_argument("--gold", required=True, type=Path,
                        help="gold 파일 (scenario JSON 또는 JSONL)")
    parser.add_argument("--pred", required=True, type=Path, help="prediction JSONL")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"SQLite DB 경로 (기본: {DEFAULT_DB})")
    parser.add_argument("--output", required=True, type=Path, help="report JSONL")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"DB를 찾을 수 없습니다: {args.db}")

    gold_map = index_by_id(load_records(args.gold))
    pred_map = index_by_id(load_records(args.pred))

    con = sqlite3.connect(str(args.db))
    subs = get_placeholder_values(con)

    report: List[Dict[str, Any]] = []
    all_ids = sorted(pred_map)
    for sid in all_ids:
        rec = check_one(gold_map.get(sid), pred_map.get(sid), con, subs)
        rec = {"scenario_id": sid, **rec}
        report.append(rec)

    con.close()
    save_jsonl(args.output, report)

    total = len(report)
    matched = sum(1 for r in report if r["match"])
    status_ok = sum(1 for r in report if r.get("status_match"))
    print(f"Wrote {total} rows to {args.output}")
    print(f"status accuracy : {status_ok}/{total} = {status_ok/total:.1%}")
    print(f"final match     : {matched}/{total} = {matched/total:.1%}")


if __name__ == "__main__":
    main()
