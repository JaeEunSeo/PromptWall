#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy-Aware SQL Query Generator 클라이언트 (의료 도메인) — OpenAI 버전.

- system prompt : prompt/query_generator_medical.txt
- permission    : data/medical/permissions_medical.json  (요청 role의 권한 블록만 추출)
- user prompt   : User Role + User Request (2개를 따로 입력받음)

OpenAI Chat Completions API로 호출하여, 권한을 준수하는 SQL을 생성하거나
권한을 초과하면 거부(JSON)한다.

사용 예:
  # 인자로 직접 전달
  python query_generator_client.py --role nurse \
      --request "방금 측정한 혈압 120/80을 환자 observations에 기록해줘"

  # 인자를 생략하면 대화형으로 role / request를 입력받음
  python query_generator_client.py

선행 준비:
  pip install openai
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import openai
from openai import OpenAI

# ── 경로 (이 스크립트 기준 상대 경로) ──────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = BASE_DIR / "prompt" / "query_generator_medical.txt"
PERMISSIONS_PATH = BASE_DIR / "data" / "medical" / "permissions_medical.json"
SCENARIOS_PATH = BASE_DIR / "data" / "medical" / "scenarios_medical.json"

# 필요 시 다른 OpenAI 모델로 변경 (예: "gpt-4o-mini", "gpt-4.1")
MODEL = "gpt-4o-mini"


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def load_permissions() -> dict:
    with open(PERMISSIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_role_permissions(permissions: dict, role: str) -> dict:
    """요청 role의 권한 블록(table_permissions 포함)만 반환."""
    roles = permissions.get("roles", {})
    if role not in roles:
        available = ", ".join(sorted(roles))
        raise ValueError(f"알 수 없는 role: '{role}'.\n사용 가능한 role: {available}")
    return roles[role]


def build_user_message(role: str, request: str, role_permissions: dict) -> str:
    """query_generator_medical.txt의 Input Format에 맞춰 사용자 메시지 구성."""
    permission_json = json.dumps(role_permissions, ensure_ascii=False, indent=2)
    return (
        f"User Request: {request}\n"
        f"User Role: {role}\n"
        f"Permission List:\n{permission_json}"
    )


def generate_sql(role: str, request: str, *, client: OpenAI | None = None) -> dict:
    """role + request를 받아 정책 인지 SQL 생성 결과(JSON dict)를 반환."""
    client = client or OpenAI()
    system_prompt = load_system_prompt()
    permissions = load_permissions()
    role_permissions = get_role_permissions(permissions, role)
    user_message = build_user_message(role, request, role_permissions)

    response = client.chat.completions.create(
        model=MODEL,
        # gpt-5 계열은 'max_tokens' 대신 'max_completion_tokens'를 사용
        max_completion_tokens=4096,
        # gpt-5 계열은 temperature 기본값(1)만 허용하므로 지정하지 않음
        response_format={"type": "json_object"},  # JSON만 출력하도록 강제
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    text = (response.choices[0].message.content or "").strip()

    # json_object 모드면 항상 유효 JSON이지만, 방어적으로 파싱
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError(f"모델 응답을 JSON으로 파싱하지 못했습니다:\n{text}")


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


def predict_record(role: str, request: str, scenario_id: str | None = None,
                   *, client: OpenAI | None = None) -> dict:
    """answer_checker가 읽을 예측 레코드(JSON)를 만든다."""
    # scenario_id를 직접 받지 않았다면 scenarios_medical.json에서 매칭 시도
    if scenario_id is None:
        scenario_id = lookup_scenario_id(role, request)
    result = generate_sql(role, request, client=client)
    # 모델 원본 출력(ALLOW: status/sql, DENY: status/category/reason) 앞에 scenario_id만 붙인다
    return {"scenario_id": scenario_id, **result}


def run_batch(batch_path: Path, out_path: Path, *, lang: str = "ko") -> int:
    """gold/scenario JSONL을 읽어 모든 항목에 대해 예측을 만들고 JSONL로 저장."""
    client = OpenAI()
    req_key = "request_ko" if lang == "ko" else "request_en"
    n = 0
    with open(batch_path, encoding="utf-8") as fin, \
         open(out_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            sid = item.get("scenario_id")
            role = item["role"]
            request = item.get(req_key) or item.get("request_ko") or item.get("request_en")
            try:
                rec = predict_record(role, request, sid, client=client)
            except Exception as e:  # 개별 실패는 레코드에 기록하고 계속
                rec = {"scenario_id": sid, "status": "ERROR", "reason": str(e)}
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            n += 1
            print(f"[{n}] {sid}: {rec.get('status')}", file=sys.stderr)
    print(f"Wrote {n} predictions to {out_path}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="의료 도메인 정책 인지 SQL 생성기 (OpenAI API)"
    )
    parser.add_argument("--role", help="사용자 역할 (예: nurse, attending_physician, patient)")
    parser.add_argument("--request", help="자연어 요청")
    parser.add_argument("--scenario-id", help="단건 저장 시 함께 기록할 시나리오 ID")
    parser.add_argument("--batch", type=Path,
                        help="gold/scenario JSONL 경로. 모든 항목에 대해 예측을 생성")
    parser.add_argument("--out", type=Path,
                        help="결과 저장 경로(.json 단건 / .jsonl 배치)")
    parser.add_argument("--lang", choices=["ko", "en"], default="ko",
                        help="배치 모드에서 사용할 요청 언어 (기본 ko)")
    args = parser.parse_args()

    # ── 배치 모드 ──────────────────────────────────────────────────────────
    if args.batch:
        if not args.out:
            print("--batch 사용 시 --out(.jsonl)이 필요합니다.", file=sys.stderr)
            return 2
        try:
            return run_batch(args.batch, args.out, lang=args.lang)
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
        record = predict_record(role, request, args.scenario_id)
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
        args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"Saved to {args.out}", file=sys.stderr)
    print(json.dumps(record, ensure_ascii=False, indent=2))

    # 종료 코드로 ALLOW/DENY 구분 (파이프라인 연동용): ALLOW=0, DENY=10
    return 0 if record.get("status") == "ALLOW" else 10


if __name__ == "__main__":
    sys.exit(main())
