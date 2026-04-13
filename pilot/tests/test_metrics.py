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


# --- Dual reporting (GT-perspective vs claimed-dimension) tests -----------


def _claimed_dim_metrics(report, dimension: Dimension):
    """Extract ClaimedDimensionMetrics for a given dimension from a report."""
    return next(
        cdm for cdm in report.per_dimension_by_claim if cdm.dimension == dimension
    )


def test_dual_reporting_tables_have_15_dimensions():
    """Both per-dimension tables must cover all 15 dimensions."""
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
    assert len(report.per_dimension) == 15
    assert len(report.per_dimension_by_claim) == 15


def test_dual_reporting_agrees_when_dimensions_match():
    """When finding dimension == GT dimension, both tables agree on TPs."""
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
    gt_sec = next(dm for dm in report.per_dimension if dm.dimension == Dimension.SECURITY)
    claim_sec = _claimed_dim_metrics(report, Dimension.SECURITY)

    assert gt_sec.true_positives == 1
    assert claim_sec.true_positives == 1
    assert gt_sec.precision == 1.0
    assert claim_sec.precision == 1.0


def test_dual_reporting_diverges_on_dimension_misclassification():
    """Core test: when dimension misclassification is common, the two tables
    produce different (and both correct) numbers.

    Scenario: 3 GT issues are CONCURRENCY. 3 findings claim CORRECTNESS.
    All 3 match. Plus 1 FP finding claiming CORRECTNESS.

    GT-perspective (per_dimension):
      CONCURRENCY: 3 TP, 0 FP => precision 1.0 (inflated for precision,
        but correct for recall: "we found all concurrency bugs")
      CORRECTNESS: 0 TP, 1 FP => precision 0.0

    Claim-perspective (per_dimension_by_claim):
      CONCURRENCY: 0 TP, 0 FP => precision None (no claims)
      CORRECTNESS: 3 TP, 1 FP => precision 0.75 (honest: "3 of 4
        correctness claims were real issues")
    """
    gt_issues = [_make_gt(f"GT{idx}", "PR1", Dimension.CONCURRENCY) for idx in range(3)]
    matched_findings = [_make_finding(f"F{idx}", "PR1", Dimension.CORRECTNESS) for idx in range(3)]
    fp_finding = _make_finding("F-FP", "PR1", Dimension.CORRECTNESS)
    pr = _make_pr("PR1", gt_issues)

    matches = [
        MatchResult(ground_truth_issue_id=f"GT{idx}", finding_id=f"F{idx}")
        for idx in range(3)
    ]
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=matches,
        unmatched_findings=[fp_finding],
    )
    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": matched_findings + [fp_finding]},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )

    # --- GT-perspective checks ---
    gt_conc = next(dm for dm in report.per_dimension if dm.dimension == Dimension.CONCURRENCY)
    gt_corr = next(dm for dm in report.per_dimension if dm.dimension == Dimension.CORRECTNESS)

    assert gt_conc.true_positives == 3
    assert gt_conc.false_positives == 0
    assert gt_conc.precision == 1.0  # inflated — no finding claimed concurrency

    assert gt_corr.true_positives == 0
    assert gt_corr.false_positives == 1
    assert gt_corr.precision == 0.0  # deflated

    # --- Claim-perspective checks ---
    claim_conc = _claimed_dim_metrics(report, Dimension.CONCURRENCY)
    claim_corr = _claimed_dim_metrics(report, Dimension.CORRECTNESS)

    # No finding claimed concurrency, so no data
    assert claim_conc.true_positives == 0
    assert claim_conc.false_positives == 0
    assert claim_conc.total_claims == 0
    assert claim_conc.precision is None

    # All 4 findings claimed correctness: 3 were real issues, 1 was FP
    assert claim_corr.true_positives == 3
    assert claim_corr.false_positives == 1
    assert claim_corr.total_claims == 4
    assert claim_corr.precision == 0.75

    # Aggregate metrics unchanged by this fix
    assert report.aggregate_precision == 3 / 4  # 0.75
    assert report.aggregate_recall == 1.0
    assert report.total_true_positives == 3
    assert report.total_false_positives == 1


# --- Visible recall (truncation-aware) tests --------------------------------


def _make_gt_at_line(
    issue_id: str, pr_id: str, dim: Dimension, start_line: int
) -> GroundTruthIssue:
    """Create a GT issue at a specific line number."""
    return GroundTruthIssue(
        issue_id=issue_id,
        pr_id=pr_id,
        dimension=dim,
        severity=Severity.HIGH,
        location=Location(file_path="big.py", start_line=start_line, end_line=start_line),
        description=f"Issue at line {start_line}",
    )


def _make_truncated_pr(
    pr_id: str,
    ground_truth: list[GroundTruthIssue],
    excluded_gt_ids: list[str],
) -> PullRequest:
    """Create a PullRequest marked as truncated with excluded GT IDs."""
    return PullRequest(
        pr_id=pr_id,
        title="Truncated PR",
        language="python",
        change_type=ChangeType.BUG_FIX,
        diff="+code\n\n[... truncated at 50000 chars ...]",
        ground_truth=ground_truth,
        truncated=True,
        original_diff_length=100_000,
        excluded_gt_ids=excluded_gt_ids,
    )


def test_visible_recall_excludes_invisible_gt_issues():
    """Visible recall should not count excluded GT issues as FNs.

    3 visible GT found, 2 invisible GT missed. Total recall = 3/5 = 0.6.
    Visible recall = 3/3 = 1.0 because the 2 invisible issues are excluded.
    """
    visible_gt = [
        _make_gt_at_line("GT-VIS-1", "PR1", Dimension.CORRECTNESS, 10),
        _make_gt_at_line("GT-VIS-2", "PR1", Dimension.CORRECTNESS, 20),
        _make_gt_at_line("GT-VIS-3", "PR1", Dimension.CORRECTNESS, 30),
    ]
    invisible_gt = [
        _make_gt_at_line("GT-INVIS-1", "PR1", Dimension.CORRECTNESS, 800),
        _make_gt_at_line("GT-INVIS-2", "PR1", Dimension.CORRECTNESS, 1000),
    ]
    all_gt = visible_gt + invisible_gt
    excluded_ids = [gt.issue_id for gt in invisible_gt]

    pr = _make_truncated_pr("PR1", all_gt, excluded_ids)

    findings = [
        _make_finding("F1", "PR1", Dimension.CORRECTNESS),
        _make_finding("F2", "PR1", Dimension.CORRECTNESS),
        _make_finding("F3", "PR1", Dimension.CORRECTNESS),
    ]

    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[
            MatchResult(ground_truth_issue_id="GT-VIS-1", finding_id="F1"),
            MatchResult(ground_truth_issue_id="GT-VIS-2", finding_id="F2"),
            MatchResult(ground_truth_issue_id="GT-VIS-3", finding_id="F3"),
            MatchResult(ground_truth_issue_id="GT-INVIS-1", finding_id=None),
            MatchResult(ground_truth_issue_id="GT-INVIS-2", finding_id=None),
        ],
        unmatched_findings=[],
    )

    report = compute_metrics(
        prs=[pr],
        findings_by_pr={"PR1": findings},
        outcomes=[outcome],
        reviewer_model="mock",
        judge_panel=["mock"],
        evaluation_set="test",
    )

    # Total recall still counts all 5 GT issues — conservative metric.
    assert report.aggregate_recall == 3 / 5
    assert report.total_false_negatives == 2

    # Visible recall excludes the 2 invisible issues — fair metric.
    assert report.visible_recall == 1.0
    assert report.visible_recall_ci is not None
    assert report.truncated_pr_count == 1
    assert report.excluded_gt_issue_count == 2


def test_visible_recall_equals_total_when_no_truncation():
    """When no PRs are truncated, visible recall is None (not computed)."""
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

    # No truncation occurred, so visible recall is not computed.
    assert report.visible_recall is None
    assert report.visible_recall_ci is None
    assert report.truncated_pr_count == 0
    assert report.excluded_gt_issue_count == 0


def test_visible_recall_with_truncation_but_no_excluded_issues():
    """A truncated PR where all GT issues are in the visible region.

    visible_recall should be None because no GT issues were excluded,
    even though truncation happened. The truncated_pr_count still reflects
    that truncation occurred.
    """
    gt = _make_gt_at_line("GT1", "PR1", Dimension.CORRECTNESS, 5)
    pr = PullRequest(
        pr_id="PR1",
        title="Truncated but GT is visible",
        language="python",
        change_type=ChangeType.BUG_FIX,
        diff="+code\n\n[... truncated at 50000 chars ...]",
        ground_truth=[gt],
        truncated=True,
        original_diff_length=80_000,
        excluded_gt_ids=[],  # All GT is in the visible portion.
    )

    finding = _make_finding("F1", "PR1", Dimension.CORRECTNESS)
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

    # Truncation happened but no GT was excluded, so visible recall
    # is not computed (it would equal total recall).
    assert report.visible_recall is None
    assert report.truncated_pr_count == 1
    assert report.excluded_gt_issue_count == 0


def test_total_recall_unchanged_by_truncation_metadata():
    """Adding truncation metadata must NOT change total recall.

    This is a regression guard: the fix adds visible recall alongside
    total recall, not instead of it.
    """
    visible_gt = [_make_gt_at_line("GT-V", "PR1", Dimension.CORRECTNESS, 10)]
    invisible_gt = [_make_gt_at_line("GT-I", "PR1", Dimension.CORRECTNESS, 900)]
    all_gt = visible_gt + invisible_gt

    pr = _make_truncated_pr("PR1", all_gt, ["GT-I"])

    finding = _make_finding("F1", "PR1", Dimension.CORRECTNESS)
    outcome = MatchingOutcome(
        pr_id="PR1",
        matches=[
            MatchResult(ground_truth_issue_id="GT-V", finding_id="F1"),
            MatchResult(ground_truth_issue_id="GT-I", finding_id=None),
        ],
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

    # Total recall is 1/2 = 0.5 — the invisible issue still penalises it.
    assert report.aggregate_recall == 0.5
    assert report.total_false_negatives == 1

    # Visible recall is 1/1 = 1.0 — only visible issues count.
    assert report.visible_recall == 1.0
