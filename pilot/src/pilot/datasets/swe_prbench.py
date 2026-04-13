"""SWE-PRBench dataset adapter.

Loads the SWE-PRBench (SWE Pull Request Benchmark) dataset and converts
it to the pilot's PullRequest schema. SWE-PRBench provides 350 PRs from
65 repositories with human review comments as ground truth, collected
from actual merged PRs on GitHub.

Multi-language: Python ~69%, JavaScript ~11%, Go ~10%, TypeScript ~6%,
Java ~4%.

Data source: https://huggingface.co/datasets/foundry-ai/swe-prbench
Paper: arXiv:2603.26130

The adapter loads from HuggingFace via the `datasets` library, or from
a local JSONL file for offline use. Each PR has one or more human review
comments that serve as ground truth issues.

Limitations:
- Ground truth comments are not classified by review dimension. The
  adapter assigns a default dimension (CORRECTNESS) and marks it as
  unclassified. Accurate per-dimension metrics require a classification
  step, either heuristic or LLM-based, applied after loading.
- Severity is not annotated in SWE-PRBench. The adapter assigns MEDIUM
  as the default. Severity calibration metrics will not be meaningful
  without re-annotation.
- Change type is partially annotated via pr_type (feature, bug_fix).
  The adapter maps known values and falls back to keyword heuristics
  on the PR title for unknown types.
- Difficulty is annotated per-PR (Type1_Direct, Type2_Contextual,
  Type3_Latent) but mapped to the GroundTruthIssue difficulty field
  only at PR level, not per-comment.
- Review comment line numbers may be null. The adapter defaults to
  line 1 when missing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    Severity,
)

logger = logging.getLogger(__name__)

# ---- pr_type to ChangeType mapping ----

_PR_TYPE_MAP: dict[str, ChangeType] = {
    "bug_fix": ChangeType.BUG_FIX,
    "feature": ChangeType.NEW_FEATURE,
    "refactor": ChangeType.SIMPLE_REFACTORING,
    "enhancement": ChangeType.NEW_FEATURE,
}

# ---- Difficulty string to schema literal mapping ----

_DIFFICULTY_MAP: dict[str, str] = {
    "Type1_Direct": "easy",
    "Type2_Contextual": "medium",
    "Type3_Latent": "hard",
    # Some entries have "_Candidate" suffix
    "Type1_Direct_Candidate": "easy",
    "Type2_Contextual_Candidate": "medium",
    "Type3_Latent_Candidate": "hard",
}


def load_swe_prbench(
    dataset_path: Path | str | None = None,
    *,
    max_diff_chars: int | None = 50_000,
    hf_split: str = "prs",
) -> list[PullRequest]:
    """Load SWE-PRBench dataset and convert to PullRequest schema.

    Tries two loading strategies in order:
    1. If ``dataset_path`` points to a local JSONL file, load from there.
    2. Otherwise, attempt to load from HuggingFace using the ``datasets``
       library (``foundry-ai/swe-prbench``).

    Args:
        dataset_path: Path to a local JSONL file. When None, the adapter
            attempts HuggingFace download.
        max_diff_chars: Truncate diffs longer than this (None for no
            limit). SWE-PRBench diffs can reach ~70K chars. Default 50K
            covers the large majority of real PRs while fitting within
            typical context windows.
        hf_split: HuggingFace dataset config/split to load. The dataset
            has two configs: ``prs`` (350 PRs, full dataset) and
            ``eval_split`` (100-PR stratified sample used in the paper).

    Returns:
        List of PullRequest objects with ground truth issues derived
        from human review comments.
    """
    if dataset_path is not None:
        return _load_from_jsonl(Path(dataset_path), max_diff_chars)
    return _load_from_huggingface(max_diff_chars, hf_split)


def _load_from_huggingface(
    max_diff_chars: int | None,
    hf_split: str,
) -> list[PullRequest]:
    """Load from HuggingFace using the datasets library."""
    try:
        from datasets import load_dataset
    except ImportError as e:
        raise ImportError(
            "The `datasets` library is required to load SWE-PRBench from "
            "HuggingFace. Install it with: pip install datasets\n"
            "Alternatively, pass a local JSONL path via dataset_path."
        ) from e

    logger.info("Loading SWE-PRBench from HuggingFace (config=%s)...", hf_split)
    ds = load_dataset("foundry-ai/swe-prbench", hf_split, split="train")

    prs: list[PullRequest] = []
    for i, row in enumerate(ds):
        try:
            pr = _convert_instance(dict(row), max_diff_chars)
            if pr is not None:
                prs.append(pr)
        except (KeyError, ValueError) as e:
            logger.warning(
                "Skipping SWE-PRBench instance at index %d: %s", i, e
            )
            continue

    logger.info("Loaded %d PRs from SWE-PRBench.", len(prs))
    return prs


def _load_from_jsonl(
    dataset_path: Path,
    max_diff_chars: int | None,
) -> list[PullRequest]:
    """Load from a local JSONL file."""
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"SWE-PRBench dataset not found at {dataset_path}. "
            "Download from https://huggingface.co/datasets/foundry-ai/swe-prbench "
            "or omit dataset_path to load via the datasets library."
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
                logger.warning(
                    "Skipping SWE-PRBench instance at line %d: %s",
                    line_num, e,
                )
                continue

    logger.info("Loaded %d PRs from %s.", len(prs), dataset_path)
    return prs


def _convert_instance(
    raw: dict,
    max_diff_chars: int | None,
) -> PullRequest | None:
    """Convert a single SWE-PRBench instance to PullRequest."""
    task_id = raw["task_id"]
    title = raw.get("title", f"PR from {raw.get('repo', 'unknown')}")

    # Diff
    diff = raw.get("diff_patch", "")
    if not diff:
        return None  # No diff = nothing to review.

    if max_diff_chars is not None and len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + (
            f"\n\n[... truncated at {max_diff_chars} chars ...]"
        )

    # Language
    language = raw.get("language", "unknown").lower()

    # Change type -- use pr_type if available, fall back to title heuristics
    pr_type = raw.get("pr_type", "")
    change_type = _PR_TYPE_MAP.get(pr_type, _infer_change_type(title))

    # Difficulty -- mapped from SWE-PRBench taxonomy to easy/medium/hard
    difficulty_raw = raw.get("difficulty", "")
    difficulty = _DIFFICULTY_MAP.get(difficulty_raw)

    # Ground truth issues from human review comments
    comments = raw.get("human_review_comments", [])
    if not comments:
        return None  # No ground truth = cannot evaluate.

    ground_truth: list[GroundTruthIssue] = []
    for i, comment in enumerate(comments):
        gt = _convert_comment(comment, task_id, i, difficulty)
        if gt is not None:
            ground_truth.append(gt)

    if not ground_truth:
        return None

    return PullRequest(
        pr_id=task_id,
        title=title[:200],  # Truncate very long titles
        language=language,
        change_type=change_type,
        diff=diff,
        ground_truth=ground_truth,
    )


def _convert_comment(
    comment: dict,
    task_id: str,
    index: int,
    difficulty: str | None,
) -> GroundTruthIssue | None:
    """Convert a SWE-PRBench human review comment to a GroundTruthIssue."""
    text = comment.get("body", "").strip()
    if not text:
        return None

    file_path = comment.get("path") or "unknown"

    # Line number can be null in SWE-PRBench data.
    line = comment.get("line") or 1
    # SWE-PRBench comments have a single line field, not start/end.
    start_line = line
    end_line = line

    return GroundTruthIssue(
        issue_id=f"{task_id}-C{index:03d}",
        pr_id=task_id,
        dimension=Dimension.CORRECTNESS,  # Default -- needs classification
        severity=Severity.MEDIUM,  # Default -- needs annotation
        location=Location(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        ),
        description=text[:2000],  # Truncate very long comment threads
        difficulty=difficulty,
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
    # Default: bug fix (most common change type across benchmarks)
    return ChangeType.BUG_FIX


def get_dataset_stats(prs: list[PullRequest]) -> dict:
    """Compute summary statistics for a loaded SWE-PRBench dataset."""
    from collections import Counter

    change_types = Counter(pr.change_type.value for pr in prs)
    n_gt = sum(len(pr.ground_truth) for pr in prs)
    diff_lengths = [len(pr.diff) for pr in prs]
    languages = Counter(pr.language for pr in prs)
    difficulties = Counter(
        gt.difficulty
        for pr in prs
        for gt in pr.ground_truth
        if gt.difficulty is not None
    )

    return {
        "n_prs": len(prs),
        "n_ground_truth_issues": n_gt,
        "gt_per_pr_mean": round(n_gt / len(prs), 2) if prs else 0,
        "change_type_distribution": dict(change_types),
        "language_distribution": dict(languages),
        "difficulty_distribution": dict(difficulties),
        "diff_length_median": sorted(diff_lengths)[len(diff_lengths) // 2]
        if diff_lengths
        else 0,
        "diff_length_max": max(diff_lengths) if diff_lengths else 0,
        "languages": sorted(set(pr.language for pr in prs)),
    }
