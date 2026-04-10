"""Results reporting.

Formats MetricsReport as JSON and Markdown per the reporting specification
in Section 9.7 of the framework.
"""

from __future__ import annotations

import json
from pathlib import Path

from pilot.schemas import DimensionMetrics, MetricsReport, tier_of


def write_json_report(report: MetricsReport, path: Path) -> None:
    """Write the full metrics report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))


def write_markdown_report(report: MetricsReport, path: Path) -> None:
    """Write a human-readable markdown report.

    Conforms to the reporting template in Section 9.7: per-dimension results
    with confidence intervals, aggregate results, and metadata.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_markdown_report(report))


def format_markdown_report(report: MetricsReport) -> str:
    """Format a metrics report as markdown."""
    lines: list[str] = []
    lines.append("# Evaluation Report")
    lines.append("")
    lines.append(f"**Reviewer:** {report.reviewer_model}")
    lines.append(f"**Judge panel:** {', '.join(report.judge_panel)}")
    lines.append(f"**Evaluation set:** {report.evaluation_set}")
    lines.append(f"**Number of PRs:** {report.n_prs}")
    lines.append(f"**Framework version:** {report.framework_version}")
    if report.run_metadata:
        lines.append("")
        lines.append("**Run metadata:**")
        for k, v in report.run_metadata.items():
            lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Aggregate Results")
    lines.append("")
    lines.append(f"| Metric | Value | 95% CI | n |")
    lines.append(f"|---|---|---|---|")
    n_total = report.total_true_positives + report.total_false_negatives
    n_flagged = report.total_true_positives + report.total_false_positives
    lines.append(
        f"| Precision | {_fmt_pct(report.aggregate_precision)} | "
        f"{_fmt_ci(report.aggregate_precision_ci)} | {n_flagged} |"
    )
    lines.append(
        f"| Recall | {_fmt_pct(report.aggregate_recall)} | "
        f"{_fmt_ci(report.aggregate_recall_ci)} | {n_total} |"
    )
    lines.append(f"| F1 | {_fmt_pct(report.aggregate_f1)} | — | — |")
    lines.append(f"| TP | {report.total_true_positives} | — | — |")
    lines.append(f"| FP | {report.total_false_positives} | — | — |")
    lines.append(f"| FN | {report.total_false_negatives} | — | — |")
    # Dimension classification accuracy (framework Section 4.2.4)
    if report.dimension_classification_accuracy is not None:
        lines.append(
            f"| Dimension classification accuracy | "
            f"{_fmt_pct(report.dimension_classification_accuracy)} | "
            f"{_fmt_ci(report.dimension_classification_accuracy_ci)} | "
            f"{report.dimension_classification_tp} |"
        )
    lines.append("")
    lines.append("## Per-Dimension Results")
    lines.append("")
    lines.append(
        "| Dimension | Tier | n | TP | FP | FN | Precision [95% CI] | Recall [95% CI] | F1 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    # Group by tier so Tier 1 dimensions (the most important) appear first.
    by_tier: dict[int, list[DimensionMetrics]] = {1: [], 2: [], 3: []}
    for dm in report.per_dimension:
        by_tier[dm.tier].append(dm)
    for tier in (1, 2, 3):
        for dm in by_tier[tier]:
            lines.append(
                f"| {dm.dimension.value} | {dm.tier} | {dm.n_ground_truth} | "
                f"{dm.true_positives} | {dm.false_positives} | {dm.false_negatives} | "
                f"{_fmt_pct(dm.precision)} {_fmt_ci(dm.precision_ci)} | "
                f"{_fmt_pct(dm.recall)} {_fmt_ci(dm.recall_ci)} | "
                f"{_fmt_pct(dm.f1)} |"
            )
    lines.append("")
    lines.append("## Tier Summary")
    lines.append("")
    lines.append("| Tier | Dimensions | n | TP | FP | FN |")
    lines.append("|---|---|---|---|---|---|")
    for tier in (1, 2, 3):
        dms = by_tier[tier]
        n_gt = sum(dm.n_ground_truth for dm in dms)
        tp = sum(dm.true_positives for dm in dms)
        fp = sum(dm.false_positives for dm in dms)
        fn = sum(dm.false_negatives for dm in dms)
        names = ", ".join(dm.dimension.value for dm in dms)
        lines.append(f"| {tier} | {names} | {n_gt} | {tp} | {fp} | {fn} |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Wilson score 95% confidence intervals are reported for precision and recall."
    )
    lines.append(
        "- F1 is the harmonic mean of precision and recall. CIs for F1 should be computed via "
        "bootstrap BCa (Section 9.1.2); this pilot reports point estimates only."
    )
    lines.append(
        "- Dimensions with zero ground truth issues report null for precision/recall/F1."
    )
    return "\n".join(lines) + "\n"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return ""
    low, high = ci
    return f"[{low * 100:.1f}%, {high * 100:.1f}%]"
