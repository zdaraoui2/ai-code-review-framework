"""Tests verifying the model-family exclusion fix.

The framework spec (Section 8.1.1) requires judges on a panel to come from
different model families. These tests confirm that JudgePanel now enforces
this rule: same-family panels raise ValueError in strict mode (the default)
and log a warning in non-strict mode.

Previously, this file demonstrated the gap. The fix added a ``family``
abstract property to Judge and enforcement logic to JudgePanel.__init__.
"""

from __future__ import annotations

import argparse
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeJudge(Judge):
    """Minimal judge for testing panel composition constraints."""

    def __init__(self, name: str, family: str = "mock"):
        self._name = name
        self._family = family

    @property
    def model_name(self) -> str:
        return self._name

    @property
    def family(self) -> str:
        return self._family

    def match_findings_to_ground_truth(
        self, pr: PullRequest, findings: list[ReviewerFinding]
    ) -> list[MatchResult]:
        return [
            MatchResult(ground_truth_issue_id=gt.issue_id, finding_id=None)
            for gt in pr.ground_truth
        ]


def _make_pr() -> PullRequest:
    return PullRequest(
        pr_id="PR-FAMILY-TEST",
        title="Family exclusion test",
        language="python",
        change_type=ChangeType.BUG_FIX,
        diff="+# test",
        ground_truth=[
            GroundTruthIssue(
                issue_id="GT1",
                pr_id="PR-FAMILY-TEST",
                dimension=Dimension.CORRECTNESS,
                severity=Severity.HIGH,
                location=Location(file_path="foo.py", start_line=1, end_line=1),
                description="off-by-one in loop bound",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Panel-level: family diversity is now enforced
# ---------------------------------------------------------------------------


class TestPanelRejectsSameFamilyJudges:
    """Verify that JudgePanel.__init__ enforces the family exclusion rule."""

    def test_two_judges_same_family_raises(self):
        """Two judges from the same family are rejected per S8.1.1."""
        judge_a = FakeJudge("anthropic/claude-opus-4-6", family="anthropic")
        judge_b = FakeJudge("anthropic/claude-sonnet-4-6", family="anthropic")

        with pytest.raises(ValueError, match="duplicate families"):
            JudgePanel([judge_a, judge_b])

    def test_three_judges_same_family_raises(self):
        """Three judges from one family — spec says 'not acceptable'."""
        judge_a = FakeJudge("anthropic/claude-opus-4-6", family="anthropic")
        judge_b = FakeJudge("anthropic/claude-sonnet-4-6", family="anthropic")
        judge_c = FakeJudge("anthropic/claude-haiku-3.5", family="anthropic")

        with pytest.raises(ValueError, match="duplicate families"):
            JudgePanel([judge_a, judge_b, judge_c])

    def test_same_family_allowed_non_strict_with_warning(self, caplog):
        """Non-strict mode allows same-family panels but logs a warning."""
        judge_a = FakeJudge("anthropic/claude-opus-4-6", family="anthropic")
        judge_b = FakeJudge("anthropic/claude-sonnet-4-6", family="anthropic")

        with caplog.at_level("WARNING"):
            panel = JudgePanel([judge_a, judge_b], strict=False)

        assert len(panel.judges) == 2
        assert "duplicate families" in caplog.text

    def test_different_families_accepted(self):
        """Judges from different families pass validation."""
        judge_a = FakeJudge("anthropic/claude-opus-4-6", family="anthropic")
        judge_b = FakeJudge("openai/gpt-4o", family="openai")

        panel = JudgePanel([judge_a, judge_b])
        assert len(panel.judges) == 2

    def test_panel_runs_with_valid_family_panel(self):
        """A valid cross-family panel runs end-to-end."""
        judge_a = FakeJudge("anthropic/claude-opus-4-6", family="anthropic")
        judge_b = FakeJudge("openai/gpt-4o", family="openai")
        panel = JudgePanel([judge_a, judge_b])

        pr = _make_pr()
        results = panel.match_findings_to_ground_truth(pr, [])
        assert len(results) == 1
        assert results[0].finding_id is None


# ---------------------------------------------------------------------------
# Judge base class: family attribute now exists
# ---------------------------------------------------------------------------


class TestJudgeHasFamilyAttribute:
    """The Judge ABC now defines a 'family' abstract property."""

    def test_judge_abc_has_family_property(self):
        """Judge defines both model_name and family."""
        assert hasattr(Judge, "model_name")
        assert hasattr(Judge, "family")

    def test_fake_judge_family_is_accessible(self):
        """Concrete judges expose their family via the standard property."""
        judge = FakeJudge("anthropic/claude-opus-4-6", family="anthropic")
        assert judge.family == "anthropic"


# ---------------------------------------------------------------------------
# CLI-level: build_judge now enforced via JudgePanel
# ---------------------------------------------------------------------------


class TestBuildJudgeEnforcesFamilyExclusion:
    """build_judge delegates to JudgePanel, which now rejects same-family
    panels. The mock backend assigns unique families per judge instance,
    so mock,mock panels still work."""

    def test_build_judge_single_mock_works(self):
        """Single judge (no panel) is unaffected by family checks."""
        from pilot.run import build_judge

        fixture_path = (
            Path(__file__).resolve().parent.parent / "fixtures" / "mock_judge_matches.jsonl"
        )
        args = argparse.Namespace(
            judge="mock",
            judge_fixture=fixture_path,
            judge_models=None,
        )
        judge = build_judge(args)
        assert judge.family == "mock-1"
