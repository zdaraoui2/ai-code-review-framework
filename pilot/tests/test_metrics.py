"""Tests for metrics computation."""

from __future__ import annotations

import pytest

from pilot.matching import MatchingOutcome
from pilot.metrics import compute_metrics, wilson_interval
from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    MatchResult,
    PullRequest,
    ReviewerFinding,
    Severity,
)


# --- Wilson interval tests ------------------------------------------------


def test_wilson_interval_typical_case():
    # 50% from 10 samples should have a wide CI
    low, high = wilson_interval(5, 10)
    assert 0.0 <= low < 0.5 < high <= 1.0
    assert high - low > 0.4  # Wilson is asymmetric but wide at n=10


def test_wilson_interval_perfect_success():
    low, high = wilson_interval(10, 10)
    assert high == 1.0
    assert low < 1.0  # Wilson gives a non-trivial lower bound


def test_wilson_interval_zero_success():
    low, high = wilson_interval(0, 10)
    assert low == 0.0
    assert high > 0.0  # Wilson gives a non-trivial upper bound


def test_wilson_interval_zero_trials():
    low, high = wilson_interval(0, 0)
    assert (low, high) == (0.0, 0.0)


def test_wilson_interval_half_at_large_n():
    low, high = wilson_interval(500, 1000)
    # At large n, CI should be narrow and centred on 0.5
    assert abs(((low + high) / 2) - 0.5) < 0.02
    assert (high - low) < 0.1


# --- compute_metrics tests ------------------------------------------------


def _make_pr(pr_id: str, issues: list[GroundTruthIssue]) -> PullRequest:
    return PullRequest(
        pr_id=pr_id,
        title="Test",
        language="python",
        change_type=ChangeType.NEW_FEATURE,
        diff="+test",
        ground_truth=issues,
    )


def _make_gt(issue_id: str, pr_id: str, dim: Dimension) -> GroundTruthIssue:
    return GroundTruthIssue(
        issue_id=issue_id,
        pr_id=pr_id,
        dimension=dim,
        severity=Severity.HIGH,
        location=Location(file_path="a.py", start_line=1, end_line=1),
        description="test",
    )


def _make_finding(finding_id: str, pr_id: str, dim: Dimension) -> ReviewerFinding:
    return ReviewerFinding(
        finding_id=finding_id,
        pr_id=pr_id,
        reviewer_model="mock",
        location=Location(file_path="a.py", start_line=1, end_line=1),
        dimension=dim,
        severity=Severity.HIGH,
        comment="test",
    )


def test_perfect_match_gives_100_percent():
    gt = _make_gt("GT1", "PR1", Dimension.SECURITY)
    finding = _make_finding("F1", "PR1", Dimension.SECURITY)
    pr = _make_pr("PR1", [gt])
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[MatchResult(ground_truth_issue_id="GT1", finding_id="F1")],
        unmatched_findings=[],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": [finding]},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    assert report.aggregate_precision == 1.0
    assert report.aggregate_recall == 1.0
    assert report.aggregate_f1 == 1.0
    assert report.total_true_positives == 1
    assert report.total_false_positives == 0
    assert report.total_false_negatives == 0


def test_miss_gives_zero_recall():
    gt = _make_gt("GT1", "PR1", Dimension.SECURITY)
    pr = _make_pr("PR1", [gt])
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[MatchResult(ground_truth_issue_id="GT1", finding_id=None)],
        unmatched_findings=[],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": []},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    assert report.aggregate_recall == 0.0
    assert report.aggregate_precision is None  # No flagged findings
    assert report.total_false_negatives == 1


def test_false_positive_only_gives_zero_precision():
    finding = _make_finding("F1", "PR1", Dimension.SECURITY)
    pr = _make_pr("PR1", [])  # No ground truth
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[],
        unmatched_findings=[finding],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": [finding]},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    assert report.aggregate_precision == 0.0
    assert report.aggregate_recall is None  # No ground truth
    assert report.total_false_positives == 1


def test_mixed_tp_fp_fn():
    # Two GTs, one found, one missed. Plus one FP.
    gt1 = _make_gt("GT1", "PR1", Dimension.SECURITY)
    gt2 = _make_gt("GT2", "PR1", Dimension.CORRECTNESS)
    pr = _make_pr("PR1", [gt1, gt2])
    found_finding = _make_finding("F1", "PR1", Dimension.SECURITY)
    fp_finding = _make_finding("F2", "PR1", Dimension.STYLE)
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[
            MatchResult(ground_truth_issue_id="GT1", finding_id="F1"),
            MatchResult(ground_truth_issue_id="GT2", finding_id=None),
        ],
        unmatched_findings=[fp_finding],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": [found_finding, fp_finding]},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    assert report.total_true_positives == 1
    assert report.total_false_positives == 1
    assert report.total_false_negatives == 1
    assert report.aggregate_precision == 0.5
    assert report.aggregate_recall == 0.5
    assert report.aggregate_f1 == 0.5


def test_per_dimension_breakdown():
    gt_sec = _make_gt("GT1", "PR1", Dimension.SECURITY)
    gt_corr = _make_gt("GT2", "PR1", Dimension.CORRECTNESS)
    pr = _make_pr("PR1", [gt_sec, gt_corr])
    sec_finding = _make_finding("F1", "PR1", Dimension.SECURITY)
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[
            MatchResult(ground_truth_issue_id="GT1", finding_id="F1"),
            MatchResult(ground_truth_issue_id="GT2", finding_id=None),
        ],
        unmatched_findings=[],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": [sec_finding]},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    sec = next(dm for dm in report.per_dimension if dm.dimension == Dimension.SECURITY)
    corr = next(dm for dm in report.per_dimension if dm.dimension == Dimension.CORRECTNESS)
    assert sec.true_positives == 1
    assert sec.recall == 1.0
    assert corr.true_positives == 0
    assert corr.recall == 0.0


# --- Dimension classification accuracy tests ---


def test_dimension_classification_accuracy_perfect():
    """Reviewer finds the issue AND classifies it correctly."""
    gt = _make_gt("GT1", "PR1", Dimension.SECURITY)
    finding = _make_finding("F1", "PR1", Dimension.SECURITY)  # correct dimension
    pr = _make_pr("PR1", [gt])
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[MatchResult(ground_truth_issue_id="GT1", finding_id="F1")],
        unmatched_findings=[],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": [finding]},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    assert report.dimension_classification_accuracy == 1.0
    assert report.dimension_classification_tp == 1


def test_dimension_classification_accuracy_wrong_dimension():
    """Reviewer finds the issue but classifies it as the wrong dimension."""
    gt = _make_gt("GT1", "PR1", Dimension.SECURITY)
    finding = _make_finding("F1", "PR1", Dimension.CORRECTNESS)  # wrong dimension
    pr = _make_pr("PR1", [gt])
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[MatchResult(ground_truth_issue_id="GT1", finding_id="F1")],
        unmatched_findings=[],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": [finding]},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    # Recall is still 1.0 (issue was found)
    assert report.aggregate_recall == 1.0
    # But dimension classification accuracy is 0
    assert report.dimension_classification_accuracy == 0.0
    assert report.dimension_classification_tp == 1


def test_dimension_classification_accuracy_none_when_no_matches():
    """When there are no true positives, dimension accuracy is None."""
    gt = _make_gt("GT1", "PR1", Dimension.SECURITY)
    pr = _make_pr("PR1", [gt])
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[MatchResult(ground_truth_issue_id="GT1", finding_id=None)],
        unmatched_findings=[],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": []},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )
    assert report.dimension_classification_accuracy is None
    assert report.dimension_classification_tp == 0
