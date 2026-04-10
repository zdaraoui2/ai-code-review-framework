"""Reviewer adapter.

Abstract interface for calling an AI code review tool. Mock implementation
reads from fixtures; real implementation is stubbed out with TODO markers
for the user to wire up API keys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pilot.data import load_mock_reviews
from pilot.schemas import PullRequest, ReviewerFinding


class Reviewer(ABC):
    """Abstract base class for reviewer adapters.

    A reviewer takes a PR diff and returns a list of findings.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier for the underlying model (e.g., 'claude-sonnet-4-6')."""

    @abstractmethod
    def review(self, pr: PullRequest) -> list[ReviewerFinding]:
        """Generate review findings for a single PR."""


class MockReviewer(Reviewer):
    """Reviewer that returns pre-canned findings from a fixture file.

    Used for pilot testing without API costs.
    """

    def __init__(self, fixture_path: Path):
        self._findings_by_pr: dict[str, list[ReviewerFinding]] = {}
        for finding in load_mock_reviews(fixture_path):
            self._findings_by_pr.setdefault(finding.pr_id, []).append(finding)

    @property
    def model_name(self) -> str:
        return "mock-reviewer"

    def review(self, pr: PullRequest) -> list[ReviewerFinding]:
        return self._findings_by_pr.get(pr.pr_id, [])


class AnthropicReviewer(Reviewer):
    """Reviewer using the Anthropic API.

    Not implemented in the pilot — API key wiring is the user's responsibility.
    Left as a stub so the interface shape is clear.
    """

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        self._model = model
        self._api_key = api_key
        # TODO: initialise anthropic.Anthropic client
        # from anthropic import Anthropic
        # self._client = Anthropic(api_key=api_key)

    @property
    def model_name(self) -> str:
        return f"anthropic/{self._model}"

    def review(self, pr: PullRequest) -> list[ReviewerFinding]:
        # TODO: Build prompt, call self._client.messages.create(...), parse structured output.
        # The reviewer prompt should ask for findings in the ReviewerFinding schema.
        raise NotImplementedError(
            "AnthropicReviewer is a stub. Wire up the API call and structured output parsing."
        )
