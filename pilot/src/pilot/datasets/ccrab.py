"""c-CRAB dataset adapter.

Loads the c-CRAB (Code Review Agent Benchmark) dataset and converts it to
the pilot's PullRequest schema. c-CRAB provides human review comments on
real Python PRs, filtered to HIGH quality, with optional test-based
verification for a 184-instance subset.

Data source: https://github.com/c-CRAB-Benchmark/dataset
Paper: arXiv:2603.23448

The adapter loads from results_preprocessed/preprocess_dataset.jsonl (410
instances). Each instance has one or more human review comments that serve
as ground truth issues.

Limitations:
- Ground truth comments are not classified by review dimension. The adapter
  assigns a default dimension (CORRECTNESS) and marks it as unclassified.
  Accurate per-dimension metrics require a classification step, either
  heuristic or LLM-based, applied after loading.
- Severity is not annotated in c-CRAB. The adapter assigns MEDIUM as the
  default. Severity calibration metrics will not be meaningful without
  re-annotation.
- Change type is not annotated. The adapter infers from keywords in the
  PR title when possible, otherwise defaults to BUG_FIX.
- All instances are Python.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    Severity,
)


def load_ccrab(
    dataset_path: Path,
    max_diff_chars: int | None = 50_000,
) -> list[PullRequest]:
    """Load c-CRAB dataset and convert to PullRequest schema.

    Args:
        dataset_path: Path to preprocess_dataset.jsonl.
        max_diff_chars: Truncate diffs longer than this (None for no limit).
            c-CRAB diffs can be 300K+ chars; most frontier models cannot
            process them in full. Default 50K covers the large majority
            of real PRs while fitting within typical context windows.

    Returns:
        List of PullRequest objects with ground truth issues derived from
        human review comments.
    """
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"c-CRAB dataset not found at {dataset_path}. "
            "Clone https://github.com/c-CRAB-Benchmark/dataset and point "
            "to results_preprocessed/preprocess_dataset.jsonl"
        )

    prs: list[PullRequest] = []
    with dataset_path.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                pr = _convert_instance(raw, max_diff_chars)
                if pr is not None:
                    prs.append(pr)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                # Skip malformed entries rather than failing the whole load.
                import logging
                logging.getLogger(__name__).warning(
                    "Skipping c-CRAB instance at line %d: %s", line_num, e
                )
                continue
    return prs


def _convert_instance(
    raw: dict,
    max_diff_chars: int | None,
) -> PullRequest | None:
    """Convert a single c-CRAB instance to PullRequest."""
    instance_id = raw["instance_id"]
    title = raw.get("title") or raw.get("commit_to_review", {}).get(
        "head_commit_message", f"PR from {raw.get('repo', 'unknown')}"
    )

    # Diff
    diff = raw.get("commit_to_review", {}).get("patch_to_review", "")
    if not diff:
        return None  # No diff = nothing to review.

    if max_diff_chars is not None and len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + f"\n\n[... truncated at {max_diff_chars} chars ...]"

    # Language (c-CRAB is Python-only but the field exists)
    language = raw.get("language", "Python").lower()

    # Change type — infer from title keywords
    change_type = _infer_change_type(title)

    # Ground truth issues from review comments
    comments = raw.get("reference_review_comments", [])
    if not comments:
        return None  # No ground truth = cannot evaluate.

    ground_truth: list[GroundTruthIssue] = []
    for i, comment in enumerate(comments):
        gt = _convert_comment(comment, instance_id, i)
        if gt is not None:
            ground_truth.append(gt)

    if not ground_truth:
        return None

    return PullRequest(
        pr_id=instance_id,
        title=title[:200],  # Truncate very long titles
        language=language,
        change_type=change_type,
        diff=diff,
        ground_truth=ground_truth,
    )


def _convert_comment(
    comment: dict,
    instance_id: str,
    index: int,
) -> GroundTruthIssue | None:
    """Convert a c-CRAB review comment to a GroundTruthIssue."""
    text = comment.get("text", "").strip()
    if not text:
        return None

    file_path = comment.get("path", "unknown")
    # Line numbers can be None in c-CRAB data.
    line = comment.get("line") or comment.get("start_line") or 1
    start_line = comment.get("start_line") or line
    end_line = comment.get("line") or start_line

    # Ensure start <= end
    if start_line > end_line:
        start_line, end_line = end_line, start_line

    return GroundTruthIssue(
        issue_id=f"{instance_id}-C{index:03d}",
        pr_id=instance_id,
        dimension=Dimension.CORRECTNESS,  # Default — needs classification
        severity=Severity.MEDIUM,  # Default — needs annotation
        location=Location(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        ),
        description=text[:2000],  # Truncate very long comment threads
    )


def _infer_change_type(title: str) -> ChangeType:
    """Infer change type from PR title using keyword heuristics.

    This is a rough classification. Accurate change type labelling
    requires either human annotation or LLM-based classification.
    """
    title_lower = title.lower()

    if any(kw in title_lower for kw in ("fix", "bug", "patch", "hotfix", "resolve")):
        return ChangeType.BUG_FIX
    if any(kw in title_lower for kw in ("refactor", "cleanup", "clean up", "reorgani")):
        return ChangeType.SIMPLE_REFACTORING
    if any(kw in title_lower for kw in ("feat", "add", "implement", "support", "introduce")):
        return ChangeType.NEW_FEATURE
    if any(kw in title_lower for kw in ("config", "setting", "env", "yml", "yaml", "toml")):
        return ChangeType.CONFIGURATION
    if any(kw in title_lower for kw in ("dep", "upgrad", "bump", "version")):
        return ChangeType.DEPENDENCY_UPDATE
    # Default: bug fix (most common in SWE-CARE which c-CRAB derives from)
    return ChangeType.BUG_FIX


def get_dataset_stats(prs: list[PullRequest]) -> dict:
    """Compute summary statistics for a loaded c-CRAB dataset."""
    from collections import Counter

    change_types = Counter(pr.change_type.value for pr in prs)
    n_gt = sum(len(pr.ground_truth) for pr in prs)
    diff_lengths = [len(pr.diff) for pr in prs]

    return {
        "n_prs": len(prs),
        "n_ground_truth_issues": n_gt,
        "gt_per_pr_mean": n_gt / len(prs) if prs else 0,
        "change_type_distribution": dict(change_types),
        "diff_length_median": sorted(diff_lengths)[len(diff_lengths) // 2] if diff_lengths else 0,
        "diff_length_max": max(diff_lengths) if diff_lengths else 0,
        "languages": list(set(pr.language for pr in prs)),
    }
