"""Tests for the c-CRAB dataset adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from pilot.datasets.ccrab import load_ccrab, get_dataset_stats, _infer_change_type
from pilot.schemas import ChangeType, Dimension


CCRAB_PATH = Path("/Users/zak/Developer/ai-research/ccrab-dataset/results_preprocessed/preprocess_dataset.jsonl")


@pytest.mark.skipif(not CCRAB_PATH.exists(), reason="c-CRAB dataset not available locally")
class TestCCRABRealData:
    """Tests that run against the real c-CRAB dataset."""

    def test_load_all_instances(self):
        prs = load_ccrab(CCRAB_PATH)
        # Should load a substantial number (410 in the dataset, some may be
        # skipped if they have no comments or no diff)
        assert len(prs) > 300

    def test_every_pr_has_ground_truth(self):
        prs = load_ccrab(CCRAB_PATH)
        for pr in prs:
            assert len(pr.ground_truth) >= 1, f"PR {pr.pr_id} has no ground truth"

    def test_every_pr_has_diff(self):
        prs = load_ccrab(CCRAB_PATH)
        for pr in prs:
            assert len(pr.diff) > 0, f"PR {pr.pr_id} has empty diff"

    def test_diff_truncation(self):
        prs_full = load_ccrab(CCRAB_PATH, max_diff_chars=None)
        prs_truncated = load_ccrab(CCRAB_PATH, max_diff_chars=10_000)
        # Some diffs should be shorter after truncation
        long_diffs = [pr for pr in prs_full if len(pr.diff) > 10_000]
        assert len(long_diffs) > 0, "Expected some long diffs in c-CRAB"
        for pr_trunc in prs_truncated:
            assert len(pr_trunc.diff) <= 10_100  # Allow for truncation message

    def test_stats(self):
        prs = load_ccrab(CCRAB_PATH)
        stats = get_dataset_stats(prs)
        assert stats["n_prs"] > 300
        assert stats["n_ground_truth_issues"] > stats["n_prs"]
        assert stats["languages"] == ["python"]

    def test_change_type_inference(self):
        prs = load_ccrab(CCRAB_PATH)
        types = {pr.change_type for pr in prs}
        # Should infer at least a couple of different change types
        assert len(types) >= 2


class TestChangeTypeInference:
    """Unit tests for change type inference from PR titles."""

    def test_fix_title(self):
        assert _infer_change_type("Fix null pointer in auth handler") == ChangeType.BUG_FIX

    def test_feature_title(self):
        assert _infer_change_type("Add user search endpoint") == ChangeType.NEW_FEATURE

    def test_refactor_title(self):
        assert _infer_change_type("Refactor payment module for clarity") == ChangeType.SIMPLE_REFACTORING

    def test_dependency_title(self):
        assert _infer_change_type("Bump axios from 1.6 to 1.7") == ChangeType.DEPENDENCY_UPDATE

    def test_config_title(self):
        assert _infer_change_type("Update config.yml for staging") == ChangeType.CONFIGURATION

    def test_default_is_bug_fix(self):
        assert _infer_change_type("Miscellaneous changes") == ChangeType.BUG_FIX
