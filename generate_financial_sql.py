#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompt" / "query_generator_financial.txt"
DEFAULT_PERMISSION_PATH = PROJECT_ROOT / "data" / "financial" / "permission_list.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "financial" / "financial.sqlite"
DEFAULT_MODEL = "gpt-5.4-nano"


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_permission_prompt(path: Path) -> str:
    permissions: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    permission_json = json.dumps(permissions, ensure_ascii=False, indent=2)
    return f"Permission List:\n{permission_json}"


def build_runtime_placeholder_prompt(current_user_client_id: int | None) -> str | None:
    if current_user_client_id is None:
        return None
    return (
        "Runtime Placeholder Values:\n"
        f"- {{current_user_client_id}}: {current_user_client_id}\n\n"
        "When applying row_filter permissions, replace {current_user_client_id} "
        "with this runtime value."
    )


def validate_runtime_context(user_role: str, current_user_client_id: int | None) -> None:
    if user_role.lower() == "customer" and current_user_client_id is None:
        raise ValueError("customer role requires --current-user-client-id.")


def normalize_sql_for_sqlite(sql: str) -> str:
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
    cleaned = strip_leading_sql_comments(sql).lower()
    return cleaned.startswith("select") or cleaned.startswith("with")


def normalize_sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    return value


def execute_select_as_dicts(db_path: Path, sql: str) -> list[dict[str, Any]]:
    normalized_sql = normalize_sql_for_sqlite(sql)
    if not is_select_query(normalized_sql):
        raise ValueError("Only SELECT queries can be executed by generate_financial_sql.py.")

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


def attach_select_view_if_needed(model_response: str, db_path: Path) -> str:
    parsed = json.loads(model_response)
    if not isinstance(parsed, dict):
        return model_response

    status = str(parsed.get("status", "")).upper()
    sql = parsed.get("sql")
    if status != "ALLOW" or not isinstance(sql, str):
        return model_response

    normalized_sql = normalize_sql_for_sqlite(sql)
    parsed["sql"] = normalized_sql
    if is_select_query(normalized_sql):
        rows = execute_select_as_dicts(db_path, normalized_sql)
        return json.dumps(
            {"status": parsed["status"], "sql": normalized_sql, "view": rows},
            ensure_ascii=False,
            sort_keys=False,
        )

    return json.dumps(parsed, ensure_ascii=False, sort_keys=False)


def generate_sql(
    user_request: str,
    user_role: str,
    model: str,
    current_user_client_id: int | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    permission_path: Path = DEFAULT_PERMISSION_PATH,
) -> str:
    validate_runtime_context(user_role, current_user_client_id)

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI SDK first: pip install openai") from exc

    client = OpenAI()
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
    return attach_select_view_if_needed(content, db_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a policy-aware SQL query for the financial database."
    )
    parser.add_argument("--role", required=True, help="User role, e.g. teller or admin.")
    parser.add_argument("--request", required=True, help="Natural language user request.")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        help=f"OpenAI model to use. Defaults to OPENAI_MODEL or {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--current-user-client-id",
        type=int,
        help="Runtime value for {current_user_client_id}; required when --role customer.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite DB path used to execute ALLOW SELECT queries.",
    )
    parser.add_argument(
        "--prompt-path",
        type=Path,
        default=DEFAULT_PROMPT_PATH,
        help="Path to the query generator system prompt.",
    )
    parser.add_argument(
        "--permission-path",
        type=Path,
        default=DEFAULT_PERMISSION_PATH,
        help="Path to the financial permission JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_sql(
        user_request=args.request,
        user_role=args.role,
        model=args.model,
        current_user_client_id=args.current_user_client_id,
        db_path=args.db,
        prompt_path=args.prompt_path,
        permission_path=args.permission_path,
    )
    print(result)


if __name__ == "__main__":
    main()
