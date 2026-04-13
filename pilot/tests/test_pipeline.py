"""Integration test for the full pilot pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from pilot.data import load_pull_requests
from pilot.judge import MockJudge
from pilot.reviewer import MockReviewer
from pilot.run import run_pipeline


FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_and_run():
    prs = load_pull_requests(FIXTURES / "sample.jsonl")
    reviewer = MockReviewer(FIXTURES / "mock_reviews.jsonl")
    judge = MockJudge(FIXTURES / "mock_judge_matches.jsonl")
    return run_pipeline(
        prs=prs,
        reviewer=reviewer,
        judge=judge,
        evaluation_set_name="sample",
    )


def test_full_pipeline_runs_on_sample_fixtures():
    """The pipeline runs end-to-end on the sample fixtures and produces
    sensible metrics (non-zero, non-perfect)."""
    report = _load_and_run()

    # There should be 10 PRs in the sample fixture.
    assert report.n_prs == 10

    # The reviewer catches some but not all issues.
    assert report.total_true_positives > 0
    assert report.total_false_negatives > 0
    # There should be at least some unmatched findings (false positives).
    assert report.total_false_positives > 0

    # Precision and recall should be non-trivial.
    assert report.aggregate_precision is not None
    assert 0.0 < report.aggregate_precision < 1.0
    assert report.aggregate_recall is not None
    assert 0.0 < report.aggregate_recall < 1.0


def test_pipeline_per_dimension_report_has_15_dimensions():
    report = _load_and_run()
    assert len(report.per_dimension) == 15


def test_pipeline_counts_match_aggregate():
    report = _load_and_run()
    tp = sum(dm.true_positives for dm in report.per_dimension)
    fp = sum(dm.false_positives for dm in report.per_dimension)
    fn = sum(dm.false_negatives for dm in report.per_dimension)
    assert tp == report.total_true_positives
    assert fp == report.total_false_positives
    assert fn == report.total_false_negatives
