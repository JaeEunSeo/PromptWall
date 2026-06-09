#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy-Aware SQL Query Generator (금융 도메인) — 단건 / 배치 모드 지원.

- system prompt : prompt/query_generator_financial.txt
- permission    : data/financial/permission_list.json
- scenarios     : data/financial/scenario_gold_query.json

사용 예:
  # 단건 모드 — 인자로 직접 전달
  python query_generator_financial.py --role teller \
      --request "계좌 12345에 5000코루나 입금 처리해줘" \
      --scenario-id teller_001

  # 배치 모드 — 시나리오 파일의 모든 항목에 대해 예측 생성
  python query_generator_financial.py \
      --batch data/financial/scenario_gold_query.json \
      --out predictions.jsonl \
      --current-user-client-id 116

선행 준비:
  pip install openai
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import openai
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompt" / "query_generator_financial.txt"
DEFAULT_PERMISSION_PATH = PROJECT_ROOT / "data" / "financial" / "permission_list.json"
DEFAULT_SCENARIO_PATH = PROJECT_ROOT / "data" / "financial" / "scenario_gold_query.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "financial" / "financial.sqlite"
DEFAULT_MODEL = "gpt-5.4-nano"


# ── 프롬프트 로딩 ──────────────────────────────────────────────────────────────

def load_text(path: Path) -> str:
    """텍스트 파일을 읽어 문자열로 반환한다."""
    return path.read_text(encoding="utf-8").strip()


def load_permission_prompt(path: Path) -> str:
    """권한 JSON 파일을 읽어 시스템 프롬프트용 문자열로 반환한다."""
    permissions: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    permission_json = json.dumps(permissions, ensure_ascii=False, indent=2)
    return f"Permission List:\n{permission_json}"


def build_runtime_placeholder_prompt(current_user_client_id: int | None) -> str | None:
    """customer 역할의 런타임 플레이스홀더 프롬프트를 생성한다."""
    if current_user_client_id is None:
        return None
    return (
        "Runtime Placeholder Values:\n"
        f"- {{current_user_client_id}}: {current_user_client_id}\n\n"
        "When applying row_filter permissions, replace {current_user_client_id} "
        "with this runtime value."
    )


def validate_runtime_context(user_role: str, current_user_client_id: int | None) -> None:
    """customer 역할에 current_user_client_id가 필수인지 검증한다."""
    if user_role.lower() == "customer" and current_user_client_id is None:
        raise ValueError("customer role requires --current-user-client-id.")


# ── SQL 정규화 / 실행 ──────────────────────────────────────────────────────────

def normalize_sql_for_sqlite(sql: str) -> str:
    """모델이 반환한 SQL 문자열에서 코드 펜스, 따옴표 래핑, 이스케이프 문자를 제거한다."""
    cleaned = sql.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:sql|sqlite)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    if cleaned.startswith('"'):
        try:
            decoded, _ = json.JSONDecoder().raw_decode(cleaned)
            if isinstance(decoded, str):
                cleaned = decoded.strip()
        except json.JSONDecodeError:
            pass

    if len(cleaned) >= 2 and cleaned[0] in {"'", '"'} and cleaned[-1] == cleaned[0]:
        try:
            decoded = ast.literal_eval(cleaned)
            if isinstance(decoded, str):
                cleaned = decoded.strip()
        except (SyntaxError, ValueError):
            cleaned = cleaned[1:-1].strip()

    return (
        cleaned
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .strip()
    )


def strip_leading_sql_comments(sql: str) -> str:
    """SQL 앞부분의 주석(-- 및 /* */)을 제거한다."""
    cleaned = sql.lstrip()
    while True:
        if cleaned.startswith("--"):
            _, _, cleaned = cleaned.partition("\n")
            cleaned = cleaned.lstrip()
            continue
        if cleaned.startswith("/*"):
            end = cleaned.find("*/")
            if end == -1:
                return cleaned
            cleaned = cleaned[end + 2:].lstrip()
            continue
        return cleaned


def is_select_query(sql: str) -> bool:
    """SQL 문이 SELECT(또는 WITH ... SELECT) 쿼리인지 판별한다."""
    cleaned = strip_leading_sql_comments(sql).lower()
    return cleaned.startswith("select") or cleaned.startswith("with")


def normalize_sqlite_value(value: Any) -> Any:
    """SQLite 결과값을 JSON 직렬화 가능한 형태로 변환한다."""
    if isinstance(value, bytes):
        return value.hex()
    return value


def execute_select_as_dicts(db_path: Path, sql: str) -> list[dict[str, Any]]:
    """SELECT 쿼리를 읽기 전용 모드로 실행하고, 결과를 딕셔너리 리스트로 반환한다."""
    normalized_sql = normalize_sql_for_sqlite(sql)
    if not is_select_query(normalized_sql):
        raise ValueError("Only SELECT queries can be executed.")

    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(normalized_sql)
        if cursor.description is None:
            raise ValueError("SELECT query did not return rows.")
        return [
            {key: normalize_sqlite_value(row[key]) for key in row.keys()}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def attach_select_view_if_needed(
    model_response: str,
    db_path: Path,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """모델 응답 JSON을 파싱하고, ALLOW+SELECT이면 실행 결과(view)를 첨부한다.

    반환값은 scenario_id가 맨 앞에 위치하는 딕셔너리이다.
    """
    parsed = json.loads(model_response)
    if not isinstance(parsed, dict):
        parsed = {"raw": model_response}

    prefix: dict[str, Any] = {}
    if scenario_id is not None:
        prefix["scenario_id"] = scenario_id

    status = str(parsed.get("status", "")).upper()
    sql = parsed.get("sql")

    if status != "ALLOW" or not isinstance(sql, str):
        return {**prefix, **parsed}

    normalized_sql = normalize_sql_for_sqlite(sql)
    parsed["sql"] = normalized_sql
    if is_select_query(normalized_sql):
        rows = execute_select_as_dicts(db_path, normalized_sql)
        return {**prefix, "status": parsed["status"], "sql": normalized_sql, "view": rows}

    return {**prefix, **parsed}


# ── LLM 호출 ──────────────────────────────────────────────────────────────────

def generate_sql(
    user_request: str,
    user_role: str,
    model: str,
    current_user_client_id: int | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    permission_path: Path = DEFAULT_PERMISSION_PATH,
    scenario_id: str | None = None,
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """LLM을 호출하여 정책 인지 SQL을 생성하고, 결과 딕셔너리를 반환한다."""
    validate_runtime_context(user_role, current_user_client_id)

    client = client or OpenAI()
    query_generator_prompt = load_text(prompt_path)
    permission_prompt = load_permission_prompt(permission_path)
    runtime_placeholder_prompt = build_runtime_placeholder_prompt(current_user_client_id)

    messages = [
        {"role": "system", "content": query_generator_prompt},
        {"role": "system", "content": permission_prompt},
    ]
    if runtime_placeholder_prompt is not None:
        messages.append({"role": "system", "content": runtime_placeholder_prompt})
    messages.append(
        {
            "role": "user",
            "content": f"User Role: {user_role}\nUser Request: {user_request}",
        }
    )

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("The model returned an empty response.")
    return attach_select_view_if_needed(content, db_path, scenario_id=scenario_id)


# ── 시나리오 로딩 (배치용) ─────────────────────────────────────────────────────

def load_scenarios(path: Path) -> list[dict[str, Any]]:
    """시나리오 파일을 평탄한 레코드 리스트로 로드한다.

    지원 포맷:
      - 중첩 JSON (scenario_gold_query.json 스타일): {"scenarios": {role: [...]}}
      - JSON 배열: [{...}, ...]
      - JSONL: 한 줄에 하나의 레코드
    """
    text = path.read_text(encoding="utf-8").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        items: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
        return items

    if isinstance(obj, dict) and "scenarios" in obj:
        scen = obj["scenarios"]
        items = []
        if isinstance(scen, dict):
            for role_items in scen.values():
                items.extend(role_items)
        elif isinstance(scen, list):
            items.extend(scen)
        return items
    if isinstance(obj, list):
        return obj
    return [obj]


# ── 배치 실행 ──────────────────────────────────────────────────────────────────

def run_batch(
    batch_path: Path,
    out_path: Path,
    *,
    model: str,
    lang: str = "ko",
    current_user_client_id: int | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    permission_path: Path = DEFAULT_PERMISSION_PATH,
) -> int:
    """시나리오 파일의 모든 항목에 대해 LLM 예측을 생성하고 JSONL로 저장한다."""
    client = OpenAI()
    req_key = "scenario_ko" if lang == "ko" else "scenario_en"
    scenarios = load_scenarios(batch_path)

    n = 0
    with open(out_path, "w", encoding="utf-8") as fout:
        for item in scenarios:
            sid = item.get("scenario_id")
            role = item.get("role", "")
            request = item.get(req_key) or item.get("scenario_ko") or item.get("scenario_en")

            if not request:
                print(f"[SKIP] {sid}: 요청 텍스트 없음", file=sys.stderr)
                continue

            cid = current_user_client_id if role.lower() == "customer" else None

            try:
                rec = generate_sql(
                    user_request=request,
                    user_role=role,
                    model=model,
                    current_user_client_id=cid,
                    db_path=db_path,
                    prompt_path=prompt_path,
                    permission_path=permission_path,
                    scenario_id=sid,
                    client=client,
                )
            except Exception as e:
                rec = {"scenario_id": sid, "status": "ERROR", "reason": str(e)}

            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            n += 1
            print(f"[{n}/{len(scenarios)}] {sid}: {rec.get('status')}", file=sys.stderr)

    print(f"Wrote {n} predictions to {out_path}", file=sys.stderr)
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """커맨드라인 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="금융 도메인 정책 인지 SQL 생성기 (단건 / 배치 모드)"
    )
    parser.add_argument("--role", help="사용자 역할 (예: teller, admin, customer)")
    parser.add_argument("--request", help="자연어 요청")
    parser.add_argument("--scenario-id", help="단건 저장 시 함께 기록할 시나리오 ID")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        help=f"OpenAI 모델 (기본: OPENAI_MODEL 또는 {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--current-user-client-id",
        type=int,
        default=None,
        help="customer 역할의 {current_user_client_id} 런타임 값",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help="ALLOW SELECT 실행에 사용할 SQLite DB 경로",
    )
    parser.add_argument(
        "--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH,
        help="시스템 프롬프트 파일 경로",
    )
    parser.add_argument(
        "--permission-path", type=Path, default=DEFAULT_PERMISSION_PATH,
        help="권한 JSON 파일 경로",
    )
    parser.add_argument(
        "--batch", type=Path, default=None,
        help="배치 모드: 시나리오 파일 경로 (JSON 또는 JSONL)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="결과 저장 경로 (.json 단건 / .jsonl 배치)",
    )
    parser.add_argument(
        "--lang", choices=["ko", "en"], default="ko",
        help="배치 모드에서 사용할 요청 언어 (기본: ko)",
    )
    return parser.parse_args()


def main() -> int:
    """단건 또는 배치 모드로 LLM SQL 생성을 실행한다."""
    args = parse_args()

    # ── 배치 모드 ──────────────────────────────────────────────────────────
    if args.batch:
        if not args.out:
            print("--batch 사용 시 --out(.jsonl)이 필요합니다.", file=sys.stderr)
            return 2
        try:
            return run_batch(
                args.batch, args.out,
                model=args.model,
                lang=args.lang,
                current_user_client_id=args.current_user_client_id,
                db_path=args.db,
                prompt_path=args.prompt_path,
                permission_path=args.permission_path,
            )
        except openai.AuthenticationError:
            print("인증 실패: OPENAI_API_KEY를 확인하세요.", file=sys.stderr)
            return 1
        except openai.APIError as e:
            print(f"API 오류: {e}", file=sys.stderr)
            return 1

    # ── 단건 모드 ──────────────────────────────────────────────────────────
    role = args.role or input("User Role: ").strip()
    request = args.request or input("User Request: ").strip()

    if not role or not request:
        print("role과 request를 모두 입력해야 합니다.", file=sys.stderr)
        return 2

    try:
        record = generate_sql(
            user_request=request,
            user_role=role,
            model=args.model,
            current_user_client_id=args.current_user_client_id,
            db_path=args.db,
            prompt_path=args.prompt_path,
            permission_path=args.permission_path,
            scenario_id=args.scenario_id,
        )
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    except openai.AuthenticationError:
        print("인증 실패: OPENAI_API_KEY를 확인하세요.", file=sys.stderr)
        return 1
    except openai.APIError as e:
        print(f"API 오류: {e}", file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved to {args.out}", file=sys.stderr)
    print(json.dumps(record, ensure_ascii=False, indent=2))

    return 0 if record.get("status") == "ALLOW" else 10


if __name__ == "__main__":
    sys.exit(main())
