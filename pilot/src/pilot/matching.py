"""Semantic matching between reviewer findings and ground truth issues.

Uses the judge to determine whether each AI finding corresponds to a known
issue. Produces a structured result with:
- Matches (GT issue → finding, with confidence)
- Misses (GT issue not matched by any finding)
- Unmatched findings (findings not matching any GT — candidates for FP
  adjudication per Section 4.3)
"""

from __future__ import annotations

from dataclasses import dataclass

from pilot.judge import Judge
from pilot.schemas import (
    GroundTruthIssue,
    MatchResult,
    PullRequest,
    ReviewerFinding,
)


@dataclass(frozen=True)
class MatchingOutcome:
    """Result of matching reviewer findings against ground truth for one PR."""

    pr_id: str
    matches: list[MatchResult]  # One entry per GT issue
    unmatched_findings: list[ReviewerFinding]  # Findings not matched to any GT

    @property
    def true_positives(self) -> int:
        return sum(1 for m in self.matches if m.finding_id is not None)

    @property
    def false_negatives(self) -> int:
        """Ground truth issues that no finding matched."""
        return sum(1 for m in self.matches if m.finding_id is None)

    @property
    def potential_false_positives(self) -> int:
        """Findings not matching any ground truth.

        In a full implementation these would go through the FP adjudication
        protocol (Section 4.3) to separate confirmed false positives from
        confirmed novel findings. In the pilot we treat them all as potential
        FPs.
        """
        return len(self.unmatched_findings)

    def matched_finding_ids(self) -> set[str]:
        return {m.finding_id for m in self.matches if m.finding_id is not None}


def match_pr(
    pr: PullRequest,
    findings: list[ReviewerFinding],
    judge: Judge,
) -> MatchingOutcome:
    """Match findings against ground truth for a single PR."""
    match_results = judge.match_findings_to_ground_truth(pr, findings)
    matched_ids = {m.finding_id for m in match_results if m.finding_id is not None}
    unmatched = [f for f in findings if f.finding_id not in matched_ids]
    return MatchingOutcome(
        pr_id=pr.pr_id,
        matches=match_results,
        unmatched_findings=unmatched,
    )
