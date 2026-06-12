import json
import re
import pandas as pd

REPORT_PATH = "report_medical.jsonl"
QUERY_PATH = "query_generator_results_medical.jsonl"

def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return pd.DataFrame(rows)

report = load_jsonl(REPORT_PATH)
generated = load_jsonl(QUERY_PATH)

df = report.merge(
    generated[["scenario_id", "status", "sql"]],
    on="scenario_id",
    how="left"
)

df["role"] = (
    df["scenario_id"]
    .str.replace(r"_\d+$", "", regex=True)
)

def sql_type(sql):
    if not isinstance(sql, str):
        return "NONE"
    return sql.strip().split()[0].upper()

df["sql_type"] = df["sql"].apply(sql_type)

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
        "total_scenarios": len(df),
        "match_rate": float(df["match"].mean()),
        "status_accuracy": float(df["status_match"].mean()),
        "result_accuracy": float(df["result_match"].mean()),
        "false_allow_count": int(df["false_allow"].sum()),
        "false_deny_count": int(df["false_deny"].sum()),
    },

    "role_metrics": (
        df.groupby("role")
          .agg(
              scenario_count=("scenario_id","count"),
              match_rate=("match","mean"),
              status_accuracy=("status_match","mean"),
              result_accuracy=("result_match","mean"),
              false_allow_count=("false_allow","sum"),
              false_deny_count=("false_deny","sum"),
          )
          .reset_index()
          .to_dict("records")
    ),

    "sql_type_metrics": (
        df.groupby("sql_type")
          .agg(
              scenario_count=("scenario_id","count"),
              match_rate=("match","mean"),
              failure_count=("match", lambda x:(~x).sum())
          )
          .reset_index()
          .to_dict("records")
    ),

    "failures": (
        df[df["match"] == False]
        [[
            "scenario_id",
            "role",
            "gold_status",
            "pred_status",
            "reason",
            "gold_row_count",
            "pred_row_count",
            "sql"
        ]]
        .to_dict("records")
    )
}

with open(
    "analysis_summary_medical.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)