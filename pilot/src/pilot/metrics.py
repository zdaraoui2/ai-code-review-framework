"""Metrics computation for the framework.

Implements Section 4 (metrics) and Section 9 (statistical protocol) of the
measurement framework. Core metrics: precision, recall, F1 per dimension,
with 95% Wilson score confidence intervals for proportions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pilot.matching import MatchingOutcome
from pilot.schemas import (
    ClaimedDimensionMetrics,
    Dimension,
    DimensionMetrics,
    GroundTruthIssue,
    MetricsReport,
    PullRequest,
    ReviewerFinding,
    tier_of,
)


@dataclass(frozen=True)
class _Counts:
    tp: int
    fp: int
    fn: int


def wilson_interval(successes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Compute the Wilson score confidence interval for a proportion.

    This is the CI method required by Section 9.1 of the framework. It is
    robust for small samples and never overshoots [0, 1], unlike the Wald
    (normal approximation) interval.

    Args:
        successes: Number of successes.
        total: Total number of trials.
        confidence: Confidence level (default 0.95 for a 95% CI).

    Returns:
        (lower, upper) bounds of the confidence interval.
    """
    if total == 0:
        return (0.0, 0.0)
    # z-score for the given confidence level (two-sided).
    # 1.96 for 95%, 2.576 for 99%.
    alpha = 1 - confidence
    z = _inverse_normal_cdf(1 - alpha / 2)

    p_hat = successes / total
    denominator = 1 + z**2 / total
    centre = (p_hat + z**2 / (2 * total)) / denominator
    half_width = (
        z * math.sqrt(p_hat * (1 - p_hat) / total + z**2 / (4 * total**2)) / denominator
    )
    return (max(0.0, centre - half_width), min(1.0, centre + half_width))


def _inverse_normal_cdf(p: float) -> float:
    """Inverse of the standard normal CDF.

    Uses the Beasley-Springer-Moro approximation. Accurate enough for CI
    computation at common confidence levels.
    """
    # Coefficients for the approximation.
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(
        ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
    ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def _precision(counts: _Counts) -> float | None:
    denom = counts.tp + counts.fp
    return counts.tp / denom if denom > 0 else None


def _recall(counts: _Counts) -> float | None:
    denom = counts.tp + counts.fn
    return counts.tp / denom if denom > 0 else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def compute_metrics(
    prs: list[PullRequest],
    findings_by_pr: dict[str, list[ReviewerFinding]],
    outcomes: list[MatchingOutcome],
    reviewer_model: str,
    judge_panel: list[str],
    evaluation_set: str,
    run_metadata: dict[str, str] | None = None,
) -> MetricsReport:
    """Compute per-dimension and aggregate metrics.

    For each dimension, counts TPs, FPs, and FNs, then computes precision,
    recall, F1, and Wilson score CIs for precision and recall.

    TPs are matched on the ground truth issue's dimension — when a finding
    matches a GT issue, the match counts toward the GT's dimension, not the
    finding's. This means a reviewer that finds the right issue but classifies
    it in the wrong dimension still gets credit for recall, but the precision
    is counted against the finding's claimed dimension. This is the same
    convention used by c-CRAB.
    """
    outcomes_by_pr = {o.pr_id: o for o in outcomes}
    findings_lookup: dict[str, ReviewerFinding] = {}
    for pr_findings in findings_by_pr.values():
        for f in pr_findings:
            findings_lookup[f.finding_id] = f

    # Per-dimension TPs, FPs, FNs
    per_dim: dict[Dimension, _Counts] = {
        d: _Counts(tp=0, fp=0, fn=0) for d in Dimension
    }

    # Dimension classification accuracy counters:
    # correct_dimension = matched findings where reviewer dimension == GT dimension
    # matched_total = total matched findings (i.e., true positives)
    correct_dimension = 0
    matched_total = 0

    for pr in prs:
        outcome = outcomes_by_pr[pr.pr_id]
        gt_by_id = {gt.issue_id: gt for gt in pr.ground_truth}
        for match in outcome.matches:
            gt_issue = gt_by_id[match.ground_truth_issue_id]
            if match.finding_id is not None:
                # TP: attribute to the GT issue's dimension.
                current = per_dim[gt_issue.dimension]
                per_dim[gt_issue.dimension] = _Counts(
                    tp=current.tp + 1, fp=current.fp, fn=current.fn
                )
                # Dimension classification accuracy check
                matched_finding = findings_lookup.get(match.finding_id)
                if matched_finding is not None:
                    matched_total += 1
                    if matched_finding.dimension == gt_issue.dimension:
                        correct_dimension += 1
            else:
                # FN: attribute to the GT issue's dimension.
                current = per_dim[gt_issue.dimension]
                per_dim[gt_issue.dimension] = _Counts(
                    tp=current.tp, fp=current.fp, fn=current.fn + 1
                )

        # Unmatched findings are FPs, attributed to the finding's claimed dimension.
        for finding in outcome.unmatched_findings:
            current = per_dim[finding.dimension]
            per_dim[finding.dimension] = _Counts(
                tp=current.tp, fp=current.fp + 1, fn=current.fn
            )

    # --- Finding-perspective (claimed dimension) attribution ---
    # Second pass: attribute TPs to the finding's claimed dimension, not the
    # GT's. This gives an honest answer to "when the reviewer claims dimension
    # X, how often is it a real issue?" Recall is not meaningful here because
    # FNs have no claimed dimension.
    claimed_tp: dict[Dimension, int] = {dim: 0 for dim in Dimension}
    claimed_fp: dict[Dimension, int] = {dim: 0 for dim in Dimension}

    for pr in prs:
        outcome = outcomes_by_pr[pr.pr_id]
        for match in outcome.matches:
            if match.finding_id is not None:
                matched_finding = findings_lookup.get(match.finding_id)
                if matched_finding is not None:
                    claimed_tp[matched_finding.dimension] += 1
        for finding in outcome.unmatched_findings:
            claimed_fp[finding.dimension] += 1

    # Build per-dimension metrics
    per_dimension_metrics: list[DimensionMetrics] = []
    total_tp = total_fp = total_fn = 0

    for dim in Dimension:
        counts = per_dim[dim]
        total_tp += counts.tp
        total_fp += counts.fp
        total_fn += counts.fn

        n_gt = counts.tp + counts.fn
        p = _precision(counts)
        r = _recall(counts)
        f1 = _f1(p, r)

        p_ci = None
        r_ci = None
        if counts.tp + counts.fp > 0:
            p_ci = wilson_interval(counts.tp, counts.tp + counts.fp)
        if n_gt > 0:
            r_ci = wilson_interval(counts.tp, n_gt)

        per_dimension_metrics.append(
            DimensionMetrics(
                dimension=dim,
                tier=tier_of(dim),
                n_ground_truth=n_gt,
                true_positives=counts.tp,
                false_positives=counts.fp,
                false_negatives=counts.fn,
                precision=p,
                recall=r,
                f1=f1,
                precision_ci=p_ci,
                recall_ci=r_ci,
            )
        )

    # Build claimed-dimension metrics
    claimed_dimension_metrics: list[ClaimedDimensionMetrics] = []
    for dim in Dimension:
        dim_claimed_tp = claimed_tp[dim]
        dim_claimed_fp = claimed_fp[dim]
        total_claims = dim_claimed_tp + dim_claimed_fp
        claim_precision = dim_claimed_tp / total_claims if total_claims > 0 else None
        claim_precision_ci = (
            wilson_interval(dim_claimed_tp, total_claims) if total_claims > 0 else None
        )
        claimed_dimension_metrics.append(
            ClaimedDimensionMetrics(
                dimension=dim,
                tier=tier_of(dim),
                true_positives=dim_claimed_tp,
                false_positives=dim_claimed_fp,
                total_claims=total_claims,
                precision=claim_precision,
                precision_ci=claim_precision_ci,
            )
        )

    # Aggregate
    agg_counts = _Counts(tp=total_tp, fp=total_fp, fn=total_fn)
    agg_p = _precision(agg_counts)
    agg_r = _recall(agg_counts)
    agg_f1 = _f1(agg_p, agg_r)
    agg_p_ci = (
        wilson_interval(total_tp, total_tp + total_fp) if (total_tp + total_fp) > 0 else None
    )
    agg_r_ci = (
        wilson_interval(total_tp, total_tp + total_fn) if (total_tp + total_fn) > 0 else None
    )

    # Dimension classification accuracy
    dim_accuracy = correct_dimension / matched_total if matched_total > 0 else None
    dim_accuracy_ci = (
        wilson_interval(correct_dimension, matched_total) if matched_total > 0 else None
    )

    # ── Visible recall ──────────────────────────────────────────────
    # Collect all excluded GT issue IDs across truncated PRs. These are
    # GT issues the reviewer could not see because the diff was truncated.
    # They still count toward total recall (aggregate_recall above) but
    # are excluded from visible recall.
    all_excluded_gt_ids: set[str] = set()
    truncated_pr_count = sum(1 for pr_item in prs if pr_item.truncated)
    for pr_item in prs:
        if pr_item.truncated and pr_item.excluded_gt_ids:
            all_excluded_gt_ids.update(pr_item.excluded_gt_ids)

    visible_recall: float | None = None
    visible_recall_ci_val: tuple[float, float] | None = None

    if all_excluded_gt_ids:
        # Recount FNs excluding the invisible GT issues.
        visible_fn = total_fn
        for pr_item in prs:
            outcome = outcomes_by_pr[pr_item.pr_id]
            for match in outcome.matches:
                if match.finding_id is None and match.ground_truth_issue_id in all_excluded_gt_ids:
                    visible_fn -= 1

        visible_total = total_tp + visible_fn
        if visible_total > 0:
            visible_recall = total_tp / visible_total
            visible_recall_ci_val = wilson_interval(total_tp, visible_total)

    return MetricsReport(
        reviewer_model=reviewer_model,
        judge_panel=judge_panel,
        evaluation_set=evaluation_set,
        n_prs=len(prs),
        per_dimension=per_dimension_metrics,
        per_dimension_by_claim=claimed_dimension_metrics,
        total_true_positives=total_tp,
        total_false_positives=total_fp,
        total_false_negatives=total_fn,
        aggregate_precision=agg_p,
        aggregate_recall=agg_r,
        aggregate_f1=agg_f1,
        aggregate_precision_ci=agg_p_ci,
        aggregate_recall_ci=agg_r_ci,
        visible_recall=visible_recall,
        visible_recall_ci=visible_recall_ci_val,
        truncated_pr_count=truncated_pr_count,
        excluded_gt_issue_count=len(all_excluded_gt_ids),
        dimension_classification_tp=matched_total,
        dimension_classification_accuracy=dim_accuracy,
        dimension_classification_accuracy_ci=dim_accuracy_ci,
        run_metadata=run_metadata or {},
    )
