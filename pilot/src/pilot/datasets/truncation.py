"""Shared diff truncation logic for dataset adapters.

When a diff is truncated at max_diff_chars, GT issues referencing code
past the truncation point are invisible to the reviewer. This module
provides helpers to:
1. Truncate a diff and record metadata.
2. Estimate the last visible line number from the truncated diff.
3. Identify GT issues whose locations fall past the truncation point.
"""

from __future__ import annotations

from dataclasses import dataclass

from pilot.schemas import GroundTruthIssue


@dataclass(frozen=True)
class TruncationResult:
    """Result of truncating a diff."""

    diff: str
    truncated: bool
    original_diff_length: int | None
    last_visible_line: int


def truncate_diff(
    diff: str,
    max_diff_chars: int | None,
) -> TruncationResult:
    """Truncate a diff and compute truncation metadata.

    Args:
        diff: The original diff text.
        max_diff_chars: Character limit. None means no truncation.

    Returns:
        TruncationResult with the (possibly truncated) diff, whether
        truncation occurred, the original length, and an estimate of
        the last line number visible in the truncated diff.
    """
    if max_diff_chars is None or len(diff) <= max_diff_chars:
        # No truncation — count all lines in the full diff.
        last_line = _estimate_last_diff_line(diff)
        return TruncationResult(
            diff=diff,
            truncated=False,
            original_diff_length=None,
            last_visible_line=last_line,
        )

    original_length = len(diff)
    visible_portion = diff[:max_diff_chars]
    last_visible_line = _estimate_last_diff_line(visible_portion)

    truncated_diff = (
        visible_portion
        + f"\n\n[... truncated at {max_diff_chars} chars ...]"
    )

    return TruncationResult(
        diff=truncated_diff,
        truncated=True,
        original_diff_length=original_length,
        last_visible_line=last_visible_line,
    )


def identify_excluded_gt_ids(
    ground_truth: list[GroundTruthIssue],
    last_visible_line: int,
    truncated: bool,
) -> list[str]:
    """Return IDs of GT issues whose locations fall past the truncation point.

    This is a heuristic: diff line numbers in @@ headers don't map
    perfectly to character offsets, and GT locations are in file
    coordinates, not diff coordinates. But it's a reasonable
    approximation — if a GT issue's start_line exceeds the highest
    line number mentioned in the visible portion of the diff, the
    reviewer almost certainly cannot see it.

    Args:
        ground_truth: All GT issues for the PR.
        last_visible_line: Estimated last line number visible in the
            truncated diff.
        truncated: Whether the diff was actually truncated. If False,
            returns an empty list (all GT is visible).

    Returns:
        List of issue IDs for GT issues likely in the truncated region.
    """
    if not truncated:
        return []

    excluded_ids: list[str] = []
    for gt_issue in ground_truth:
        if gt_issue.location.start_line > last_visible_line:
            excluded_ids.append(gt_issue.issue_id)
    return excluded_ids


def _estimate_last_diff_line(diff_text: str) -> int:
    """Estimate the highest new-file line number visible in a diff.

    Walks the diff line by line, tracking the current new-file line
    number through hunk headers and content lines. This is more
    accurate than trusting hunk header lengths, which may claim more
    lines than are actually present (e.g. when the diff is truncated
    mid-hunk).

    Context lines (' ') and addition lines ('+') advance the new-file
    line counter. Deletion lines ('-') do not — they belong to the
    old file only.

    Falls back to counting newlines if no hunk headers are found.
    """
    import re

    hunk_pattern = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    current_new_line = 0
    highest_new_line = 0
    in_hunk = False

    for line in diff_text.split("\n"):
        hunk_match = hunk_pattern.search(line)
        if hunk_match:
            # Entering a new hunk — reset the new-file line counter to
            # the hunk's declared start.
            current_new_line = int(hunk_match.group(1))
            in_hunk = True
            # The first content line of this hunk will be at current_new_line,
            # so don't increment yet.
            continue

        if not in_hunk:
            continue

        if line.startswith("+"):
            # Addition: this line exists in the new file.
            if current_new_line > highest_new_line:
                highest_new_line = current_new_line
            current_new_line += 1
        elif line.startswith("-"):
            # Deletion: old-file only, does not advance new-file counter.
            pass
        elif line.startswith("\\"):
            # "\ No newline at end of file" — metadata, skip.
            pass
        else:
            # Context line (starts with ' ' or is empty): present in
            # both old and new files.
            if current_new_line > highest_new_line:
                highest_new_line = current_new_line
            current_new_line += 1

    if highest_new_line > 0:
        return highest_new_line

    # Fallback: count newlines as a rough proxy. This is imprecise but
    # better than nothing when the diff lacks hunk headers (e.g. it's
    # a raw patch without @@ markers).
    return diff_text.count("\n")
