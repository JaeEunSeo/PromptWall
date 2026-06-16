#!/usr/bin/env python3
"""medical 평가 리포트(report_pos_medical_*.jsonl) 분석 차트를 생성한다.

사용:
  python report/generate_report_charts_medical.py                         # 기본 v2
  python report/generate_report_charts_medical.py \
      --report evaluation/report_pos_medical_v1.jsonl \
      --outdir report/figures_medical_v1
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.15,
})

# 의료 도메인 13개 역할 (권한 레벨 순)
ROLE_ORDER = [
    "system_admin", "privacy_officer", "hospital_director", "attending_physician",
    "nurse", "pharmacist", "clinical_technician", "medical_coder",
    "registration_clerk", "insurance_examiner", "research_analyst",
    "external_auditor", "patient",
]
ROLE_LABELS = [
    "System Admin (Lv1)", "Privacy Officer (Lv2)", "Hospital Dir (Lv3)", "Att. Physician (Lv4)",
    "Nurse (Lv5)", "Pharmacist (Lv6)", "Clinical Tech (Lv7)", "Medical Coder (Lv8)",
    "Registration (Lv9)", "Insur. Examiner (Lv10)", "Research Analyst (Lv11)",
    "External Auditor (Lv12)", "Patient (Lv13)",
]


def load_report(report_path: Path):
    records = []
    with report_path.open() as f:
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

def chart1_role_accuracy(records, fig_dir):
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
    status_rates = [role_status_ok[r] / role_total[r] * 100 if role_total[r] else 0 for r in ROLE_ORDER]
    match_rates = [role_match[r] / role_total[r] * 100 if role_total[r] else 0 for r in ROLE_ORDER]

    fig, ax = plt.subplots(figsize=(14, 5))
    w = 0.4
    bars1 = ax.bar([x - w / 2 for x in x_pos], status_rates, w, label="Status Accuracy", color="#4C9BE8")
    bars2 = ax.bar([x + w / 2 for x in x_pos], match_rates, w, label="Final Match", color="#2ECC71")
    for bars in (bars1, bars2):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{bar.get_height():.0f}%", ha="center", va="bottom", fontsize=7)

    ax.set_xticks(list(x_pos))
    ax.set_xticklabels(ROLE_LABELS, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Accuracy by Role (Medical)", fontsize=13, fontweight="bold")
    ax.legend(loc="upper right")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(100))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.savefig(fig_dir / "role_accuracy.png")
    plt.close(fig)


def chart2_error_type_pie(records, fig_dir):
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
        "match": "#2ECC71", "false_deny": "#E74C3C", "false_allow": "#E67E22",
        "status_error": "#9B59B6", "col_count_mismatch": "#3498DB",
        "row_mismatch": "#F1C40F", "other_mismatch": "#95A5A6",
    }
    order = ["match", "false_deny", "false_allow", "status_error",
             "col_count_mismatch", "row_mismatch", "other_mismatch"]
    labels, sizes, colors = [], [], []
    for key in order:
        if cats.get(key, 0) > 0:
            labels.append(labels_map[key]); sizes.append(cats[key]); colors.append(colors_map[key])

    fig, ax = plt.subplots(figsize=(7, 7))
    _, _, autotexts = ax.pie(
        sizes, labels=labels, colors=colors,
        autopct=lambda p: f"{p:.1f}%\n({int(round(p * sum(sizes) / 100))})",
        startangle=90, textprops={"fontsize": 10},
    )
    for at in autotexts:
        at.set_fontsize(9)
    ax.set_title(f"Error Type Distribution ({len(records)} scenarios)", fontsize=13, fontweight="bold")
    fig.savefig(fig_dir / "error_type_pie.png")
    plt.close(fig)


def chart3_allow_deny_confusion(records, fig_dir):
    """ALLOW/DENY confusion matrix 히트맵."""
    matrix = defaultdict(int)
    for r in records:
        matrix[(r.get("gold_status", "?"), r.get("pred_status", "?"))] += 1

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
    ax.set_title("ALLOW / DENY Confusion Matrix (Medical)", fontsize=12, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.savefig(fig_dir / "confusion_matrix.png")
    plt.close(fig)


def chart4_role_error_heatmap(records, fig_dir):
    """역할 x 오류 유형 히트맵."""
    error_types = ["false_deny", "false_allow", "col_count_mismatch", "row_mismatch", "status_error", "other_mismatch"]
    error_labels = ["False Deny", "False Allow", "Col Mismatch", "Row Mismatch", "Status Error", "Other"]

    data = []
    for role in ROLE_ORDER:
        role_recs = [r for r in records if get_role(r["scenario_id"]) == role]
        data.append([sum(1 for r in role_recs if classify_error(r) == et) for et in error_types])

    fig, ax = plt.subplots(figsize=(9, 6.5))
    im = ax.imshow(data, cmap="Reds", aspect="auto")
    ax.set_xticks(range(len(error_labels)))
    ax.set_xticklabels(error_labels, rotation=30, ha="right", fontsize=9)
    ax.set_yticks(range(len(ROLE_LABELS)))
    ax.set_yticklabels(ROLE_LABELS, fontsize=8)
    for i in range(len(ROLE_ORDER)):
        for j in range(len(error_types)):
            val = data[i][j]
            if val > 0:
                color = "white" if val >= 3 else "black"
                ax.text(j, i, str(val), ha="center", va="center", fontsize=10, fontweight="bold", color=color)
    ax.set_title("Error Type × Role Heatmap (Medical)", fontsize=13, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.savefig(fig_dir / "role_error_heatmap.png")
    plt.close(fig)


def chart5_allow_breakdown(records, fig_dir):
    """ALLOW 시나리오의 세부 결과 Stacked Bar (역할별)."""
    cats = ["match", "false_deny", "col_count_mismatch", "row_mismatch", "other_mismatch"]
    cat_labels = ["Match", "False Deny", "Col Mismatch", "Row Mismatch", "Other"]
    cat_colors = ["#2ECC71", "#E74C3C", "#3498DB", "#F1C40F", "#95A5A6"]

    role_data = {role: Counter() for role in ROLE_ORDER}
    for r in records:
        if r.get("gold_status") != "ALLOW":
            continue
        role_data[get_role(r["scenario_id"])][classify_error(r)] += 1

    fig, ax = plt.subplots(figsize=(14, 5))
    x_pos = range(len(ROLE_ORDER))
    bottoms = [0] * len(ROLE_ORDER)
    for cat, label, color in zip(cats, cat_labels, cat_colors):
        vals = [role_data[role].get(cat, 0) for role in ROLE_ORDER]
        ax.bar(x_pos, vals, bottom=bottoms, label=label, color=color, width=0.6)
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(i, bottoms[i] + v / 2, str(v), ha="center", va="center", fontsize=8, fontweight="bold")
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.set_xticks(list(x_pos))
    ax.set_xticklabels(ROLE_LABELS, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Count")
    ax.set_title("ALLOW Scenario Breakdown by Role (Medical)", fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.savefig(fig_dir / "allow_breakdown.png")
    plt.close(fig)


def parse_args():
    p = argparse.ArgumentParser(description="medical 평가 리포트 차트 생성")
    p.add_argument("--report", type=Path,
                   default=PROJECT_ROOT / "evaluation" / "report_pos_medical_v2.jsonl",
                   help="채점 리포트 JSONL 경로 (기본: report_pos_medical_v2.jsonl)")
    p.add_argument("--outdir", type=Path,
                   default=SCRIPT_DIR / "figures_medical",
                   help="차트 저장 폴더 (기본: report/figures_medical)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    records = load_report(args.report)
    chart1_role_accuracy(records, args.outdir)
    chart2_error_type_pie(records, args.outdir)
    chart3_allow_deny_confusion(records, args.outdir)
    chart4_role_error_heatmap(records, args.outdir)
    chart5_allow_breakdown(records, args.outdir)
    print(f"Loaded {len(records)} records from {args.report}")
    print(f"Charts saved to {args.outdir}")
