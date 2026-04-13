"""Greptile benchmark dataset adapter.

Loads the Greptile code review benchmark and converts it to the pilot's
PullRequest schema. Greptile provides 50 PRs across 5 major open-source
repositories, each containing known bug introductions traced to real
commits.

Data source: https://greptile.com/benchmarks (July 2025)
Repositories: Sentry (Python), Cal.com (TypeScript), Grafana (Go),
              Keycloak (Java), Discourse (Ruby) — 10 PRs each.

The benchmark is published as a webpage, not a downloadable dataset.
Users must prepare a local JSONL file from the published data. Each line
should be a JSON object with the following schema:

    {
        "pr_id": "sentry-1234",
        "repo": "sentry",
        "language": "python",
        "title": "Fix pagination for audit logs",
        "diff": "--- a/file.py\n+++ b/file.py\n...",
        "bugs": [
            {
                "description": "Negative slice on Django queryset",
                "file_path": "src/sentry/audit.py",
                "start_line": 42,
                "end_line": 45,
                "severity": "high"
            }
        ]
    }

Field reference:
    pr_id       Unique identifier (e.g. "sentry-1234" or the GH PR number).
    repo        Repository short name (sentry, calcom, grafana, keycloak,
                discourse).
    language    Programming language (python, typescript, go, java, ruby).
    title       PR title.
    diff        Unified diff of the PR.
    bugs        Array of known bugs introduced by this PR.
      description   What the bug is, in reviewer terms.
      file_path     File where the bug occurs.
      start_line    First line of the faulty code.
      end_line      Last line of the faulty code.
      severity      One of: critical, high, medium, low.

Scoring rule (from Greptile): a bug is counted as "caught" only when the
tool explicitly identifies the faulty code in a line-level comment AND
explains the impact. This adapter loads the ground truth; the matching
logic lives in the evaluation pipeline.

Limitations:
- Ground truth dimension is not annotated in Greptile. The adapter
  assigns CORRECTNESS as the default. Accurate per-dimension metrics
  require a classification step after loading.
- Change type is inferred from the PR title using keyword heuristics.
  Accurate change type labelling requires human annotation or LLM-based
  classification.
- Severity IS annotated in Greptile and maps directly to the framework's
  4-level scale (Low, Medium, High, Critical). This is used as-is.
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

_SEVERITY_MAP: dict[str, Severity] = {
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}

_REPO_LANGUAGE: dict[str, str] = {
    "sentry": "python",
    "calcom": "typescript",
    "cal.com": "typescript",
    "grafana": "go",
    "keycloak": "java",
    "discourse": "ruby",
}


def load_greptile(
    dataset_path: Path,
    max_diff_chars: int | None = 50_000,
) -> list[PullRequest]:
    """Load Greptile benchmark dataset and convert to PullRequest schema.

    Args:
        dataset_path: Path to the JSONL file prepared from Greptile's
            published benchmark data. See module docstring for the
            expected schema.
        max_diff_chars: Truncate diffs longer than this (None for no
            limit). Default 50K covers the large majority of real PRs
            while fitting within typical context windows.

    Returns:
        List of PullRequest objects with ground truth issues derived
        from Greptile's known bug annotations.
    """
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Greptile dataset not found at {dataset_path}. "
            "Prepare a JSONL file from https://greptile.com/benchmarks "
            "— see the module docstring for the expected schema."
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
                    "Skipping Greptile instance at line %d: %s", line_num, e
                )
                continue
    return prs


def _convert_instance(
    raw: dict,
    max_diff_chars: int | None,
) -> PullRequest | None:
    """Convert a single Greptile JSONL entry to PullRequest."""
    pr_id = raw["pr_id"]
    title = raw.get("title", f"PR {pr_id}")

    # Diff
    diff = raw.get("diff", "")
    if not diff:
        return None  # No diff = nothing to review.

    from pilot.datasets.truncation import truncate_diff, identify_excluded_gt_ids

    truncation_result = truncate_diff(diff, max_diff_chars)
    diff = truncation_result.diff

    # Language — from explicit field, falling back to repo name lookup
    language = raw.get("language", "").lower()
    if not language:
        repo = raw.get("repo", "").lower()
        language = _REPO_LANGUAGE.get(repo, "unknown")

    # Change type — infer from title keywords
    change_type = _infer_change_type(title)

    # Ground truth bugs
    bugs = raw.get("bugs", [])
    if not bugs:
        return None  # No ground truth = cannot evaluate.

    ground_truth: list[GroundTruthIssue] = []
    for i, bug in enumerate(bugs):
        gt = _convert_bug(bug, pr_id, i)
        if gt is not None:
            ground_truth.append(gt)

    if not ground_truth:
        return None

    excluded_gt_ids = identify_excluded_gt_ids(
        ground_truth,
        truncation_result.last_visible_line,
        truncation_result.truncated,
    )

    return PullRequest(
        pr_id=pr_id,
        title=title[:200],
        language=language,
        change_type=change_type,
        diff=diff,
        ground_truth=ground_truth,
        truncated=truncation_result.truncated,
        original_diff_length=truncation_result.original_diff_length,
        excluded_gt_ids=excluded_gt_ids,
    )


def _convert_bug(
    bug: dict,
    pr_id: str,
    index: int,
) -> GroundTruthIssue | None:
    """Convert a Greptile bug annotation to a GroundTruthIssue."""
    description = bug.get("description", "").strip()
    if not description:
        return None

    file_path = bug.get("file_path", "unknown")
    start_line = bug.get("start_line", 1)
    end_line = bug.get("end_line", start_line)

    # Ensure start <= end
    if start_line > end_line:
        start_line, end_line = end_line, start_line

    # Map severity — Greptile uses the same 4-level scale
    severity_str = bug.get("severity", "").lower()
    severity = _SEVERITY_MAP.get(severity_str)
    if severity is None:
        logger.warning(
            "Unknown severity %r for bug %d in PR %s, defaulting to MEDIUM",
            severity_str, index, pr_id,
        )
        severity = Severity.MEDIUM

    return GroundTruthIssue(
        issue_id=f"{pr_id}-B{index:03d}",
        pr_id=pr_id,
        dimension=Dimension.CORRECTNESS,  # Default — needs classification
        severity=severity,
        location=Location(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        ),
        description=description[:2000],
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
    # Default: bug fix (Greptile tracks bug introductions)
    return ChangeType.BUG_FIX


def get_dataset_stats(prs: list[PullRequest]) -> dict:
    """Compute summary statistics for a loaded Greptile dataset."""
    from collections import Counter

    change_types = Counter(pr.change_type.value for pr in prs)
    severities = Counter(
        gt.severity.name
        for pr in prs
        for gt in pr.ground_truth
    )
    n_gt = sum(len(pr.ground_truth) for pr in prs)
    diff_lengths = [len(pr.diff) for pr in prs]

    return {
        "n_prs": len(prs),
        "n_ground_truth_issues": n_gt,
        "gt_per_pr_mean": n_gt / len(prs) if prs else 0,
        "change_type_distribution": dict(change_types),
        "severity_distribution": dict(severities),
        "diff_length_median": sorted(diff_lengths)[len(diff_lengths) // 2] if diff_lengths else 0,
        "diff_length_max": max(diff_lengths) if diff_lengths else 0,
        "languages": sorted(set(pr.language for pr in prs)),
        "repos": sorted(set(
            pr.pr_id.rsplit("-", 1)[0]
            for pr in prs
            if "-" in pr.pr_id
        )),
    }
