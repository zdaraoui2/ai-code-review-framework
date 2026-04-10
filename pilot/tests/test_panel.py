"""Tests for the JudgePanel with majority vote aggregation."""

from __future__ import annotations

import pytest

from pilot.judge import Judge
from pilot.panel import JudgePanel
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


class _StaticJudge(Judge):
    """Judge that returns pre-canned results for each PR."""

    def __init__(self, name: str, results_by_pr: dict[str, list[MatchResult]]):
        self._name = name
        self._results = results_by_pr

    @property
    def model_name(self) -> str:
        return self._name

    def match_findings_to_ground_truth(
        self, pr: PullRequest, findings: list[ReviewerFinding]
    ) -> list[MatchResult]:
        return self._results.get(pr.pr_id, [])


def _pr_with_issues(issue_ids: list[str]) -> PullRequest:
    return PullRequest(
        pr_id="PR1",
        title="Test",
        language="python",
        change_type=ChangeType.NEW_FEATURE,
        diff="+test",
        ground_truth=[
            GroundTruthIssue(
                issue_id=gid,
                pr_id="PR1",
                dimension=Dimension.CORRECTNESS,
                severity=Severity.MEDIUM,
                location=Location(file_path="a.py", start_line=1, end_line=1),
                description="test",
            )
            for gid in issue_ids
        ],
    )


def test_panel_requires_at_least_2_judges():
    single = _StaticJudge("j1", {})
    with pytest.raises(ValueError):
        JudgePanel([single])


def test_panel_unanimous_match_gives_high_confidence():
    pr = _pr_with_issues(["GT1"])
    j1 = _StaticJudge("j1", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    j2 = _StaticJudge("j2", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    j3 = _StaticJudge("j3", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    panel = JudgePanel([j1, j2, j3])

    results = panel.match_findings_to_ground_truth(pr, [])
    assert len(results) == 1
    assert results[0].finding_id == "F1"
    assert results[0].match_confidence == "high"


def test_panel_majority_match_gives_medium_confidence():
    pr = _pr_with_issues(["GT1"])
    j1 = _StaticJudge("j1", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    j2 = _StaticJudge("j2", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    j3 = _StaticJudge(
        "j3", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id=None)]}
    )
    panel = JudgePanel([j1, j2, j3])

    results = panel.match_findings_to_ground_truth(pr, [])
    assert results[0].finding_id == "F1"
    assert results[0].match_confidence == "medium"


def test_panel_all_no_match_gives_no_match():
    pr = _pr_with_issues(["GT1"])
    j1 = _StaticJudge("j1", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id=None)]})
    j2 = _StaticJudge("j2", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id=None)]})
    panel = JudgePanel([j1, j2])

    results = panel.match_findings_to_ground_truth(pr, [])
    assert results[0].finding_id is None


def test_panel_split_vote_no_majority_gives_no_match():
    pr = _pr_with_issues(["GT1"])
    # Three judges, three different answers — no majority
    j1 = _StaticJudge("j1", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    j2 = _StaticJudge("j2", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F2")]})
    j3 = _StaticJudge("j3", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F3")]})
    panel = JudgePanel([j1, j2, j3])

    results = panel.match_findings_to_ground_truth(pr, [])
    assert results[0].finding_id is None


def test_panel_majority_no_match_overrides_minority_match():
    pr = _pr_with_issues(["GT1"])
    # 2 judges say no-match, 1 says F1 — majority wins, no-match
    j1 = _StaticJudge("j1", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id=None)]})
    j2 = _StaticJudge("j2", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id=None)]})
    j3 = _StaticJudge("j3", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    panel = JudgePanel([j1, j2, j3])

    results = panel.match_findings_to_ground_truth(pr, [])
    assert results[0].finding_id is None


def test_panel_2_judges_must_agree():
    pr = _pr_with_issues(["GT1"])
    # 2 judges, split — no majority possible (1 > 1 is false)
    j1 = _StaticJudge("j1", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id="F1")]})
    j2 = _StaticJudge("j2", {"PR1": [MatchResult(ground_truth_issue_id="GT1", finding_id=None)]})
    panel = JudgePanel([j1, j2])

    results = panel.match_findings_to_ground_truth(pr, [])
    assert results[0].finding_id is None
