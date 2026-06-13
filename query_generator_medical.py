#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy-Aware SQL Query Generator (의료 도메인) — 단건 / 배치 모드 지원.

query_generator_financial.py와 동일한 인터페이스/구현을 따르되, Synthea 의료 DB에 맞춤:
  - row_filter placeholder: {current_user_patient_id}, {current_user_provider_id}
  - system prompt : prompt/query_generator_medical.txt (v1) / prompt_v2/query_generator_medical.txt (v2)
  - permission    : data/medical/permissions_medical.json
  - scenarios     : data/medical/scenario_gold_query_medical.json

사용 예:
  # 단건 모드
  python query_generator_medical.py --role nurse \
      --request "방금 측정한 혈압 120/80을 환자의 observations로 기록해줘." \
      --scenario-id nurse_001

  # 배치 모드 (v2 프롬프트)
  python query_generator_medical.py \
      --batch data/medical/scenarios_medical.json \
      --out execution/medical/query_generator_results_medical_v2.jsonl \
      --prompt-version v2

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

import openai
from openai import OpenAI

try:  # .env 가 있으면 로드 (없거나 dotenv 미설치여도 무시)
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parent
if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompt" / "query_generator_medical.txt"
DEFAULT_PROMPT_PATH_V2 = PROJECT_ROOT / "prompt_v2" / "query_generator_medical.txt"
DEFAULT_PERMISSION_PATH = PROJECT_ROOT / "data" / "medical" / "permissions_medical.json"
DEFAULT_SCENARIO_PATH = PROJECT_ROOT / "data" / "medical" / "scenario_gold_query_medical.json"
SCENARIOS_PATH = PROJECT_ROOT / "data" / "medical" / "scenarios_medical.json"
# 의료 DB는 리포지토리 루트(PromptWall의 상위)에 위치
DEFAULT_DB_PATH = PROJECT_ROOT.parent / "synthea_1k.sqlite"
DEFAULT_MODEL = "gpt-5.4-nano"


# ── 프롬프트 로딩 ──────────────────────────────────────────────────────────────

def load_text(path: Path) -> str:
    """텍스트 파일을 읽어 문자열로 반환한다."""
    return path.read_text(encoding="utf-8").strip()


def load_permissions(path: Path) -> dict[str, Any]:
    """권한 JSON 파일 전체를 로드한다."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_permission_prompt(path: Path) -> str:
    """권한 JSON 파일을 읽어 시스템 프롬프트용 문자열로 반환한다 (v1: 전체 role 포함)."""
    permissions = load_permissions(path)
    permission_json = json.dumps(permissions, ensure_ascii=False, indent=2)
    return f"Permission List:\n{permission_json}"


def get_role_permissions(permissions: dict[str, Any], role: str) -> dict[str, Any]:
    """요청 role의 권한 블록(table_permissions 포함)만 반환한다."""
    roles = permissions.get("roles", {})
    if role not in roles:
        available = ", ".join(sorted(roles))
        raise ValueError(f"알 수 없는 role: '{role}'.\n사용 가능한 role: {available}")
    return roles[role]


def build_role_permission_json(permissions: dict[str, Any], role: str) -> str:
    """요청 role의 권한 블록만 JSON 문자열로 직렬화한다 (v2: user 메시지용)."""
    return json.dumps(get_role_permissions(permissions, role), ensure_ascii=False, indent=2)


def build_user_message_v1(user_role: str, user_request: str) -> str:
    """v1: User Role + User Request만 포함한 user 메시지를 구성한다."""
    return f"User Role: {user_role}\nUser Request: {user_request}"


def build_user_message_v2(user_role: str, user_request: str, role_permission_json: str) -> str:
    """v2: User Role + User Request + 요청 role의 Permission List를 포함한 user 메시지를 구성한다."""
    return (
        f"User Role: {user_role}\n"
        f"User Request: {user_request}\n"
        f"Permission List:\n{role_permission_json}"
    )


def resolve_default_placeholders(db_path: Path) -> tuple[str | None, str | None]:
    """DB에서 행 수준 필터 placeholder 기본값을 가져온다.

    answer_checker가 치환에 쓰는 것과 동일한 규칙(첫 행)으로 선택하여,
    생성된 SQL의 주입값과 채점 시 치환값이 일치하도록 한다.
    """
    patient_id = provider_id = None
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            r = conn.execute("SELECT Id FROM patients LIMIT 1").fetchone()
            if r:
                patient_id = r[0]
            r = conn.execute("SELECT Id FROM providers LIMIT 1").fetchone()
            if r:
                provider_id = r[0]
        finally:
            conn.close()
    except Exception:
        pass
    return patient_id, provider_id


def build_runtime_placeholder_prompt(
    current_user_patient_id: str | None,
    current_user_provider_id: str | None,
) -> str | None:
    """행 수준 필터 placeholder의 런타임 값을 알려주는 system 프롬프트를 생성한다.

    값이 하나도 제공되지 않으면 None을 반환하며, 이 경우 모델은 placeholder를
    SQL에 그대로 남겨 둔다(채점 시점에 치환됨).
    """
    lines: list[str] = []
    if current_user_patient_id is not None:
        lines.append(f"- {{current_user_patient_id}}: {current_user_patient_id}")
    if current_user_provider_id is not None:
        lines.append(f"- {{current_user_provider_id}}: {current_user_provider_id}")
    if not lines:
        return None
    return (
        "Runtime Placeholder Values:\n"
        + "\n".join(lines)
        + "\n\nWhen applying row_filter permissions, replace these placeholders "
        "with the runtime values above."
    )


# ── scenario_id 자동 매칭 (단건 모드에서 request로 scenario_id 추론) ──────────────

_scenario_index: dict[tuple[str, str], str] | None = None


def _load_scenario_index() -> dict[tuple[str, str], str]:
    """scenarios_medical.json을 (role, 요청문) -> scenario_id 로 인덱싱(1회 캐시)."""
    global _scenario_index
    if _scenario_index is None:
        _scenario_index = {}
        try:
            data = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _scenario_index
        for items in data.get("scenarios", {}).values():
            for it in items:
                sid = it.get("scenario_id")
                role = it.get("role")
                for key in ("scenario_ko", "scenario_en"):
                    text = it.get(key)
                    if role and text and sid:
                        _scenario_index[(role, text.strip())] = sid
    return _scenario_index


def lookup_scenario_id(role: str, request: str) -> str | None:
    """role이 같고 scenario_ko/scenario_en이 request와 완전 동일하면 그 scenario_id 반환."""
    return _load_scenario_index().get((role, request.strip()))


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
        try:
            rows = execute_select_as_dicts(db_path, normalized_sql)
            return {**prefix, "status": parsed["status"], "sql": normalized_sql, "view": rows}
        except Exception as e:
            # 실행 실패(placeholder 미치환 등)는 view 없이 sql만 반환하고 사유를 남긴다
            return {**prefix, "status": parsed["status"], "sql": normalized_sql,
                    "view_error": str(e)}

    return {**prefix, **parsed}


# ── LLM 호출 ──────────────────────────────────────────────────────────────────

def generate_sql(
    user_request: str,
    user_role: str,
    model: str,
    current_user_patient_id: str | None = None,
    current_user_provider_id: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    prompt_path: Path | None = None,
    permission_path: Path = DEFAULT_PERMISSION_PATH,
    prompt_version: str = "v1",
    scenario_id: str | None = None,
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """LLM을 호출하여 정책 인지 SQL을 생성하고, 결과 딕셔너리를 반환한다."""
    if prompt_version not in ("v1", "v2"):
        raise ValueError(f"알 수 없는 prompt_version: '{prompt_version}'. 'v1' 또는 'v2'를 사용하세요.")

    client = client or OpenAI()
    if prompt_path is None:
        prompt_path = DEFAULT_PROMPT_PATH_V2 if prompt_version == "v2" else DEFAULT_PROMPT_PATH

    query_generator_prompt = load_text(prompt_path)
    runtime_placeholder_prompt = build_runtime_placeholder_prompt(
        current_user_patient_id, current_user_provider_id
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": query_generator_prompt},
    ]

    if prompt_version == "v2":
        permissions = load_permissions(permission_path)
        role_permission_json = build_role_permission_json(permissions, user_role)
        if runtime_placeholder_prompt is not None:
            messages.append({"role": "system", "content": runtime_placeholder_prompt})
        messages.append(
            {
                "role": "user",
                "content": build_user_message_v2(user_role, user_request, role_permission_json),
            }
        )
    else:
        messages.append({"role": "system", "content": load_permission_prompt(permission_path)})
        if runtime_placeholder_prompt is not None:
            messages.append({"role": "system", "content": runtime_placeholder_prompt})
        messages.append(
            {
                "role": "user",
                "content": build_user_message_v1(user_role, user_request),
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
      - 중첩 JSON (scenarios_medical.json / scenario_gold_query_medical.json): {"scenarios": {role: [...]}}
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
    current_user_patient_id: str | None = None,
    current_user_provider_id: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    prompt_path: Path | None = None,
    permission_path: Path = DEFAULT_PERMISSION_PATH,
    prompt_version: str = "v1",
) -> int:
    """시나리오 파일의 모든 항목에 대해 LLM 예측을 생성하고 JSONL로 저장한다."""
    client = OpenAI()
    # 요청 텍스트 필드: scenario_ko/en(시나리오 파일) 또는 request_ko/en(gold 파일) 지원
    pref = (("scenario_ko", "request_ko") if lang == "ko"
            else ("scenario_en", "request_en"))
    fallbacks = ("scenario_ko", "scenario_en", "request_ko", "request_en")
    scenarios = load_scenarios(batch_path)

    n = 0
    with open(out_path, "w", encoding="utf-8") as fout:
        for item in scenarios:
            sid = item.get("scenario_id")
            role = item.get("role", "")
            request = next((item[k] for k in (*pref, *fallbacks) if item.get(k)), None)

            if not request:
                print(f"[SKIP] {sid}: 요청 텍스트 없음", file=sys.stderr)
                continue

            try:
                rec = generate_sql(
                    user_request=request,
                    user_role=role,
                    model=model,
                    current_user_patient_id=current_user_patient_id,
                    current_user_provider_id=current_user_provider_id,
                    db_path=db_path,
                    prompt_path=prompt_path,
                    permission_path=permission_path,
                    prompt_version=prompt_version,
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
        description="의료 도메인 정책 인지 SQL 생성기 (단건 / 배치 모드)"
    )
    parser.add_argument("--role", help="사용자 역할 (예: nurse, attending_physician, patient)")
    parser.add_argument("--request", help="자연어 요청")
    parser.add_argument("--scenario-id", help="단건 저장 시 함께 기록할 시나리오 ID")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        help=f"OpenAI 모델 (기본: OPENAI_MODEL 또는 {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--current-user-patient-id",
        default=None,
        help="patient 역할의 {current_user_patient_id} 런타임 값 (patients.id, UUID)",
    )
    parser.add_argument(
        "--current-user-provider-id",
        default=None,
        help="attending_physician 역할의 {current_user_provider_id} 런타임 값 (providers.id, UUID)",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help=f"ALLOW SELECT 실행에 사용할 SQLite DB 경로 (기본: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--prompt-path", type=Path, default=None,
        help="시스템 프롬프트 파일 경로 (기본: --prompt-version에 따라 prompt/ 또는 prompt_v2/의 "
             "query_generator_medical.txt)",
    )
    parser.add_argument(
        "--permission-path", type=Path, default=DEFAULT_PERMISSION_PATH,
        help="권한 JSON 파일 경로",
    )
    parser.add_argument(
        "--prompt-version", choices=["v1", "v2"], default="v1",
        help="프롬프트 버전: v1=기존 동작(전체 권한 JSON을 별도 system 메시지로 전달), "
             "v2=요청 role의 권한만 user 메시지에 포함하고 DDL 기반 system 프롬프트 사용",
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

    # placeholder 런타임 값: 인자로 안 주면 DB에서 기본값(첫 환자/의사)을 끼워 넣는다
    patient_id = args.current_user_patient_id
    provider_id = args.current_user_provider_id
    if patient_id is None or provider_id is None:
        d_pid, d_prov = resolve_default_placeholders(args.db)
        patient_id = patient_id if patient_id is not None else d_pid
        provider_id = provider_id if provider_id is not None else d_prov
        print(f"[placeholder] patient={patient_id} provider={provider_id}", file=sys.stderr)

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
                current_user_patient_id=patient_id,
                current_user_provider_id=provider_id,
                db_path=args.db,
                prompt_path=args.prompt_path,
                permission_path=args.permission_path,
                prompt_version=args.prompt_version,
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

    # scenario_id를 직접 안 주면 scenarios_medical.json에서 role+request 완전일치로 자동 부여
    scenario_id = args.scenario_id or lookup_scenario_id(role, request)

    try:
        record = generate_sql(
            user_request=request,
            user_role=role,
            model=args.model,
            current_user_patient_id=patient_id,
            current_user_provider_id=provider_id,
            db_path=args.db,
            prompt_path=args.prompt_path,
            permission_path=args.permission_path,
            prompt_version=args.prompt_version,
            scenario_id=scenario_id,
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
