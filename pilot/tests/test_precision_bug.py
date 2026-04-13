"""Test for methodological bug: asymmetric dimension attribution.

The bug: TPs are attributed to the GT dimension, but FPs are attributed to
the finding's claimed dimension. If a reviewer detects real issues but
misclassifies their dimension, this asymmetry inflates per-dimension
precision for the GT dimension (which gets free TPs with no corresponding FPs)
and deflates precision for the finding's claimed dimension (which gets FPs but
no corresponding TPs).

The fix: dual reporting. per_dimension (GT-perspective) remains unchanged
for recall. per_dimension_by_claim (finding-perspective) attributes TPs to
the finding's claimed dimension, giving honest precision by claim.
"""

from __future__ import annotations

import pytest

from pilot.matching import MatchingOutcome
from pilot.metrics import compute_metrics
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


# --- helpers ----------------------------------------------------------------


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


def _dim_metrics(report, dimension: Dimension):
    """Extract DimensionMetrics for a given dimension from a report."""
    return next(dm for dm in report.per_dimension if dm.dimension == dimension)


def _claimed_metrics(report, dimension: Dimension):
    """Extract ClaimedDimensionMetrics for a given dimension from a report."""
    return next(cdm for cdm in report.per_dimension_by_claim if cdm.dimension == dimension)


# --- Scenario A: all findings match, wrong dimension -----------------------


class TestScenarioA_AllMatchedWrongDimension:
    """5 GT issues in CONCURRENCY, 5 findings claiming CORRECTNESS, all matched.

    Every finding detects a real issue but labels it with the wrong dimension.
    Since all findings match, there are 0 FPs. TPs are attributed to the GT
    dimension (CONCURRENCY). What does per-dimension precision look like?
    """

    @pytest.fixture()
    def report(self):
        gt_issues = [_make_gt(f"GT{i}", "PR1", Dimension.CONCURRENCY) for i in range(5)]
        findings = [_make_finding(f"F{i}", "PR1", Dimension.CORRECTNESS) for i in range(5)]
        pr = _make_pr("PR1", gt_issues)

        matches = [
            MatchResult(ground_truth_issue_id=f"GT{i}", finding_id=f"F{i}")
            for i in range(5)
        ]
        outcome = MatchingOutcome(pr_id="PR1", matches=matches, unmatched_findings=[])

        return compute_metrics(
            prs=[pr],
            findings_by_pr={"PR1": findings},
            outcomes=[outcome],
            reviewer_model="mock",
            judge_panel=["mock"],
            evaluation_set="test",
        )

    def test_aggregate_metrics_are_correct(self, report):
        """Aggregate precision/recall should be 1.0 — all issues found, no FPs."""
        print(f"\n--- Scenario A: aggregate ---")
        print(f"  aggregate precision = {report.aggregate_precision}")
        print(f"  aggregate recall    = {report.aggregate_recall}")
        print(f"  aggregate F1        = {report.aggregate_f1}")
        print(f"  total TP={report.total_true_positives}  FP={report.total_false_positives}  FN={report.total_false_negatives}")
        assert report.aggregate_precision == 1.0
        assert report.aggregate_recall == 1.0

    def test_concurrency_gets_tps_despite_no_findings_claiming_it(self, report):
        """CONCURRENCY gets 5 TPs even though no finding claimed CONCURRENCY."""
        conc = _dim_metrics(report, Dimension.CONCURRENCY)
        print(f"\n--- Scenario A: CONCURRENCY ---")
        print(f"  TP={conc.true_positives}  FP={conc.false_positives}  FN={conc.false_negatives}")
        print(f"  precision={conc.precision}  recall={conc.recall}")
        # This is the attribution rule: TPs go to GT dimension
        assert conc.true_positives == 5
        assert conc.false_positives == 0
        assert conc.precision == 1.0
        assert conc.recall == 1.0

    def test_correctness_shows_nothing_despite_all_findings_claiming_it(self, report):
        """CORRECTNESS gets 0 TPs and 0 FPs — the findings that claimed it are invisible."""
        corr = _dim_metrics(report, Dimension.CORRECTNESS)
        print(f"\n--- Scenario A: CORRECTNESS ---")
        print(f"  TP={corr.true_positives}  FP={corr.false_positives}  FN={corr.false_negatives}")
        print(f"  precision={corr.precision}  recall={corr.recall}")
        assert corr.true_positives == 0
        assert corr.false_positives == 0
        assert corr.precision is None  # undefined: 0/(0+0)

    def test_dimension_classification_accuracy_catches_misclassification(self, report):
        """The dimension_classification_accuracy metric should be 0.0."""
        print(f"\n--- Scenario A: dimension classification ---")
        print(f"  accuracy = {report.dimension_classification_accuracy}")
        print(f"  matched_total = {report.dimension_classification_tp}")
        assert report.dimension_classification_accuracy == 0.0

    def test_claimed_perspective_attributes_tps_to_correctness(self, report):
        """The finding-perspective table should show 5 TPs under CORRECTNESS
        (the claimed dimension), not CONCURRENCY (the GT dimension)."""
        claim_conc = _claimed_metrics(report, Dimension.CONCURRENCY)
        claim_corr = _claimed_metrics(report, Dimension.CORRECTNESS)

        # No finding claimed concurrency
        assert claim_conc.true_positives == 0
        assert claim_conc.total_claims == 0
        assert claim_conc.precision is None

        # All 5 findings claimed correctness and all matched
        assert claim_corr.true_positives == 5
        assert claim_corr.false_positives == 0
        assert claim_corr.total_claims == 5
        assert claim_corr.precision == 1.0


# --- Scenario B: mixed matches + FPs, all wrong dimension ------------------


class TestScenarioB_MixedMatchesAndFPsWrongDimension:
    """3 GT CONCURRENCY + 2 GT CORRECTNESS issues. 5 findings all claim
    CORRECTNESS. 3 findings match the 3 CONCURRENCY GTs; 2 findings match
    nothing (FPs). The 2 CORRECTNESS GTs are missed (FNs).

    This is the scenario where the asymmetry matters most:
    - CONCURRENCY gets 3 TPs, 0 FPs => precision 1.0  (inflated?)
    - CORRECTNESS gets 0 TPs, 2 FPs, 2 FNs => precision 0.0

    The reviewer never claimed to find CONCURRENCY issues, yet CONCURRENCY
    shows perfect precision. Meanwhile CORRECTNESS — the dimension the
    reviewer claimed — gets punished with 0% precision.
    """

    @pytest.fixture()
    def report(self):
        gt_concurrency = [_make_gt(f"GT_C{i}", "PR1", Dimension.CONCURRENCY) for i in range(3)]
        gt_correctness = [_make_gt(f"GT_R{i}", "PR1", Dimension.CORRECTNESS) for i in range(2)]
        all_gt = gt_concurrency + gt_correctness
        pr = _make_pr("PR1", all_gt)

        # All 5 findings claim CORRECTNESS
        findings = [_make_finding(f"F{i}", "PR1", Dimension.CORRECTNESS) for i in range(5)]

        # F0-F2 match CONCURRENCY GT; F3-F4 match nothing; CORRECTNESS GT unmatched
        matches = [
            MatchResult(ground_truth_issue_id=f"GT_C{i}", finding_id=f"F{i}")
            for i in range(3)
        ] + [
            MatchResult(ground_truth_issue_id=f"GT_R{i}", finding_id=None)
            for i in range(2)
        ]
        unmatched_findings = [findings[3], findings[4]]

        outcome = MatchingOutcome(
            pr_id="PR1",
            matches=matches,
            unmatched_findings=unmatched_findings,
        )

        return compute_metrics(
            prs=[pr],
            findings_by_pr={"PR1": findings},
            outcomes=[outcome],
            reviewer_model="mock",
            judge_panel=["mock"],
            evaluation_set="test",
        )

    def test_aggregate_metrics(self, report):
        print(f"\n--- Scenario B: aggregate ---")
        print(f"  TP={report.total_true_positives}  FP={report.total_false_positives}  FN={report.total_false_negatives}")
        print(f"  aggregate precision = {report.aggregate_precision}")
        print(f"  aggregate recall    = {report.aggregate_recall}")
        assert report.total_true_positives == 3
        assert report.total_false_positives == 2
        assert report.total_false_negatives == 2
        assert report.aggregate_precision == 3 / 5  # 0.6
        assert report.aggregate_recall == 3 / 5  # 0.6

    def test_concurrency_precision_inflated(self, report):
        """CONCURRENCY gets 3 TPs and 0 FPs — precision 1.0.

        But the reviewer never claimed CONCURRENCY. The 3 matched findings all
        said CORRECTNESS. The TP attribution to the GT dimension creates a
        phantom 100% precision in a dimension the reviewer did not even target.
        """
        conc = _dim_metrics(report, Dimension.CONCURRENCY)
        print(f"\n--- Scenario B: CONCURRENCY (the GT dimension) ---")
        print(f"  TP={conc.true_positives}  FP={conc.false_positives}  FN={conc.false_negatives}")
        print(f"  precision={conc.precision}  recall={conc.recall}")
        # Demonstrating the inflation: precision is 1.0 despite every finding
        # claiming a different dimension
        assert conc.true_positives == 3
        assert conc.false_positives == 0
        assert conc.precision == 1.0  # <-- this is the inflation
        assert conc.recall == 1.0

    def test_correctness_precision_deflated(self, report):
        """CORRECTNESS gets 0 TPs and 2 FPs — precision 0.0.

        All 5 findings claimed CORRECTNESS, but the 3 that matched had their
        TPs redirected to CONCURRENCY. Only the 2 unmatched findings remain
        here as FPs. The CORRECTNESS GT issues that were missed add 2 FNs.
        """
        corr = _dim_metrics(report, Dimension.CORRECTNESS)
        print(f"\n--- Scenario B: CORRECTNESS (the finding's claimed dimension) ---")
        print(f"  TP={corr.true_positives}  FP={corr.false_positives}  FN={corr.false_negatives}")
        print(f"  precision={corr.precision}  recall={corr.recall}")
        assert corr.true_positives == 0
        assert corr.false_positives == 2
        assert corr.false_negatives == 2
        assert corr.precision == 0.0  # <-- this is the deflation
        assert corr.recall == 0.0

    def test_dimension_classification_accuracy_is_zero(self, report):
        """All 3 matched findings misclassified the dimension."""
        print(f"\n--- Scenario B: dimension classification ---")
        print(f"  accuracy = {report.dimension_classification_accuracy}")
        assert report.dimension_classification_accuracy == 0.0

    def test_claimed_perspective_gives_honest_correctness_precision(self, report):
        """The finding-perspective table fixes the misleading per-dimension
        precision. All 5 findings claimed CORRECTNESS: 3 matched real issues,
        2 were FPs. So claimed precision for CORRECTNESS = 3/5 = 0.6.

        Compare to the GT-perspective where CORRECTNESS shows 0% precision
        (0 TP, 2 FP) and CONCURRENCY shows 100% precision (3 TP, 0 FP).
        """
        claim_conc = _claimed_metrics(report, Dimension.CONCURRENCY)
        claim_corr = _claimed_metrics(report, Dimension.CORRECTNESS)

        # No finding claimed concurrency
        assert claim_conc.true_positives == 0
        assert claim_conc.total_claims == 0
        assert claim_conc.precision is None

        # 5 findings claimed correctness: 3 matched, 2 didn't
        assert claim_corr.true_positives == 3
        assert claim_corr.false_positives == 2
        assert claim_corr.total_claims == 5
        assert claim_corr.precision == 3 / 5  # 0.6 — honest


# --- Scenario C: control — same setup but correct dimensions ---------------


class TestScenarioC_ControlCorrectDimensions:
    """Same as Scenario B but findings claim the correct dimensions.

    3 findings claim CONCURRENCY (matching 3 CONCURRENCY GTs), 2 findings
    claim CORRECTNESS but don't match. This shows what honest per-dimension
    metrics look like.
    """

    @pytest.fixture()
    def report(self):
        gt_concurrency = [_make_gt(f"GT_C{i}", "PR1", Dimension.CONCURRENCY) for i in range(3)]
        gt_correctness = [_make_gt(f"GT_R{i}", "PR1", Dimension.CORRECTNESS) for i in range(2)]
        all_gt = gt_concurrency + gt_correctness
        pr = _make_pr("PR1", all_gt)

        # Findings correctly claim CONCURRENCY for matched, CORRECTNESS for unmatched
        matched_findings = [_make_finding(f"F{i}", "PR1", Dimension.CONCURRENCY) for i in range(3)]
        unmatched_findings_list = [_make_finding(f"F{i}", "PR1", Dimension.CORRECTNESS) for i in range(3, 5)]
        all_findings = matched_findings + unmatched_findings_list

        matches = [
            MatchResult(ground_truth_issue_id=f"GT_C{i}", finding_id=f"F{i}")
            for i in range(3)
        ] + [
            MatchResult(ground_truth_issue_id=f"GT_R{i}", finding_id=None)
            for i in range(2)
        ]

        outcome = MatchingOutcome(
            pr_id="PR1",
            matches=matches,
            unmatched_findings=unmatched_findings_list,
        )

        return compute_metrics(
            prs=[pr],
            findings_by_pr={"PR1": all_findings},
            outcomes=[outcome],
            reviewer_model="mock",
            judge_panel=["mock"],
            evaluation_set="test",
        )

    def test_concurrency_precision_still_1_but_honestly(self, report):
        """When dimension claims are correct, CONCURRENCY precision 1.0 is fair."""
        conc = _dim_metrics(report, Dimension.CONCURRENCY)
        print(f"\n--- Scenario C (control): CONCURRENCY ---")
        print(f"  TP={conc.true_positives}  FP={conc.false_positives}  FN={conc.false_negatives}")
        print(f"  precision={conc.precision}")
        assert conc.precision == 1.0

    def test_correctness_precision_same_as_scenario_b(self, report):
        """CORRECTNESS still has 0 TP and 2 FP — same result either way."""
        corr = _dim_metrics(report, Dimension.CORRECTNESS)
        print(f"\n--- Scenario C (control): CORRECTNESS ---")
        print(f"  TP={corr.true_positives}  FP={corr.false_positives}  FN={corr.false_negatives}")
        print(f"  precision={corr.precision}")
        assert corr.precision == 0.0

    def test_dimension_classification_accuracy_is_perfect(self, report):
        """Control: all matched findings have correct dimension."""
        print(f"\n--- Scenario C (control): dimension classification ---")
        print(f"  accuracy = {report.dimension_classification_accuracy}")
        assert report.dimension_classification_accuracy == 1.0

    def test_claimed_and_gt_perspectives_agree_when_dimensions_correct(self, report):
        """When dimensions are correct, both perspectives give the same numbers.

        CONCURRENCY: GT-perspective TP=3 FP=0, claim-perspective TP=3 FP=0.
        CORRECTNESS: GT-perspective TP=0 FP=2, claim-perspective TP=0 FP=2.
        """
        gt_conc = _dim_metrics(report, Dimension.CONCURRENCY)
        claim_conc = _claimed_metrics(report, Dimension.CONCURRENCY)
        assert gt_conc.true_positives == claim_conc.true_positives == 3
        assert gt_conc.false_positives == claim_conc.false_positives == 0

        gt_corr = _dim_metrics(report, Dimension.CORRECTNESS)
        claim_corr = _claimed_metrics(report, Dimension.CORRECTNESS)
        assert gt_corr.false_positives == claim_corr.false_positives == 2
