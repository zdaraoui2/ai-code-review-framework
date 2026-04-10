"""Data loading utilities for the pilot pipeline.

Reads JSONL fixtures and validates them against the pydantic schemas.
"""

from __future__ import annotations

import json
from pathlib import Path

from pilot.schemas import (
    MatchResult,
    PullRequest,
    ReviewerFinding,
)


def load_pull_requests(path: Path) -> list[PullRequest]:
    """Load PRs with ground truth from a JSONL file.

    Each line is a JSON object conforming to the PullRequest schema.
    """
    prs: list[PullRequest] = []
    with path.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                prs.append(PullRequest.model_validate(data))
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Failed to parse line {line_num} of {path}: {e}") from e
    return prs


def load_mock_reviews(path: Path) -> list[ReviewerFinding]:
    """Load pre-canned reviewer findings from a JSONL file.

    Used in mock mode to avoid API calls.
    """
    findings: list[ReviewerFinding] = []
    with path.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                findings.append(ReviewerFinding.model_validate(data))
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Failed to parse line {line_num} of {path}: {e}") from e
    return findings


def load_mock_judge_matches(path: Path) -> list[MatchResult]:
    """Load pre-canned judge match decisions from a JSONL file.

    Each line specifies whether a ground truth issue was matched by a finding.
    """
    matches: list[MatchResult] = []
    with path.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                matches.append(MatchResult.model_validate(data))
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Failed to parse line {line_num} of {path}: {e}") from e
    return matches
