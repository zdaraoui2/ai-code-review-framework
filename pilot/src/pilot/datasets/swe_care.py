"""SWE-CARE dataset adapter.

Loads the SWE-CARE (Software Engineering - Code Analysis and Review
Evaluation) dataset and converts it to the pilot's PullRequest schema.
SWE-CARE provides human review comments on real Python and Java PRs,
with multi-faceted annotation including difficulty, review effort, and
problem domain classification.

Data source: https://huggingface.co/datasets/inclusionAI/SWE-CARE
License: Apache 2.0

The adapter loads the test split (671 verified instances) by default.
Each instance has one or more human review comments that serve as
ground truth issues, plus rich metadata including 9 PR problem domains.

Limitations:
- Ground truth comments are not classified by review dimension. The
  adapter maps SWE-CARE's 9 problem domains to framework dimensions
  where a reasonable mapping exists, and falls back to CORRECTNESS for
  ambiguous domains. Accurate per-dimension metrics require a
  classification step, either heuristic or LLM-based, applied after
  loading.
- Severity is not annotated in SWE-CARE. The adapter assigns MEDIUM as
  the default. Severity calibration metrics will not be meaningful
  without re-annotation.
- Change type is mapped from SWE-CARE's problem_domain where possible,
  with fallback to keyword inference from the PR title.
- SWE-CARE's difficulty metadata is preserved: it maps to
  GroundTruthIssue.difficulty (low->easy, medium->medium, hard->hard).
  The estimated_review_effort field is not carried through because the
  PullRequest schema has no slot for it. If needed, reload from the
  raw dataset.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    Severity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Problem domain mappings
# ---------------------------------------------------------------------------

# SWE-CARE's 9 problem domains -> framework ChangeType.
# These are rough mappings; some domains span multiple change types.
_DOMAIN_TO_CHANGE_TYPE: dict[str, ChangeType] = {
    "Bug Fixes": ChangeType.BUG_FIX,
    "New Feature Additions": ChangeType.NEW_FEATURE,
    "Documentation Updates": ChangeType.SIMPLE_REFACTORING,
    "Dependency Updates & Env Compatibility": ChangeType.DEPENDENCY_UPDATE,
    "Performance Optimizations": ChangeType.SIMPLE_REFACTORING,
    "Refactoring": ChangeType.SIMPLE_REFACTORING,
    "Testing Enhancements": ChangeType.SIMPLE_REFACTORING,
    "API Changes": ChangeType.NEW_FEATURE,
    "Configuration/Build System Changes": ChangeType.CONFIGURATION,
}

# SWE-CARE's 9 problem domains -> framework Dimension.
# Only mapped where the domain strongly implies a dimension. The rest
# fall back to CORRECTNESS (the c-CRAB default) and need classification.
_DOMAIN_TO_DIMENSION: dict[str, Dimension] = {
    "Bug Fixes": Dimension.CORRECTNESS,
    "New Feature Additions": Dimension.CORRECTNESS,
    "Documentation Updates": Dimension.DOCUMENTATION,
    "Dependency Updates & Env Compatibility": Dimension.CONFIGURATION,
    "Performance Optimizations": Dimension.PERFORMANCE,
    "Refactoring": Dimension.MAINTAINABILITY,
    "Testing Enhancements": Dimension.TEST_QUALITY,
    "API Changes": Dimension.API_DESIGN,
    "Configuration/Build System Changes": Dimension.CONFIGURATION,
}

# SWE-CARE difficulty values -> GroundTruthIssue difficulty.
_DIFFICULTY_MAP: dict[str, str] = {
    "low": "easy",
    "medium": "medium",
    "hard": "hard",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_swe_care(
    dataset_path: Path | str | None = None,
    *,
    split: str = "test",
    max_diff_chars: int | None = 50_000,
) -> list[PullRequest]:
    """Load SWE-CARE dataset and convert to PullRequest schema.

    Tries the HuggingFace ``datasets`` library first. Falls back to a
    local JSONL file if a path is provided or if the library is
    unavailable.

    Args:
        dataset_path: Path to a local JSONL export of SWE-CARE. When
            None, loads from HuggingFace Hub via the ``datasets``
            library.
        split: Which split to load. Defaults to ``"test"`` (671
            verified instances). Use ``"dev"`` for the full 7,086
            development set.
        max_diff_chars: Truncate diffs longer than this (None for no
            limit). SWE-CARE diffs can exceed 300K chars; most frontier
            models cannot process them in full. Default 50K covers the
            large majority of real PRs while fitting within typical
            context windows.

    Returns:
        List of PullRequest objects with ground truth issues derived
        from human review comments.
    """
    if dataset_path is not None:
        raw_instances = _load_from_file(Path(dataset_path))
    else:
        raw_instances = _load_from_huggingface(split)

    prs: list[PullRequest] = []
    for i, raw in enumerate(raw_instances):
        try:
            pr = _convert_instance(raw, max_diff_chars)
            if pr is not None:
                prs.append(pr)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(
                "Skipping SWE-CARE instance %d (%s): %s",
                i,
                raw.get("instance_id", "unknown"),
                e,
            )
            continue
    return prs


def get_dataset_stats(prs: list[PullRequest]) -> dict:
    """Compute summary statistics for a loaded SWE-CARE dataset."""
    from collections import Counter

    change_types = Counter(pr.change_type.value for pr in prs)
    languages = Counter(pr.language for pr in prs)
    n_gt = sum(len(pr.ground_truth) for pr in prs)
    diff_lengths = [len(pr.diff) for pr in prs]

    return {
        "n_prs": len(prs),
        "n_ground_truth_issues": n_gt,
        "gt_per_pr_mean": round(n_gt / len(prs), 2) if prs else 0,
        "change_type_distribution": dict(change_types),
        "language_distribution": dict(languages),
        "diff_length_median": (
            sorted(diff_lengths)[len(diff_lengths) // 2]
            if diff_lengths
            else 0
        ),
        "diff_length_max": max(diff_lengths) if diff_lengths else 0,
        "languages": sorted(set(pr.language for pr in prs)),
    }


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def _load_from_huggingface(split: str) -> list[dict]:
    """Load SWE-CARE from HuggingFace Hub using the ``datasets`` library."""
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "The 'datasets' library is required to load SWE-CARE from "
            "HuggingFace. Install it with: pip install datasets\n"
            "Alternatively, provide a local JSONL file path via "
            "dataset_path."
        )

    logger.info("Loading SWE-CARE '%s' split from HuggingFace Hub...", split)
    ds = load_dataset("inclusionAI/SWE-CARE", split=split)

    # Convert to list of dicts for uniform processing.
    return [dict(row) for row in ds]


def _load_from_file(dataset_path: Path) -> list[dict]:
    """Load SWE-CARE from a local JSONL file."""
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"SWE-CARE dataset not found at {dataset_path}. "
            "Either install the 'datasets' library to load from "
            "HuggingFace, or provide a valid path to a JSONL export."
        )

    instances: list[dict] = []
    with dataset_path.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                instances.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(
                    "Skipping malformed JSON at line %d: %s", line_num, e
                )
    return instances


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _convert_instance(
    raw: dict[str, Any],
    max_diff_chars: int | None,
) -> PullRequest | None:
    """Convert a single SWE-CARE instance to PullRequest."""
    instance_id = raw["instance_id"]
    title = raw.get("title", "")
    if not title:
        # Fall back to commit message, then to a generated title.
        commit_info = raw.get("commit_to_review")
        if isinstance(commit_info, dict):
            title = commit_info.get("head_commit_message", "")
        if not title:
            title = f"PR from {raw.get('repo', 'unknown')}"

    # Diff -- nested under commit_to_review.
    commit_info = raw.get("commit_to_review")
    if isinstance(commit_info, dict):
        diff = commit_info.get("patch_to_review", "")
    else:
        diff = ""

    if not diff:
        return None  # No diff = nothing to review.

    if max_diff_chars is not None and len(diff) > max_diff_chars:
        diff = (
            diff[:max_diff_chars]
            + f"\n\n[... truncated at {max_diff_chars} chars ...]"
        )

    # Language
    language = raw.get("language", "python").lower()

    # Metadata
    metadata = raw.get("metadata") or {}
    problem_domain = metadata.get("problem_domain", "")
    difficulty = _DIFFICULTY_MAP.get(
        metadata.get("difficulty", ""), None
    )

    # Change type -- prefer domain mapping, fall back to title inference.
    change_type = _DOMAIN_TO_CHANGE_TYPE.get(problem_domain)
    if change_type is None:
        change_type = _infer_change_type(title)

    # Default dimension from problem domain.
    default_dimension = _DOMAIN_TO_DIMENSION.get(
        problem_domain, Dimension.CORRECTNESS
    )

    # Ground truth issues from review comments.
    comments = raw.get("reference_review_comments", [])
    if not comments:
        return None  # No ground truth = cannot evaluate.

    ground_truth: list[GroundTruthIssue] = []
    for i, comment in enumerate(comments):
        gt = _convert_comment(
            comment, instance_id, i, default_dimension, difficulty
        )
        if gt is not None:
            ground_truth.append(gt)

    if not ground_truth:
        return None

    return PullRequest(
        pr_id=instance_id,
        title=title[:200],  # Truncate very long titles.
        language=language,
        change_type=change_type,
        diff=diff,
        ground_truth=ground_truth,
    )


def _convert_comment(
    comment: dict[str, Any],
    instance_id: str,
    index: int,
    default_dimension: Dimension,
    difficulty: str | None,
) -> GroundTruthIssue | None:
    """Convert a SWE-CARE review comment to a GroundTruthIssue."""
    text = comment.get("text", "").strip()
    if not text:
        return None

    file_path = comment.get("path", "unknown")

    # Line numbers can be None in SWE-CARE data.
    line = comment.get("line") or comment.get("start_line") or 1
    start_line = comment.get("start_line") or line
    end_line = comment.get("line") or start_line

    # Ensure start <= end.
    if start_line > end_line:
        start_line, end_line = end_line, start_line

    return GroundTruthIssue(
        issue_id=f"{instance_id}-C{index:03d}",
        pr_id=instance_id,
        dimension=default_dimension,
        severity=Severity.MEDIUM,  # Default -- needs annotation.
        location=Location(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        ),
        description=text[:2000],  # Truncate very long comment threads.
        difficulty=difficulty,
    )


def _infer_change_type(title: str) -> ChangeType:
    """Infer change type from PR title using keyword heuristics.

    This is a rough classification. Accurate change type labelling
    requires either human annotation or LLM-based classification.
    Shared with c-CRAB adapter logic.
    """
    title_lower = title.lower()

    if any(
        kw in title_lower
        for kw in ("fix", "bug", "patch", "hotfix", "resolve")
    ):
        return ChangeType.BUG_FIX
    if any(
        kw in title_lower
        for kw in ("refactor", "cleanup", "clean up", "reorgani")
    ):
        return ChangeType.SIMPLE_REFACTORING
    if any(
        kw in title_lower
        for kw in ("feat", "add", "implement", "support", "introduce")
    ):
        return ChangeType.NEW_FEATURE
    if any(
        kw in title_lower
        for kw in ("config", "setting", "env", "yml", "yaml", "toml")
    ):
        return ChangeType.CONFIGURATION
    if any(
        kw in title_lower
        for kw in ("dep", "upgrad", "bump", "version")
    ):
        return ChangeType.DEPENDENCY_UPDATE
    # Default: bug fix (most common in SWE-CARE).
    return ChangeType.BUG_FIX
