"""Tests verifying the truncation-recall fix.

When diffs are truncated at --max-diff-chars, ground truth issues that
reference code in the truncated portion are now tracked via
PullRequest.excluded_gt_ids. The metrics pipeline computes dual recall:
- aggregate_recall: counts all GT issues (conservative, unchanged).
- visible_recall: excludes GT issues in truncated regions (fair).

These tests verify:
1. PullRequest carries truncation metadata.
2. Dataset adapters populate truncation metadata correctly.
3. compute_metrics computes visible_recall from excluded_gt_ids.
4. The original unfair penalty is gone from visible_recall while total
   recall remains unchanged.
"""

from __future__ import annotations

from pilot.judge import Judge
from pilot.matching import MatchingOutcome, match_pr
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_large_diff(total_chars: int) -> str:
    """Build a synthetic unified diff of approximately `total_chars` characters.

    The diff consists of numbered lines so we can tell where truncation
    lands. Each line is ~80 chars including the line number prefix.
    """
    header = "--- a/big_file.py\n+++ b/big_file.py\n@@ -1,5000 +1,5000 @@\n"
    lines: list[str] = [header]
    current_length = len(header)
    line_number = 1

    while current_length < total_chars:
        # Alternate between context, additions, and deletions to look
        # realistic. Every 10th line is a change.
        if line_number % 10 == 0:
            prefix = "+"
        elif line_number % 10 == 5:
            prefix = "-"
        else:
            prefix = " "

        line_content = (
            f"{prefix}# Line {line_number:06d}: "
            f"some_variable_{line_number} = compute(arg_{line_number})"
        )
        # Pad to ~80 chars
        line_content = line_content.ljust(78) + "\n"
        lines.append(line_content)
        current_length += len(line_content)
        line_number += 1

    return "".join(lines)[:total_chars]


def _make_gt_issue(
    issue_id: str,
    pr_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
    description: str,
) -> GroundTruthIssue:
    return GroundTruthIssue(
        issue_id=issue_id,
        pr_id=pr_id,
        dimension=Dimension.CORRECTNESS,
        severity=Severity.HIGH,
        location=Location(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        ),
        description=description,
    )


def _make_finding(
    finding_id: str,
    pr_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
    comment: str,
) -> ReviewerFinding:
    return ReviewerFinding(
        finding_id=finding_id,
        pr_id=pr_id,
        reviewer_model="test-reviewer",
        location=Location(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        ),
        dimension=Dimension.CORRECTNESS,
        severity=Severity.HIGH,
        comment=comment,
    )


class _DeterministicJudge(Judge):
    """A judge that matches findings to GT issues by a predefined mapping.

    This lets us control exactly which findings match which GT issues
    without relying on fixture files or LLM calls.
    """

    def __init__(self, match_map: dict[str, str | None]):
        """
        Args:
            match_map: Mapping from ground_truth_issue_id to finding_id
                (or None for a miss).
        """
        self._match_map = match_map

    @property
    def model_name(self) -> str:
        return "deterministic-test-judge"

    @property
    def family(self) -> str:
        return "test"

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        results: list[MatchResult] = []
        for gt_issue in pr.ground_truth:
            finding_id = self._match_map.get(gt_issue.issue_id)
            results.append(
                MatchResult(
                    ground_truth_issue_id=gt_issue.issue_id,
                    finding_id=finding_id,
                    match_confidence="high" if finding_id else None,
                )
            )
        return results


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

TOTAL_DIFF_CHARS = 100_000
TRUNCATION_LIMIT = 50_000
PR_ID = "truncation-test-PR1"
FILE_PATH = "big_file.py"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTruncationMetadata:
    """PullRequest now carries truncation metadata."""

    def test_pull_request_has_truncation_fields(self):
        """The PullRequest schema has fields to track truncation state."""
        field_names = set(PullRequest.model_fields.keys())
        assert "truncated" in field_names
        assert "original_diff_length" in field_names
        assert "excluded_gt_ids" in field_names

    def test_truncation_defaults_are_safe(self):
        """Without explicit truncation metadata, defaults are benign."""
        pr = PullRequest(
            pr_id="test",
            title="test",
            language="python",
            change_type=ChangeType.BUG_FIX,
            diff="+code",
            ground_truth=[],
        )
        assert pr.truncated is False
        assert pr.original_diff_length is None
        assert pr.excluded_gt_ids == []


class TestTruncationRecallFix:
    """Verify the truncation-recall fix produces dual recall metrics."""

    def _build_scenario(self):
        """Build the full test scenario.

        Returns a tuple of (pr, visible_findings, all_gt,
        visible_gt_ids, invisible_gt_ids).
        """
        # Build a 100K-char diff, then truncate it at 50K
        full_diff = _build_large_diff(TOTAL_DIFF_CHARS)
        assert len(full_diff) == TOTAL_DIFF_CHARS

        truncated_diff = (
            full_diff[:TRUNCATION_LIMIT]
            + f"\n\n[... truncated at {TRUNCATION_LIMIT} chars ...]"
        )

        visible_gt = [
            _make_gt_issue(
                "GT-VIS-1", PR_ID, FILE_PATH, 100, 105,
                "Off-by-one in loop bound at line 100",
            ),
            _make_gt_issue(
                "GT-VIS-2", PR_ID, FILE_PATH, 200, 210,
                "Missing null check at line 200",
            ),
            _make_gt_issue(
                "GT-VIS-3", PR_ID, FILE_PATH, 300, 305,
                "SQL injection at line 300",
            ),
        ]

        invisible_gt = [
            _make_gt_issue(
                "GT-INVIS-1", PR_ID, FILE_PATH, 800, 810,
                "Race condition at line 800 (in truncated portion)",
            ),
            _make_gt_issue(
                "GT-INVIS-2", PR_ID, FILE_PATH, 1000, 1005,
                "Buffer overflow at line 1000 (in truncated portion)",
            ),
        ]

        all_gt = visible_gt + invisible_gt
        invisible_gt_ids = [gt.issue_id for gt in invisible_gt]

        pr = PullRequest(
            pr_id=PR_ID,
            title="Large PR with issues in truncated region",
            language="python",
            change_type=ChangeType.BUG_FIX,
            diff=truncated_diff,
            ground_truth=all_gt,
            truncated=True,
            original_diff_length=TOTAL_DIFF_CHARS,
            excluded_gt_ids=invisible_gt_ids,
        )

        # Reviewer finds exactly the 3 visible issues
        visible_findings = [
            _make_finding(
                "F-VIS-1", PR_ID, FILE_PATH, 100, 105,
                "Found: off-by-one in loop bound",
            ),
            _make_finding(
                "F-VIS-2", PR_ID, FILE_PATH, 200, 210,
                "Found: missing null check",
            ),
            _make_finding(
                "F-VIS-3", PR_ID, FILE_PATH, 300, 305,
                "Found: SQL injection vulnerability",
            ),
        ]

        visible_gt_ids = {gt.issue_id for gt in visible_gt}

        return pr, visible_findings, all_gt, visible_gt_ids, set(invisible_gt_ids)

    def test_all_gt_issues_preserved_on_pr(self):
        """After truncation, all 5 GT issues remain on the PR object.

        GT issues are NOT filtered -- they are merely tagged as excluded
        via excluded_gt_ids.
        """
        pr, _, _, _, _ = self._build_scenario()
        assert len(pr.ground_truth) == 5
        assert pr.truncated is True
        assert len(pr.excluded_gt_ids) == 2

    def test_total_recall_still_penalised(self):
        """Total (aggregate) recall still counts invisible issues as FNs.

        This is the conservative metric -- it has not changed.
        """
        pr, visible_findings, _, _, _ = self._build_scenario()

        match_map = {
            "GT-VIS-1": "F-VIS-1",
            "GT-VIS-2": "F-VIS-2",
            "GT-VIS-3": "F-VIS-3",
            "GT-INVIS-1": None,
            "GT-INVIS-2": None,
        }
        judge = _DeterministicJudge(match_map)
        outcome = match_pr(pr, visible_findings, judge)

        report = compute_metrics(
            prs=[pr],
            findings_by_pr={PR_ID: visible_findings},
            outcomes=[outcome],
            reviewer_model="test-reviewer",
            judge_panel=["deterministic-test-judge"],
            evaluation_set="truncation-test",
        )

        # Total recall is still 3/5 = 0.6 (conservative, unchanged).
        assert report.aggregate_recall == 3 / 5
        assert report.total_false_negatives == 2

    def test_visible_recall_is_fair(self):
        """Visible recall excludes GT issues in truncated regions.

        A reviewer that finds all 3 visible issues should get visible
        recall = 1.0, not 0.6.
        """
        pr, visible_findings, _, _, _ = self._build_scenario()

        match_map = {
            "GT-VIS-1": "F-VIS-1",
            "GT-VIS-2": "F-VIS-2",
            "GT-VIS-3": "F-VIS-3",
            "GT-INVIS-1": None,
            "GT-INVIS-2": None,
        }
        judge = _DeterministicJudge(match_map)
        outcome = match_pr(pr, visible_findings, judge)

        report = compute_metrics(
            prs=[pr],
            findings_by_pr={PR_ID: visible_findings},
            outcomes=[outcome],
            reviewer_model="test-reviewer",
            judge_panel=["deterministic-test-judge"],
            evaluation_set="truncation-test",
        )

        # Visible recall = 3/3 = 1.0 -- fair metric.
        assert report.visible_recall == 1.0
        assert report.visible_recall_ci is not None
        assert report.truncated_pr_count == 1
        assert report.excluded_gt_issue_count == 2

    def test_ccrab_adapter_populates_truncation_metadata(self):
        """Verify the c-CRAB adapter records truncation metadata when
        a diff is truncated.
        """
        import json
        import tempfile
        from pathlib import Path

        from pilot.datasets.ccrab import load_ccrab

        large_diff = _build_large_diff(TOTAL_DIFF_CHARS)

        instance = {
            "instance_id": "test-instance-truncation",
            "title": "Fix bug in large module",
            "commit_to_review": {
                "head_commit_message": "Fix bug",
                "patch_to_review": large_diff,
            },
            "language": "Python",
            "reference_review_comments": [
                {
                    "text": "Early issue: missing error handling",
                    "path": "big_file.py",
                    "line": 50,
                    "start_line": 50,
                },
                {
                    "text": "Late issue: race condition in cleanup",
                    "path": "big_file.py",
                    "line": 900,
                    "start_line": 900,
                },
            ],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as tmp:
            tmp.write(json.dumps(instance) + "\n")
            tmp_path = Path(tmp.name)

        try:
            prs = load_ccrab(tmp_path, max_diff_chars=TRUNCATION_LIMIT)
        finally:
            tmp_path.unlink()

        assert len(prs) == 1
        pr = prs[0]

        # Diff is truncated
        assert pr.truncated is True
        assert pr.original_diff_length == TOTAL_DIFF_CHARS
        assert "[... truncated at" in pr.diff

        # Both GT issues survive
        assert len(pr.ground_truth) == 2

        # The late issue (line 900) should be in excluded_gt_ids because
        # it's past the last visible line in the truncated diff.
        late_issue = next(
            gt for gt in pr.ground_truth if gt.location.start_line == 900
        )
        assert late_issue.issue_id in pr.excluded_gt_ids

        # The early issue (line 50) should NOT be excluded.
        early_issue = next(
            gt for gt in pr.ground_truth if gt.location.start_line == 50
        )
        assert early_issue.issue_id not in pr.excluded_gt_ids

    def test_recall_penalty_no_longer_scales_with_truncation(self):
        """With visible recall, more aggressive truncation does not
        unfairly depress the fair metric. Total recall still shows the
        conservative picture.
        """
        full_diff = _build_large_diff(TOTAL_DIFF_CHARS)
        quarter_limit = 25_000
        truncated_diff = (
            full_diff[:quarter_limit]
            + f"\n\n[... truncated at {quarter_limit} chars ...]"
        )

        all_gt = [
            _make_gt_issue(
                "GT-1", PR_ID, FILE_PATH, 100, 105,
                "Issue at line 100 (visible in first quarter)",
            ),
            _make_gt_issue(
                "GT-2", PR_ID, FILE_PATH, 400, 410,
                "Issue at line 400 (invisible after quarter truncation)",
            ),
            _make_gt_issue(
                "GT-3", PR_ID, FILE_PATH, 700, 710,
                "Issue at line 700 (invisible after quarter truncation)",
            ),
            _make_gt_issue(
                "GT-4", PR_ID, FILE_PATH, 900, 910,
                "Issue at line 900 (invisible after quarter truncation)",
            ),
        ]

        pr = PullRequest(
            pr_id=PR_ID,
            title="Large PR with aggressive truncation",
            language="python",
            change_type=ChangeType.BUG_FIX,
            diff=truncated_diff,
            ground_truth=all_gt,
            truncated=True,
            original_diff_length=TOTAL_DIFF_CHARS,
            excluded_gt_ids=["GT-2", "GT-3", "GT-4"],
        )

        # Reviewer finds the 1 visible issue
        findings = [
            _make_finding(
                "F-1", PR_ID, FILE_PATH, 100, 105,
                "Found: issue at line 100",
            ),
        ]

        match_map = {
            "GT-1": "F-1",
            "GT-2": None,
            "GT-3": None,
            "GT-4": None,
        }
        judge = _DeterministicJudge(match_map)
        outcome = match_pr(pr, findings, judge)

        report = compute_metrics(
            prs=[pr],
            findings_by_pr={PR_ID: findings},
            outcomes=[outcome],
            reviewer_model="test-reviewer",
            judge_panel=["deterministic-test-judge"],
            evaluation_set="truncation-scaling-test",
        )

        # Total recall is still 1/4 = 0.25 (conservative).
        assert report.aggregate_recall == 1 / 4
        assert report.total_false_negatives == 3

        # Visible recall is 1/1 = 1.0 (fair).
        assert report.visible_recall == 1.0
        assert report.excluded_gt_issue_count == 3
