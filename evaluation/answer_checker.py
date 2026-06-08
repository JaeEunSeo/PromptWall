#!/usr/bin/env python3
"""Gold-vs-prediction answer checker for view-style SQL outputs.

This checker compares the GT (gold) view/result and a predicted view/result by:
1) converting each row to a dict keyed by column name,
2) normalizing values,
3) comparing rows as an order-insensitive multiset.

Expected input format (JSONL, one case per line):

Gold file example:
{"scenario_id": "system_admin_001", "rows": [{"table_name": "patients", "record_count": 10}, ...]}

Prediction file example:
{"scenario_id": "system_admin_001", "rows": [{"table_name": "patients", "record_count": 10}, ...]}

The script is intentionally permissive about field names. It will look for rows under:
- rows
- result
- gold_result
- view
- data
- output

Usage:
    python answer_checker.py --gold medical_gold_results.jsonl --pred model_outputs.jsonl --output checker_report.jsonl

Output per line:
{"scenario_id": ..., "match": true/false, "reason": ..., "gold_row_count": ..., "pred_row_count": ...}
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

ROW_KEYS = ("rows", "result", "gold_result", "view", "data", "output")
ID_KEYS = ("scenario_id", "id", "sample_id", "qid")


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


def save_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=False) + "\n")


def pick_id(record: Mapping[str, Any], fallback: str) -> str:
    for key in ID_KEYS:
        if key in record and record[key] is not None:
            return str(record[key])
    return fallback


def extract_rows(record: Mapping[str, Any]) -> List[Any]:
    for key in ROW_KEYS:
        if key in record:
            value = record[key]
            if value is None:
                return []
            if isinstance(value, list):
                return value
            # single row object
            return [value]
    return []


def normalize_value(value: Any) -> Any:
    """Make values comparable across common SQL/JSON serialization differences."""
    if value is None:
        return None

    # Normalize booleans before ints because bool is a subclass of int.
    if isinstance(value, bool):
        return value

    # Normalize ints/floats.
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            if math.isnan(value):
                return "__NaN__"
            if value.is_integer():
                return int(value)
        return value

    # Strings: trim surrounding whitespace only; keep internal spaces.
    if isinstance(value, str):
        s = value.strip()
        # Try to normalize obvious numeric strings.
        if s:
            try:
                if "." in s or "e" in s.lower():
                    f = float(s)
                    if f.is_integer():
                        return int(f)
                    return f
                return int(s)
            except ValueError:
                pass
        return s

    # Lists/dicts: normalize recursively.
    if isinstance(value, list):
        return [normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): normalize_value(v) for k, v in value.items()}

    return value


def row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert a row-like object into a column-keyed dict."""
    if row is None:
        return {}

    if isinstance(row, dict):
        return {str(k): normalize_value(v) for k, v in row.items()}

    # List/tuple row with separate columns is not supported unless already wrapped.
    # Accept a tiny subset of alternate formats:
    #   {"columns": [...], "values": [...]} or {"header": [...], "row": [...]}.
    if isinstance(row, Mapping):
        cols = row.get("columns") or row.get("header")
        vals = row.get("values") or row.get("row")
        if isinstance(cols, list) and isinstance(vals, list) and len(cols) == len(vals):
            return {str(c): normalize_value(v) for c, v in zip(cols, vals)}

    raise TypeError(
        "Each row must be a dict-like object or a {columns, values} / {header, row} structure."
    )


def rows_to_multiset(rows: Sequence[Any]) -> Tuple[Counter, List[Dict[str, Any]]]:
    """Convert rows into a Counter over canonical row signatures."""
    converted: List[Dict[str, Any]] = []
    signatures: List[Tuple[Tuple[str, str], ...]] = []

    for row in rows:
        d = row_to_dict(row)
        converted.append(d)
        signature = tuple(sorted((str(k), json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)) for k, v in d.items()))
        signatures.append(signature)

    return Counter(signatures), converted


def compare_views(gold_rows: Sequence[Any], pred_rows: Sequence[Any]) -> Tuple[bool, str]:
    """Compare two views as unordered multisets of row dicts."""
    gold_counter, gold_norm = rows_to_multiset(gold_rows)
    pred_counter, pred_norm = rows_to_multiset(pred_rows)

    if gold_counter == pred_counter:
        return True, "exact match"

    missing = gold_counter - pred_counter
    extra = pred_counter - gold_counter

    reason_parts: List[str] = []
    if missing:
        reason_parts.append(f"missing_rows={sum(missing.values())}")
    if extra:
        reason_parts.append(f"extra_rows={sum(extra.values())}")

    # Helpful debug hints for common schema/serialization mismatches.
    if gold_norm and pred_norm:
        gold_keys = set(gold_norm[0].keys())
        pred_keys = set(pred_norm[0].keys())
        if gold_keys != pred_keys:
            reason_parts.append(f"column_mismatch gold={sorted(gold_keys)} pred={sorted(pred_keys)}")

    if not reason_parts:
        reason_parts.append("row content mismatch")

    return False, "; ".join(reason_parts)


def index_by_id(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for i, item in enumerate(items):
        sid = pick_id(item, fallback=str(i))
        idx[sid] = item
    return idx


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare GT and predicted view-style SQL results.")
    parser.add_argument("--gold", required=True, type=Path, help="Gold JSONL file")
    parser.add_argument("--pred", required=True, type=Path, help="Prediction JSONL file")
    parser.add_argument("--output", required=True, type=Path, help="Output JSONL report")
    args = parser.parse_args()

    gold_items = load_jsonl(args.gold)
    pred_items = load_jsonl(args.pred)

    gold_map = index_by_id(gold_items)
    pred_map = index_by_id(pred_items)

    report: List[Dict[str, Any]] = []

    all_ids = sorted(set(gold_map) | set(pred_map))
    for sid in all_ids:
        gold = gold_map.get(sid)
        pred = pred_map.get(sid)

        if gold is None:
            report.append({
                "scenario_id": sid,
                "match": False,
                "reason": "missing_gold_case",
                "gold_row_count": 0,
                "pred_row_count": len(extract_rows(pred or {})),
            })
            continue

        if pred is None:
            report.append({
                "scenario_id": sid,
                "match": False,
                "reason": "missing_prediction_case",
                "gold_row_count": len(extract_rows(gold)),
                "pred_row_count": 0,
            })
            continue

        gold_rows = extract_rows(gold)
        pred_rows = extract_rows(pred)
        match, reason = compare_views(gold_rows, pred_rows)

        report.append({
            "scenario_id": sid,
            "match": match,
            "reason": reason,
            "gold_row_count": len(gold_rows),
            "pred_row_count": len(pred_rows),
        })

    save_jsonl(args.output, report)
    print(f"Wrote {len(report)} comparison rows to {args.output}")


if __name__ == "__main__":
    main()
