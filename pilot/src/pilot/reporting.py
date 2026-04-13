"""Results reporting.

Formats MetricsReport as JSON and Markdown per the reporting specification
in Section 9.7 of the framework.
"""

from __future__ import annotations

import json
from pathlib import Path

from pilot.schemas import ClaimedDimensionMetrics, DimensionMetrics, MetricsReport, tier_of


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
    recall_label = "Recall (all GT)" if report.visible_recall is not None else "Recall"
    lines.append(
        f"| {recall_label} | {_fmt_pct(report.aggregate_recall)} | "
        f"{_fmt_ci(report.aggregate_recall_ci)} | {n_total} |"
    )
    if report.visible_recall is not None:
        visible_n = report.total_true_positives + (
            report.total_false_negatives - report.excluded_gt_issue_count
        )
        lines.append(
            f"| Recall (visible GT only) | {_fmt_pct(report.visible_recall)} | "
            f"{_fmt_ci(report.visible_recall_ci)} | {visible_n} |"
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
    lines.append("## Detection by Ground Truth Dimension")
    lines.append("")
    lines.append(
        "TPs are attributed to the GT issue's dimension. "
        "This view is authoritative for **recall**: "
        "\"what fraction of concurrency bugs were found?\""
    )
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

    # Claimed-dimension table (finding perspective)
    if report.per_dimension_by_claim:
        lines.append("")
        lines.append("## Detection by Claimed Dimension")
        lines.append("")
        lines.append(
            "TPs are attributed to the finding's claimed dimension. "
            "This view is authoritative for **precision**: "
            "\"when the reviewer says concurrency, is it right?\""
        )
        lines.append("")
        lines.append(
            "| Dimension | Tier | TP | FP | Total claims | Precision [95% CI] |"
        )
        lines.append("|---|---|---|---|---|---|")
        by_claim_tier: dict[int, list[ClaimedDimensionMetrics]] = {1: [], 2: [], 3: []}
        for cdm in report.per_dimension_by_claim:
            by_claim_tier[cdm.tier].append(cdm)
        for tier in (1, 2, 3):
            for cdm in by_claim_tier[tier]:
                if cdm.total_claims > 0:
                    lines.append(
                        f"| {cdm.dimension.value} | {cdm.tier} | "
                        f"{cdm.true_positives} | {cdm.false_positives} | "
                        f"{cdm.total_claims} | "
                        f"{_fmt_pct(cdm.precision)} {_fmt_ci(cdm.precision_ci)} |"
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
    # Data quality warnings — flag issues that may affect result reliability.
    data_quality_warnings = _collect_data_quality_warnings(report)
    if data_quality_warnings:
        lines.append("")
        lines.append("## Data Quality Warnings")
        lines.append("")
        for warning in data_quality_warnings:
            lines.append(f"- **Warning:** {warning}")

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
    if report.truncated_pr_count > 0:
        lines.append(
            f"- {report.truncated_pr_count} PR(s) had diffs truncated. "
            f"{report.excluded_gt_issue_count} GT issue(s) in truncated regions "
            f"are excluded from visible recall but still count toward total recall."
        )
    return "\n".join(lines) + "\n"


_SEVERITY_COERCION_RATE_THRESHOLD = 0.20


def _collect_data_quality_warnings(report: MetricsReport) -> list[str]:
    """Check run metadata for data quality issues worth surfacing.

    Currently checks:
    - Severity coercion rate > 20% indicates the reviewer model is
      frequently returning non-standard severity values.
    """
    warnings: list[str] = []
    rate_str = report.run_metadata.get("severity_coercion_rate", "")
    if rate_str:
        try:
            # Parse "25.00%" -> 0.25
            rate = float(rate_str.rstrip("%")) / 100.0
        except (ValueError, TypeError):
            rate = 0.0
        if rate > _SEVERITY_COERCION_RATE_THRESHOLD:
            coercion_count = report.run_metadata.get("severity_coercion_count", "?")
            warnings.append(
                f"Severity coercion rate is {rate_str} ({coercion_count} findings "
                f"required coercion). The reviewer model is returning non-standard "
                f"severity values. Severity-dependent metrics may be unreliable."
            )
    return warnings


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return ""
    low, high = ci
    return f"[{low * 100:.1f}%, {high * 100:.1f}%]"
