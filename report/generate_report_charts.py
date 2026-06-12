#!/usr/bin/env python3
"""report_pos_financial_v1.jsonl 분석 차트를 생성한다."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_PATH = SCRIPT_DIR.parent / "evaluation" / "report_pos_financial_v1.jsonl"
FIG_DIR = SCRIPT_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.15,
})

ROLE_ORDER = [
    "admin", "compliance", "branch_manager", "loan_officer",
    "teller", "customer_service", "data_analyst", "auditor", "customer",
]
ROLE_LABELS = [
    "Admin (Lv1)", "Compliance (Lv2)", "Branch Mgr (Lv3)", "Loan Officer (Lv4)",
    "Teller (Lv5)", "Cust. Service (Lv6)", "Data Analyst (Lv7)", "Auditor (Lv8)", "Customer (Lv9)",
]


def load_report():
    records = []
    with REPORT_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def get_role(sid: str) -> str:
    parts = sid.rsplit("_", 1)
    return parts[0] if len(parts) == 2 else sid


def classify_error(rec: dict) -> str:
    if rec["match"]:
        return "match"
    reason = rec.get("reason", "")
    if "status_mismatch" in reason:
        gs = rec.get("gold_status", "")
        ps = rec.get("pred_status", "")
        if gs == "ALLOW" and ps == "DENY":
            return "false_deny"
        if gs == "DENY" and ps == "ALLOW":
            return "false_allow"
        return "status_error"
    if "column_count_mismatch" in reason:
        return "col_count_mismatch"
    if "missing_rows" in reason or "extra_rows" in reason:
        return "row_mismatch"
    return "other_mismatch"


# ──────────────────────────────────────────────────────────────────────────

def chart1_role_accuracy(records):
    """역할별 Status 일치율 & Match율 그룹 바 차트."""
    role_total = defaultdict(int)
    role_status_ok = defaultdict(int)
    role_match = defaultdict(int)

    for r in records:
        role = get_role(r["scenario_id"])
        role_total[role] += 1
        if r.get("status_match"):
            role_status_ok[role] += 1
        if r["match"]:
            role_match[role] += 1

    x_pos = range(len(ROLE_ORDER))
    status_rates = [role_status_ok[r] / role_total[r] * 100 for r in ROLE_ORDER]
    match_rates = [role_match[r] / role_total[r] * 100 for r in ROLE_ORDER]

    fig, ax = plt.subplots(figsize=(12, 5))
    w = 0.35
    bars1 = ax.bar([x - w / 2 for x in x_pos], status_rates, w, label="Status Accuracy", color="#4C9BE8")
    bars2 = ax.bar([x + w / 2 for x in x_pos], match_rates, w, label="Final Match", color="#2ECC71")

    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{bar.get_height():.0f}%", ha="center", va="bottom", fontsize=8)
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{bar.get_height():.0f}%", ha="center", va="bottom", fontsize=8)

    ax.set_xticks(list(x_pos))
    ax.set_xticklabels(ROLE_LABELS, rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Accuracy by Role", fontsize=13, fontweight="bold")
    ax.legend(loc="upper right")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(100))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.savefig(FIG_DIR / "role_accuracy.png")
    plt.close(fig)


def chart2_error_type_pie(records):
    """오류 유형 파이 차트."""
    cats = Counter()
    for r in records:
        cats[classify_error(r)] += 1

    labels_map = {
        "match": "Match",
        "false_deny": "False Deny\n(ALLOW→DENY)",
        "false_allow": "False Allow\n(DENY→ALLOW)",
        "status_error": "Status Error",
        "col_count_mismatch": "Column Count\nMismatch",
        "row_mismatch": "Row Mismatch",
        "other_mismatch": "Other",
    }
    colors_map = {
        "match": "#2ECC71",
        "false_deny": "#E74C3C",
        "false_allow": "#E67E22",
        "status_error": "#9B59B6",
        "col_count_mismatch": "#3498DB",
        "row_mismatch": "#F1C40F",
        "other_mismatch": "#95A5A6",
    }
    order = ["match", "false_deny", "false_allow", "status_error",
             "col_count_mismatch", "row_mismatch", "other_mismatch"]
    labels = []
    sizes = []
    colors = []
    for key in order:
        if cats.get(key, 0) > 0:
            labels.append(labels_map[key])
            sizes.append(cats[key])
            colors.append(colors_map[key])

    fig, ax = plt.subplots(figsize=(7, 7))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct=lambda p: f"{p:.1f}%\n({int(round(p * sum(sizes) / 100))})",
        startangle=90, textprops={"fontsize": 10},
    )
    for at in autotexts:
        at.set_fontsize(9)
    ax.set_title("Error Type Distribution (71 scenarios)", fontsize=13, fontweight="bold")

    fig.savefig(FIG_DIR / "error_type_pie.png")
    plt.close(fig)


def chart3_allow_deny_confusion(records):
    """ALLOW/DENY confusion matrix 히트맵."""
    matrix = defaultdict(int)
    for r in records:
        gs = r.get("gold_status", "?")
        ps = r.get("pred_status", "?")
        if ps == "ERROR":
            ps = "ERROR"
        matrix[(gs, ps)] += 1

    labels = ["ALLOW", "DENY", "ERROR"]
    data = [[matrix.get((g, p), 0) for p in labels] for g in ["ALLOW", "DENY"]]

    fig, ax = plt.subplots(figsize=(5, 3.5))
    im = ax.imshow(data, cmap="YlOrRd", aspect="auto")

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([f"Pred\n{l}" for l in labels], fontsize=10)
    ax.set_yticks(range(2))
    ax.set_yticklabels(["Gold\nALLOW", "Gold\nDENY"], fontsize=10)

    for i in range(2):
        for j in range(len(labels)):
            val = data[i][j]
            color = "white" if val > 10 else "black"
            ax.text(j, i, str(val), ha="center", va="center", fontsize=16, fontweight="bold", color=color)

    ax.set_title("ALLOW / DENY Confusion Matrix", fontsize=13, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7)

    fig.savefig(FIG_DIR / "confusion_matrix.png")
    plt.close(fig)


def chart4_role_error_heatmap(records):
    """역할 x 오류 유형 히트맵."""
    error_types = ["false_deny", "false_allow", "col_count_mismatch", "row_mismatch", "status_error"]
    error_labels = ["False Deny", "False Allow", "Col Mismatch", "Row Mismatch", "Status Error"]

    data = []
    for role in ROLE_ORDER:
        row = []
        role_recs = [r for r in records if get_role(r["scenario_id"]) == role]
        for et in error_types:
            cnt = sum(1 for r in role_recs if classify_error(r) == et)
            row.append(cnt)
        data.append(row)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    im = ax.imshow(data, cmap="Reds", aspect="auto")

    ax.set_xticks(range(len(error_labels)))
    ax.set_xticklabels(error_labels, rotation=30, ha="right", fontsize=9)
    ax.set_yticks(range(len(ROLE_LABELS)))
    ax.set_yticklabels(ROLE_LABELS, fontsize=9)

    for i in range(len(ROLE_ORDER)):
        for j in range(len(error_types)):
            val = data[i][j]
            if val > 0:
                color = "white" if val >= 3 else "black"
                ax.text(j, i, str(val), ha="center", va="center", fontsize=11, fontweight="bold", color=color)

    ax.set_title("Error Type × Role Heatmap", fontsize=13, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7)

    fig.savefig(FIG_DIR / "role_error_heatmap.png")
    plt.close(fig)


def chart5_allow_breakdown(records):
    """ALLOW 시나리오의 세부 결과 Stacked Bar (역할별)."""
    cats = ["match", "false_deny", "col_count_mismatch", "row_mismatch", "other_mismatch"]
    cat_labels = ["Match", "False Deny", "Col Mismatch", "Row Mismatch", "Other"]
    cat_colors = ["#2ECC71", "#E74C3C", "#3498DB", "#F1C40F", "#95A5A6"]

    role_data = {role: Counter() for role in ROLE_ORDER}
    for r in records:
        if r.get("gold_status") != "ALLOW":
            continue
        role = get_role(r["scenario_id"])
        role_data[role][classify_error(r)] += 1

    fig, ax = plt.subplots(figsize=(12, 5))
    x_pos = range(len(ROLE_ORDER))
    bottoms = [0] * len(ROLE_ORDER)

    for cat, label, color in zip(cats, cat_labels, cat_colors):
        vals = [role_data[role].get(cat, 0) for role in ROLE_ORDER]
        ax.bar(x_pos, vals, bottom=bottoms, label=label, color=color, width=0.6)
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(i, bottoms[i] + v / 2, str(v), ha="center", va="center", fontsize=9, fontweight="bold")
        bottoms = [b + v for b, v in zip(bottoms, vals)]

    ax.set_xticks(list(x_pos))
    ax.set_xticklabels(ROLE_LABELS, rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Count")
    ax.set_title("ALLOW Scenario Breakdown by Role", fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.savefig(FIG_DIR / "allow_breakdown.png")
    plt.close(fig)


if __name__ == "__main__":
    records = load_report()
    chart1_role_accuracy(records)
    chart2_error_type_pie(records)
    chart3_allow_deny_confusion(records)
    chart4_role_error_heatmap(records)
    chart5_allow_breakdown(records)
    print(f"Charts saved to {FIG_DIR}")
