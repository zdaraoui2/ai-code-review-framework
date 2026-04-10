"""Tests for data loading."""

from __future__ import annotations

from pathlib import Path

from pilot.data import (
    load_mock_judge_matches,
    load_mock_reviews,
    load_pull_requests,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_load_sample_prs():
    prs = load_pull_requests(FIXTURES / "sample.jsonl")
    assert len(prs) == 10
    # Every PR has a non-empty ground truth
    for pr in prs:
        assert len(pr.ground_truth) >= 1


def test_load_mock_reviews():
    findings = load_mock_reviews(FIXTURES / "mock_reviews.jsonl")
    assert len(findings) > 0
    # Findings span multiple PRs
    pr_ids = {f.pr_id for f in findings}
    assert len(pr_ids) > 1


def test_load_mock_judge_matches():
    matches = load_mock_judge_matches(FIXTURES / "mock_judge_matches.jsonl")
    assert len(matches) > 0
    # Some matches have findings, some don't
    has_finding = [m for m in matches if m.finding_id is not None]
    no_finding = [m for m in matches if m.finding_id is None]
    assert len(has_finding) > 0
    assert len(no_finding) > 0
