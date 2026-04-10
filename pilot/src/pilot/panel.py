"""Judge panel orchestration.

Implements the 3-judge panel from S8.1 with majority vote aggregation.
A JudgePanel is itself a Judge — it implements the same interface but
delegates to multiple underlying judges and aggregates their results.
"""

from __future__ import annotations

from collections import Counter

from pilot.judge import Judge
from pilot.schemas import MatchResult, PullRequest, ReviewerFinding


class JudgePanel(Judge):
    """A panel of judges with majority vote aggregation for issue-match.

    Per S8.1.2, binary decisions use majority vote. For issue-match:
    - A ground truth issue is matched if the majority of judges agree on
      the same finding_id (not null).
    - If judges disagree on which finding matches, or if a minority picks
      a different finding than the rest, the aggregate treats it as no-match.
    - If all judges say no-match, the aggregate is no-match.

    The panel MUST contain at least 2 judges, and all judges MUST come from
    different model families (per S8.1.1 — model family exclusion rule). The
    panel does not enforce this — the caller is responsible for constructing
    a valid panel.
    """

    def __init__(self, judges: list[Judge]):
        if len(judges) < 2:
            raise ValueError(
                f"JudgePanel requires at least 2 judges, got {len(judges)}"
            )
        self._judges = judges

    @property
    def model_name(self) -> str:
        names = [j.model_name for j in self._judges]
        return f"panel[{','.join(names)}]"

    @property
    def judges(self) -> list[Judge]:
        return list(self._judges)

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        """Query each judge and aggregate by majority vote per GT issue."""
        # Collect per-judge match results
        per_judge_results: list[list[MatchResult]] = [
            judge.match_findings_to_ground_truth(pr, findings) for judge in self._judges
        ]

        aggregated: list[MatchResult] = []
        for gt_issue in pr.ground_truth:
            # Find each judge's decision for this GT issue
            votes: list[str | None] = []
            confidences: list[str | None] = []
            for judge_results in per_judge_results:
                match_for_gt = next(
                    (m for m in judge_results if m.ground_truth_issue_id == gt_issue.issue_id),
                    None,
                )
                if match_for_gt is None:
                    # Judge didn't return a result for this GT — treat as abstain/no-match
                    votes.append(None)
                    confidences.append(None)
                else:
                    votes.append(match_for_gt.finding_id)
                    confidences.append(match_for_gt.match_confidence)

            aggregated.append(
                _majority_vote(
                    gt_issue_id=gt_issue.issue_id,
                    votes=votes,
                    confidences=confidences,
                    total_judges=len(self._judges),
                )
            )
        return aggregated


def _majority_vote(
    gt_issue_id: str,
    votes: list[str | None],
    confidences: list[str | None],
    total_judges: int,
) -> MatchResult:
    """Aggregate per-judge votes into a single MatchResult.

    Rule: the matched finding is the one that appears in a strict majority
    (>50%) of votes. If no finding reaches a majority, the result is no-match.

    Match confidence is derived from vote concentration:
    - All judges agree on the same finding: "high"
    - Strict majority agrees on the same finding: "medium"
    - Split (no majority): null (no-match)
    """
    vote_counts = Counter(v for v in votes if v is not None)
    if not vote_counts:
        # All judges returned null — no match
        return MatchResult(ground_truth_issue_id=gt_issue_id, finding_id=None)

    top_finding, top_count = vote_counts.most_common(1)[0]

    # Count abstentions/no-match votes
    no_match_count = sum(1 for v in votes if v is None)
    if no_match_count >= (total_judges + 1) // 2:
        # Majority of judges said no-match
        return MatchResult(ground_truth_issue_id=gt_issue_id, finding_id=None)

    if top_count > total_judges / 2:
        # Strict majority on one finding
        if top_count == total_judges:
            confidence = "high"
        else:
            confidence = "medium"
        return MatchResult(
            ground_truth_issue_id=gt_issue_id,
            finding_id=top_finding,
            match_confidence=confidence,
        )

    # No majority — treat as no-match
    return MatchResult(ground_truth_issue_id=gt_issue_id, finding_id=None)
