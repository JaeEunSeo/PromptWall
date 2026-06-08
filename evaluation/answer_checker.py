#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gold-vs-prediction answer checker (status-first, then execution-based).

평가 절차 (scenario_id로 gold/pred 매칭):
  1) ALLOW/DENY 일치 여부 판정.
     - status가 다르면 즉시 불일치.
     - 둘 다 DENY면 일치 (실행할 SQL 없음).
  2) 둘 다 ALLOW면 gold_sql과 pred_sql을 실제 SQLite DB에서 실행:
     - 행 수준 필터 placeholder({current_user_patient_id}, {current_user_provider_id})는
       DB에 실재하는 ID로 동일하게 치환.
     - SELECT는 결과 행을, INSERT/UPDATE/DELETE는 {"rowcount": n}을 결과로 사용.
     - 변경 연산은 트랜잭션을 ROLLBACK하여 DB를 보존.
     - 결과를 dict 멀티셋(순서 무시)으로 비교.
  3) status 일치 AND 결과 일치 → 최종 match=true.

입력:
  gold: scenario_gold_query_medical.json (financial 스타일 단일 JSON: metadata + scenarios{role:[...]},
        각 시나리오에 expected_result + gold_query). JSONL 형식도 자동 인식.
  pred: query_generator_medical.py 산출물. JSON 단건/배열, JSONL 모두 인식
        (scenario_id, pred_status, pred_sql)

사용:
  python answer_checker.py --gold ../data/medical/scenario_gold_query_medical.json \
      --pred preds.json --db ../../synthea_1k.sqlite --output report.jsonl
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

DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "synthea_1k.sqlite"


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
    """gold/pred 파일을 평탄한 레코드 리스트로 로드 (gold·pred 공용).

    지원 포맷:
      - 단일 JSON 객체: {"scenario_id":..., ...}                → [obj]
      - JSON 배열: [ {...}, {...} ]
      - 중첩 JSON (financial 스타일): {"metadata":..., "scenarios": {role: [..]}} 또는 scenarios가 리스트
      - JSONL: 한 줄에 하나의 레코드
    """
    text = path.read_text(encoding="utf-8").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return load_jsonl(path)  # JSONL 폴백

    if isinstance(obj, dict) and "scenarios" in obj:
        scen = obj["scenarios"]
        items: List[Dict[str, Any]] = []
        if isinstance(scen, dict):           # role -> [scenarios]
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


# ── 값/행 정규화 + 멀티셋 비교 ───────────────────────────────────────────────
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


def row_to_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return {str(k): normalize_value(v) for k, v in row.items()}
    raise TypeError("Each row must be a dict-like object.")


def rows_to_multiset(rows: Sequence[Any]) -> Counter:
    signatures = []
    for row in rows:
        d = row_to_dict(row)
        sig = tuple(sorted(
            (str(k), json.dumps(v, ensure_ascii=False, sort_keys=True, default=str))
            for k, v in d.items()
        ))
        signatures.append(sig)
    return Counter(signatures)


def compare_results(gold_rows: Sequence[Any], pred_rows: Sequence[Any]) -> Tuple[bool, str]:
    gold_c = rows_to_multiset(gold_rows)
    pred_c = rows_to_multiset(pred_rows)
    if gold_c == pred_c:
        return True, "result match"
    missing = sum((gold_c - pred_c).values())
    extra = sum((pred_c - gold_c).values())
    parts = []
    if missing:
        parts.append(f"missing_rows={missing}")
    if extra:
        parts.append(f"extra_rows={extra}")
    if gold_rows and pred_rows:
        gk = set(row_to_dict(gold_rows[0])); pk = set(row_to_dict(pred_rows[0]))
        if gk != pk:
            parts.append(f"column_mismatch gold={sorted(gk)} pred={sorted(pk)}")
    return False, "; ".join(parts) or "result mismatch"


# ── SQL 실행 ─────────────────────────────────────────────────────────────────
def substitute_placeholders(sql: str, subs: Mapping[str, str]) -> str:
    for ph, val in subs.items():
        sql = sql.replace(ph, str(val))
    return sql


def run_sql(con: sqlite3.Connection, sql: str, subs: Mapping[str, str]) -> Tuple[List[dict] | None, str | None]:
    """SQL 실행 → (rows, error). 변경 연산은 rollback하여 DB를 보존."""
    if not sql or not sql.strip():
        return None, "empty_sql"
    sql = substitute_placeholders(sql, subs)
    cur = con.cursor()
    try:
        cur.execute(sql)
        if cur.description:  # SELECT 등 결과 집합이 있는 경우
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        else:               # INSERT/UPDATE/DELETE
            rows = [{"rowcount": cur.rowcount}]
        return rows, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        con.rollback()  # 어떤 변경도 영구 반영하지 않음


def get_placeholder_values(con: sqlite3.Connection) -> Dict[str, str]:
    """행 수준 필터 placeholder를 채울 실제 ID를 DB에서 가져온다."""
    subs: Dict[str, str] = {}
    try:
        r = con.execute("SELECT Id FROM patients LIMIT 1").fetchone()
        if r:
            subs["{current_user_patient_id}"] = r[0]
    except Exception:
        pass
    try:
        r = con.execute("SELECT Id FROM providers LIMIT 1").fetchone()
        if r:
            subs["{current_user_provider_id}"] = r[0]
    except Exception:
        pass
    return subs


# ── 메인 채점 ────────────────────────────────────────────────────────────────
def check_one(gold: Mapping[str, Any] | None, pred: Mapping[str, Any] | None,
              con: sqlite3.Connection, subs: Mapping[str, str]) -> Dict[str, Any]:
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

    # ① ALLOW/DENY 일치 판정
    status_match = (gold_status == pred_status)
    if not status_match:
        return {**base, "match": False, "status_match": False,
                "result_match": None,
                "reason": f"status_mismatch (gold={gold_status} pred={pred_status})"}

    # 둘 다 DENY → 실행할 SQL 없음, 일치
    if gold_status == "DENY":
        return {**base, "match": True, "status_match": True,
                "result_match": None, "reason": "deny match"}

    # ② 둘 다 ALLOW → 실제 실행 후 결과 비교
    gold_sql = first_key(gold, GOLD_SQL_KEYS)
    pred_sql = first_key(pred, PRED_SQL_KEYS)

    gold_rows, gold_err = run_sql(con, gold_sql or "", subs)
    pred_rows, pred_err = run_sql(con, pred_sql or "", subs)

    if gold_err:
        return {**base, "match": False, "status_match": True,
                "result_match": False, "reason": f"gold_sql_error: {gold_err}"}
    if pred_err:
        return {**base, "match": False, "status_match": True,
                "result_match": False, "reason": f"pred_sql_error: {pred_err}",
                "gold_row_count": len(gold_rows or [])}

    result_match, reason = compare_results(gold_rows or [], pred_rows or [])
    return {**base, "match": (status_match and result_match),
            "status_match": True, "result_match": result_match,
            "reason": reason,
            "gold_row_count": len(gold_rows or []),
            "pred_row_count": len(pred_rows or [])}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ALLOW/DENY 일치 + (ALLOW 시) 실제 실행 결과 비교 채점기")
    parser.add_argument("--gold", required=True, type=Path,
                        help="gold 파일 (scenario_gold_query_medical.json 또는 JSONL)")
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
    # pred에 존재하는 scenario_id만 채점 대상으로 한다
    all_ids = sorted(pred_map)
    for sid in all_ids:
        rec = check_one(gold_map.get(sid), pred_map.get(sid), con, subs)
        rec = {"scenario_id": sid, **rec}
        report.append(rec)

    con.close()
    save_jsonl(args.output, report)

    # 요약
    total = len(report)
    matched = sum(1 for r in report if r["match"])
    status_ok = sum(1 for r in report if r.get("status_match"))
    print(f"Wrote {total} rows to {args.output}")
    print(f"status accuracy : {status_ok}/{total} = {status_ok/total:.1%}")
    print(f"final match     : {matched}/{total} = {matched/total:.1%}")


if __name__ == "__main__":
    main()
