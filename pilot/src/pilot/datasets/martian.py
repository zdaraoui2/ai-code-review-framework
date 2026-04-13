"""Martian code review benchmark dataset adapter.

Loads the Martian code review benchmark and converts it to the pilot's
PullRequest schema. Martian provides 50 curated PRs across 5 major
open-source repositories with human-curated golden comments and severity
labels.

Data source: https://github.com/withmartian/code-review-benchmark
Licence: MIT
Repositories: Sentry (Python), Cal.com (TypeScript), Grafana (Go),
              Keycloak (Java), Discourse (Ruby) — 10 PRs each.

Loading modes:
    1. From a cloned copy of the Martian repo — point ``repo_path`` at
       the repository root. The adapter reads golden comments from
       ``offline/golden_comments/*.json`` and enriches with metadata
       from ``offline/results/pr_labels.json``.
    2. From a pre-assembled JSONL file — point ``jsonl_path`` at the
       file. Use this when you have already fetched diffs and assembled
       the data into the schema described below.

Exactly one of ``repo_path`` or ``jsonl_path`` must be provided.

Repository layout (when using ``repo_path``):
    offline/
        golden_comments/
            sentry.json         # Array of PR objects
            grafana.json
            keycloak.json
            discourse.json
            cal_dot_com.json
        results/
            pr_labels.json      # Metadata keyed by original PR URL
            benchmark_data.json # Full benchmark data including tool reviews

Golden comment JSON schema (per repo file):
    [
        {
            "pr_title": "Fix pagination for audit logs",
            "url": "https://github.com/ai-code-review-evaluation/sentry-greptile/pull/1",
            "original_url": "https://github.com/getsentry/sentry/pull/93824",
            "comments": [
                {
                    "comment": "Negative slice on Django queryset",
                    "severity": "High"
                }
            ]
        }
    ]

PR labels JSON schema (pr_labels.json):
    {
        "https://github.com/keycloak/keycloak/pull/37429": {
            "derived": {
                "language": "Java",
                "num_golden_comments": 4,
                "severity_mix": {"Medium": 2, "Low": 2},
                "num_files_touched": 4
            },
            "llm_pr_labels": {
                "change_type": "feature",
                ...
            }
        }
    }

Pre-assembled JSONL schema (for ``jsonl_path`` mode):
    {
        "pr_id": "keycloak-37429",
        "repo": "keycloak",
        "language": "java",
        "title": "Fixing Re-authentication with passkeys",
        "diff": "--- a/file.java\\n+++ b/file.java\\n...",
        "comments": [
            {
                "comment": "Description of the issue",
                "severity": "High"
            }
        ]
    }

Limitations:
- Golden comments are location-agnostic by design. They describe semantic
  issues without file paths or line numbers. The adapter sets Location to
  file_path="unknown", start_line=1, end_line=1. Matching must therefore
  be done semantically (e.g. by an LLM judge), not by line overlap.
- Ground truth dimension is not annotated. The adapter assigns CORRECTNESS
  as the default. Accurate per-dimension metrics require classification
  after loading.
- When loading from the repo (``repo_path`` mode), diffs are NOT included
  in the golden comment files. You must either:
    (a) supply a ``diff_dir`` containing one ``.diff`` file per PR
        (named by pr_id, e.g. ``keycloak-37429.diff``), or
    (b) accept empty diffs (the adapter will set diff to a placeholder).
  The JSONL mode expects diffs inline.
- Severity IS annotated in Martian (Low/Medium/High/Critical) and maps
  directly to the framework's 4-level scale.
- Change type is taken from pr_labels.json when available, otherwise
  inferred from the PR title.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)

_SEVERITY_MAP: dict[str, Severity] = {
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}

_CHANGE_TYPE_MAP: dict[str, ChangeType] = {
    "feature": ChangeType.NEW_FEATURE,
    "bug_fix": ChangeType.BUG_FIX,
    "bugfix": ChangeType.BUG_FIX,
    "refactoring": ChangeType.SIMPLE_REFACTORING,
    "refactor": ChangeType.SIMPLE_REFACTORING,
    "config": ChangeType.CONFIGURATION,
    "configuration": ChangeType.CONFIGURATION,
    "dependency": ChangeType.DEPENDENCY_UPDATE,
    "dependency_update": ChangeType.DEPENDENCY_UPDATE,
    "architectural_refactoring": ChangeType.ARCHITECTURAL_REFACTORING,
}

_REPO_FILENAMES: dict[str, str] = {
    "sentry.json": "sentry",
    "grafana.json": "grafana",
    "keycloak.json": "keycloak",
    "discourse.json": "discourse",
    "cal_dot_com.json": "calcom",
}

_REPO_LANGUAGE: dict[str, str] = {
    "sentry": "python",
    "grafana": "go",
    "keycloak": "java",
    "discourse": "ruby",
    "calcom": "typescript",
}


def load_martian(
    repo_path: Path | None = None,
    jsonl_path: Path | None = None,
    diff_dir: Path | None = None,
    max_diff_chars: int | None = 50_000,
) -> list[PullRequest]:
    """Load Martian benchmark dataset and convert to PullRequest schema.

    Provide exactly one of ``repo_path`` or ``jsonl_path``.

    Args:
        repo_path: Path to the cloned withmartian/code-review-benchmark
            repository root. The adapter reads golden comments and
            pr_labels from the offline/ directory.
        jsonl_path: Path to a pre-assembled JSONL file with diffs
            already included (see module docstring for schema).
        diff_dir: Optional directory containing .diff files named by
            pr_id (e.g. keycloak-37429.diff). Only used in repo_path
            mode. If not provided, diffs will be empty.
        max_diff_chars: Truncate diffs longer than this (None for no
            limit). Default 50K covers the large majority of real PRs
            while fitting within typical context windows.

    Returns:
        List of PullRequest objects with ground truth issues derived
        from Martian's golden comment annotations.

    Raises:
        ValueError: If both or neither of repo_path and jsonl_path are
            provided.
        FileNotFoundError: If specified paths do not exist.
    """
    if (repo_path is None) == (jsonl_path is None):
        raise ValueError(
            "Provide exactly one of repo_path or jsonl_path, not both."
        )

    if jsonl_path is not None:
        return _load_from_jsonl(jsonl_path, max_diff_chars)

    assert repo_path is not None
    return _load_from_repo(repo_path, diff_dir, max_diff_chars)


# ── Repo-based loading ──────────────────────────────────────────────


def _load_from_repo(
    repo_path: Path,
    diff_dir: Path | None,
    max_diff_chars: int | None,
) -> list[PullRequest]:
    """Load from a cloned copy of the Martian repo."""
    golden_dir = repo_path / "offline" / "golden_comments"
    if not golden_dir.is_dir():
        raise FileNotFoundError(
            f"Golden comments directory not found at {golden_dir}. "
            "Clone https://github.com/withmartian/code-review-benchmark "
            "and point repo_path at the repository root."
        )

    # Load PR metadata from pr_labels.json if available
    labels_path = repo_path / "offline" / "results" / "pr_labels.json"
    pr_labels: dict = {}
    if labels_path.exists():
        with labels_path.open() as f:
            pr_labels = json.load(f)

    prs: list[PullRequest] = []

    for filename, repo_name in _REPO_FILENAMES.items():
        file_path = golden_dir / filename
        if not file_path.exists():
            logger.warning("Golden comments file not found: %s", file_path)
            continue

        with file_path.open() as f:
            entries = json.load(f)

        for entry_idx, entry in enumerate(entries):
            try:
                pr = _convert_repo_entry(
                    entry, repo_name, entry_idx, pr_labels,
                    diff_dir, max_diff_chars,
                )
                if pr is not None:
                    prs.append(pr)
            except (KeyError, ValueError) as e:
                logger.warning(
                    "Skipping Martian entry %d in %s: %s",
                    entry_idx, filename, e,
                )
                continue

    return prs


def _convert_repo_entry(
    entry: dict,
    repo_name: str,
    entry_idx: int,
    pr_labels: dict,
    diff_dir: Path | None,
    max_diff_chars: int | None,
) -> PullRequest | None:
    """Convert a single golden comment entry to PullRequest."""
    title = entry.get("pr_title", f"PR from {repo_name}")

    # Derive pr_id from the URL
    url = entry.get("original_url") or entry.get("url", "")
    pr_id = _pr_id_from_url(url, repo_name, entry_idx)

    # Look up metadata from pr_labels.json
    # Labels are keyed by various URL forms — try both original and fork
    labels = (
        pr_labels.get(entry.get("original_url", ""), {})
        or pr_labels.get(entry.get("url", ""), {})
    )
    derived = labels.get("derived", {})
    llm_labels = labels.get("llm_pr_labels", {})

    # Language
    language = derived.get("language", "").lower()
    if not language:
        language = _REPO_LANGUAGE.get(repo_name, "unknown")

    # Change type
    change_type_str = llm_labels.get("change_type", "")
    change_type = _CHANGE_TYPE_MAP.get(
        change_type_str, _infer_change_type(title)
    )

    # Diff — try to load from diff_dir
    diff = ""
    if diff_dir is not None:
        diff_file = diff_dir / f"{pr_id}.diff"
        if diff_file.exists():
            diff = diff_file.read_text(errors="replace")

    if not diff:
        diff = f"[Diff not available — fetch from {url}]"

    if max_diff_chars is not None and len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + f"\n\n[... truncated at {max_diff_chars} chars ...]"

    # Ground truth from golden comments
    comments = entry.get("comments", [])
    if not comments:
        return None

    ground_truth: list[GroundTruthIssue] = []
    for i, comment in enumerate(comments):
        gt = _convert_golden_comment(comment, pr_id, i)
        if gt is not None:
            ground_truth.append(gt)

    if not ground_truth:
        return None

    return PullRequest(
        pr_id=pr_id,
        title=title[:200],
        language=language,
        change_type=change_type,
        diff=diff,
        ground_truth=ground_truth,
    )


def _pr_id_from_url(url: str, repo_name: str, fallback_idx: int) -> str:
    """Extract a stable pr_id from a GitHub PR URL.

    Prefers the original_url (e.g. keycloak/keycloak/pull/37429 ->
    keycloak-37429). Falls back to repo_name-idx.
    """
    match = re.search(r"/pull/(\d+)", url)
    if match:
        return f"{repo_name}-{match.group(1)}"
    return f"{repo_name}-{fallback_idx}"


# ── JSONL-based loading ─────────────────────────────────────────────


def _load_from_jsonl(
    jsonl_path: Path,
    max_diff_chars: int | None,
) -> list[PullRequest]:
    """Load from a pre-assembled JSONL file."""
    if not jsonl_path.exists():
        raise FileNotFoundError(
            f"Martian JSONL file not found at {jsonl_path}. "
            "See the module docstring for the expected schema."
        )

    prs: list[PullRequest] = []
    with jsonl_path.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                pr = _convert_jsonl_entry(raw, max_diff_chars)
                if pr is not None:
                    prs.append(pr)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(
                    "Skipping Martian JSONL entry at line %d: %s",
                    line_num, e,
                )
                continue
    return prs


def _convert_jsonl_entry(
    raw: dict,
    max_diff_chars: int | None,
) -> PullRequest | None:
    """Convert a single JSONL entry to PullRequest."""
    pr_id = raw["pr_id"]
    title = raw.get("title", f"PR {pr_id}")

    diff = raw.get("diff", "")
    if not diff:
        diff = "[Diff not provided]"

    if max_diff_chars is not None and len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + f"\n\n[... truncated at {max_diff_chars} chars ...]"

    language = raw.get("language", "").lower()
    if not language:
        repo = raw.get("repo", "").lower()
        language = _REPO_LANGUAGE.get(repo, "unknown")

    change_type = _infer_change_type(title)

    comments = raw.get("comments", [])
    if not comments:
        return None

    ground_truth: list[GroundTruthIssue] = []
    for i, comment in enumerate(comments):
        gt = _convert_golden_comment(comment, pr_id, i)
        if gt is not None:
            ground_truth.append(gt)

    if not ground_truth:
        return None

    return PullRequest(
        pr_id=pr_id,
        title=title[:200],
        language=language,
        change_type=change_type,
        diff=diff,
        ground_truth=ground_truth,
    )


# ── Shared helpers ───────────────────────────────────────────────────


def _convert_golden_comment(
    comment: dict,
    pr_id: str,
    index: int,
) -> GroundTruthIssue | None:
    """Convert a Martian golden comment to a GroundTruthIssue.

    Martian golden comments are location-agnostic: they describe the
    semantic issue without file paths or line numbers. The Location is
    set to a placeholder. Matching must be done semantically.
    """
    text = comment.get("comment", "").strip()
    if not text:
        return None

    # Map severity — Martian uses the same 4-level scale
    severity_str = comment.get("severity", "").lower()
    severity = _SEVERITY_MAP.get(severity_str)
    if severity is None:
        logger.warning(
            "Unknown severity %r for comment %d in PR %s, defaulting to MEDIUM",
            severity_str, index, pr_id,
        )
        severity = Severity.MEDIUM

    return GroundTruthIssue(
        issue_id=f"{pr_id}-G{index:03d}",
        pr_id=pr_id,
        dimension=Dimension.CORRECTNESS,  # Default — needs classification
        severity=severity,
        location=Location(
            file_path="unknown",
            start_line=1,
            end_line=1,
        ),
        description=text[:2000],
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
    # Default: new feature (most Martian PRs are feature additions)
    return ChangeType.NEW_FEATURE


def get_dataset_stats(prs: list[PullRequest]) -> dict:
    """Compute summary statistics for a loaded Martian dataset."""
    from collections import Counter

    change_types = Counter(pr.change_type.value for pr in prs)
    severities = Counter(
        gt.severity.name
        for pr in prs
        for gt in pr.ground_truth
    )
    n_gt = sum(len(pr.ground_truth) for pr in prs)
    diff_lengths = [len(pr.diff) for pr in prs]
    has_real_diff = sum(
        1 for pr in prs
        if not pr.diff.startswith("[Diff not")
    )

    return {
        "n_prs": len(prs),
        "n_ground_truth_issues": n_gt,
        "gt_per_pr_mean": n_gt / len(prs) if prs else 0,
        "change_type_distribution": dict(change_types),
        "severity_distribution": dict(severities),
        "diff_length_median": sorted(diff_lengths)[len(diff_lengths) // 2] if diff_lengths else 0,
        "diff_length_max": max(diff_lengths) if diff_lengths else 0,
        "prs_with_diff": has_real_diff,
        "prs_without_diff": len(prs) - has_real_diff,
        "languages": sorted(set(pr.language for pr in prs)),
        "location_agnostic": True,  # Martian golden comments lack file/line info
    }
