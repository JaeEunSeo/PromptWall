import json
import re
from pathlib import Path
import pandas as pd


REPORT_PATH = "report_financial.jsonl"
QUERY_PATH = "query_generator_results.jsonl"
OUTPUT_PATH = "analysis_summary.json"


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return pd.DataFrame(rows)


def infer_role(scenario_id):
    # 예: admin_001, compliance_002, branch_manager_001
    return re.sub(r"_\d+$", "", scenario_id)


def infer_sql_type(sql):
    if not isinstance(sql, str) or not sql.strip():
        return "NONE"
    return sql.strip().split()[0].upper()


def safe_mean(series):
    if len(series) == 0:
        return None
    return float(series.mean())


report = load_jsonl(REPORT_PATH)
queries = load_jsonl(QUERY_PATH)

# query_generator_results.jsonl의 status/sql을 report에 붙임
df = report.merge(
    queries[["scenario_id", "status", "sql"]],
    on="scenario_id",
    how="left",
    suffixes=("", "_generated")
)

df["role"] = df["scenario_id"].apply(infer_role)
df["sql_type"] = df["sql"].apply(infer_sql_type)

df["false_allow"] = (
    (df["gold_status"] == "DENY") &
    (df["pred_status"] == "ALLOW")
)

df["false_deny"] = (
    (df["gold_status"] == "ALLOW") &
    (df["pred_status"] == "DENY")
)

summary = {
    "overall": {
        "total_scenarios": int(len(df)),
        "allow_gold_count": int((df["gold_status"] == "ALLOW").sum()),
        "deny_gold_count": int((df["gold_status"] == "DENY").sum()),
        "match_count": int(df["match"].sum()),
        "match_rate": safe_mean(df["match"]),
        "status_match_count": int(df["status_match"].sum()),
        "status_accuracy": safe_mean(df["status_match"]),
        "result_match_count": int(df["result_match"].sum()),
        "result_accuracy": safe_mean(df["result_match"]),
        "false_allow_count": int(df["false_allow"].sum()),
        "false_deny_count": int(df["false_deny"].sum()),
    },

    "by_role": df.groupby("role").agg(
        scenario_count=("scenario_id", "count"),
        match_rate=("match", "mean"),
        status_accuracy=("status_match", "mean"),
        result_accuracy=("result_match", "mean"),
        false_allow_count=("false_allow", "sum"),
        false_deny_count=("false_deny", "sum"),
    ).reset_index().to_dict(orient="records"),

    "by_sql_type": df.groupby("sql_type").agg(
        scenario_count=("scenario_id", "count"),
        match_rate=("match", "mean"),
        status_accuracy=("status_match", "mean"),
        result_accuracy=("result_match", "mean"),
        false_allow_count=("false_allow", "sum"),
        false_deny_count=("false_deny", "sum"),
    ).reset_index().to_dict(orient="records"),

    "failures": df[df["match"] == False][[
        "scenario_id",
        "role",
        "gold_status",
        "pred_status",
        "status_match",
        "result_match",
        "reason",
        "gold_row_count",
        "pred_row_count",
        "sql_type",
        "sql",
    ]].to_dict(orient="records"),

    "false_allow_cases": df[df["false_allow"]][[
        "scenario_id",
        "role",
        "reason",
        "sql_type",
        "sql",
    ]].to_dict(orient="records"),

    "false_deny_cases": df[df["false_deny"]][[
        "scenario_id",
        "role",
        "reason",
        "sql_type",
        "sql",
    ]].to_dict(orient="records"),
}

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(json.dumps(summary, ensure_ascii=False, indent=2))
print(f"\nSaved to {OUTPUT_PATH}")