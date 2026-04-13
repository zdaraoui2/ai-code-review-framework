"""Judge adapter.

Implements the LLM-as-judge protocol from Section 8 of the framework.
Mock implementation reads from fixtures; real implementation is stubbed.

The pilot implements the issue-match task (determining whether an AI
finding corresponds to a ground truth issue). Validity, severity, and
quality assessment tasks are defined but stubbed — they are needed for
the full false positive adjudication protocol, which is future work.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pilot.data import load_mock_judge_matches
from pilot.schemas import (
    GroundTruthIssue,
    MatchResult,
    PullRequest,
    ReviewerFinding,
)


class Judge(ABC):
    """Abstract base class for judge adapters.

    A judge panel (Section 8.1) consists of multiple judges from different
    model families. This interface represents a single judge; the orchestrator
    aggregates results from the panel.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier for the judge model."""

    @property
    @abstractmethod
    def family(self) -> str:
        """Model family identifier (e.g., 'anthropic', 'openai').

        Used by JudgePanel to enforce the family exclusion rule from
        Section 8.1.1: all judges on a panel must come from different
        model families.
        """

    @abstractmethod
    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        """For each ground truth issue, decide which finding (if any) matches it.

        Implements Task 1 from Section 8.3.1 (Issue Detection Match).
        """


class MockJudge(Judge):
    """Judge that returns pre-canned match decisions from a fixture file.

    The mock bypasses the actual semantic matching task and returns the
    canonical mapping between ground truth issues and findings.
    """

    def __init__(
        self,
        fixture_path: Path,
        model_name: str = "mock-judge",
        family: str = "mock",
    ):
        self._model_name = model_name
        self._family = family
        self._matches_by_gt: dict[str, MatchResult] = {}
        for match in load_mock_judge_matches(fixture_path):
            self._matches_by_gt[match.ground_truth_issue_id] = match

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def family(self) -> str:
        return self._family

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        """Return the pre-canned match decision for each ground truth issue.

        Findings not matched to any GT issue are handled separately by the
        orchestrator (they become potential false positives).
        """
        results: list[MatchResult] = []
        for gt_issue in pr.ground_truth:
            if gt_issue.issue_id in self._matches_by_gt:
                results.append(self._matches_by_gt[gt_issue.issue_id])
            else:
                # No fixture entry — treat as a miss.
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
        return results


class AnthropicJudge(Judge):
    """Judge using the Anthropic API.

    Not implemented in the pilot — API key wiring is the user's responsibility.
    Implements the prompt templates from Section 8.5 of the framework.
    """

    def __init__(self, model: str = "claude-opus-4-6", api_key: str | None = None):
        self._model = model
        self._api_key = api_key

    @property
    def model_name(self) -> str:
        return f"anthropic/{self._model}"

    @property
    def family(self) -> str:
        return "anthropic"

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        # TODO: Build prompt from Section 8.5.1 template, call API,
        # parse structured JSON output per Section 8.7.1 schema.
        raise NotImplementedError(
            "AnthropicJudge is a stub. Wire up the API call and structured output parsing."
        )
