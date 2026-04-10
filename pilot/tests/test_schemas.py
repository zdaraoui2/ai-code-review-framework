"""Tests for pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    ReviewerFinding,
    Severity,
    tier_of,
    TIER_1,
    TIER_2,
    TIER_3,
)


def test_dimension_has_15_values():
    assert len(list(Dimension)) == 15


def test_tiers_partition_dimensions():
    all_tiered = TIER_1 | TIER_2 | TIER_3
    assert all_tiered == set(Dimension)
    # Tiers are disjoint
    assert TIER_1 & TIER_2 == set()
    assert TIER_1 & TIER_3 == set()
    assert TIER_2 & TIER_3 == set()


def test_tier_of_returns_correct_tier():
    assert tier_of(Dimension.SECURITY) == 1
    assert tier_of(Dimension.API_DESIGN) == 2
    assert tier_of(Dimension.STYLE) == 3


def test_severity_has_4_levels():
    assert len(list(Severity)) == 4
    assert Severity.LOW == 1
    assert Severity.CRITICAL == 4


def test_change_type_has_6_values():
    assert len(list(ChangeType)) == 6


def test_location_is_frozen():
    loc = Location(file_path="a.py", start_line=1, end_line=3)
    with pytest.raises(ValidationError):
        loc.file_path = "b.py"  # type: ignore[misc]


def test_ground_truth_issue_requires_all_fields():
    with pytest.raises(ValidationError):
        GroundTruthIssue(  # type: ignore[call-arg]
            issue_id="GT1",
            pr_id="PR1",
        )


def test_pull_request_with_ground_truth():
    pr = PullRequest(
        pr_id="PR1",
        title="Test",
        language="python",
        change_type=ChangeType.NEW_FEATURE,
        diff="+print('hi')",
        ground_truth=[
            GroundTruthIssue(
                issue_id="GT1",
                pr_id="PR1",
                dimension=Dimension.CORRECTNESS,
                severity=Severity.HIGH,
                location=Location(file_path="main.py", start_line=1, end_line=1),
                description="A test issue",
            )
        ],
    )
    assert pr.pr_id == "PR1"
    assert len(pr.ground_truth) == 1
    assert pr.ground_truth[0].dimension == Dimension.CORRECTNESS


def test_reviewer_finding_schema():
    finding = ReviewerFinding(
        finding_id="F1",
        pr_id="PR1",
        reviewer_model="mock",
        location=Location(file_path="main.py", start_line=1, end_line=1),
        dimension=Dimension.SECURITY,
        severity=Severity.CRITICAL,
        comment="SQL injection vulnerability.",
    )
    assert finding.dimension == Dimension.SECURITY
    assert finding.severity == Severity.CRITICAL
