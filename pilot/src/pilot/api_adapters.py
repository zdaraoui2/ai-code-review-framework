"""Real API adapters for Anthropic and OpenAI.

These implement the Reviewer and Judge interfaces using actual LLM APIs.
The adapters accept a client object as a dependency, which allows tests to
inject mocked clients without touching real APIs.

Wire up:
    from anthropic import Anthropic
    from openai import OpenAI

    reviewer = AnthropicReviewer(client=Anthropic(api_key=...))
    judge = AnthropicJudge(client=Anthropic(api_key=...))
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from pilot.judge import Judge
from pilot.prompts import build_judge_match_prompt, build_reviewer_prompt
from pilot.reviewer import Reviewer
from pilot.schemas import (
    Dimension,
    GroundTruthIssue,
    Location,
    MatchResult,
    PullRequest,
    ReviewerFinding,
    Severity,
)


logger = logging.getLogger(__name__)


# --- Protocols for dependency injection ---------------------------------


class AnthropicClient(Protocol):
    """Minimum interface required from anthropic.Anthropic for the adapters.

    Used to allow test mocks. In production, pass an actual Anthropic instance.
    """

    messages: Any


class OpenAIClient(Protocol):
    """Minimum interface required from openai.OpenAI for the adapters."""

    chat: Any


# --- Cost tracking ------------------------------------------------------


@dataclass
class UsageRecord:
    """Tracks token consumption and call counts for a single adapter."""

    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0
    errors: int = 0

    def record(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.call_count += 1

    def record_error(self) -> None:
        self.errors += 1
        self.call_count += 1


# --- Response parsing ---------------------------------------------------


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from model output.

    Handles cases where the model wraps the JSON in markdown code fences or
    includes leading/trailing whitespace. Raises ValueError on failure.
    """
    text = text.strip()
    if text.startswith("```"):
        # Strip markdown code fences.
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model output is not valid JSON: {e}. Text: {text[:200]}") from e


def parse_reviewer_findings(
    response_text: str,
    pr_id: str,
    reviewer_model: str,
) -> list[ReviewerFinding]:
    """Parse a reviewer API response into ReviewerFinding objects.

    Expected format: {"findings": [{"location": {...}, "dimension": "...", "severity": N, "comment": "..."}, ...]}
    """
    data = _extract_json(response_text)
    if "findings" not in data:
        raise ValueError("Reviewer response missing 'findings' array")
    findings: list[ReviewerFinding] = []
    for i, item in enumerate(data["findings"]):
        try:
            finding = ReviewerFinding(
                finding_id=f"{pr_id}-F{i+1:03d}",
                pr_id=pr_id,
                reviewer_model=reviewer_model,
                location=Location.model_validate(item["location"]),
                dimension=Dimension(item["dimension"]),
                severity=Severity(item["severity"]),
                comment=item["comment"],
            )
            findings.append(finding)
        except (KeyError, ValueError, ValidationError) as e:
            logger.warning(
                "Skipping malformed finding %d for PR %s: %s", i, pr_id, e
            )
            continue
    return findings


def parse_judge_match(
    response_text: str,
    gt_issue_id: str,
) -> MatchResult:
    """Parse a judge API response into a MatchResult.

    Expected format: {"matched_finding_id": "F001" or null, "match_confidence": "high"/"medium"/"low" or null, "justification": "..."}
    """
    data = _extract_json(response_text)
    matched_id = data.get("matched_finding_id")
    confidence = data.get("match_confidence")
    # Normalise "null" string to None.
    if isinstance(matched_id, str) and matched_id.lower() == "null":
        matched_id = None
    return MatchResult(
        ground_truth_issue_id=gt_issue_id,
        finding_id=matched_id,
        match_confidence=confidence if confidence in ("high", "medium", "low") else None,
    )


# --- Anthropic adapters --------------------------------------------------


class AnthropicReviewer(Reviewer):
    """Reviewer using the Anthropic API.

    Pass a configured Anthropic client. The adapter builds prompts, calls
    the API, parses structured JSON output, and records token usage.

    Malformed findings are logged and skipped rather than failing the whole
    review — this matches c-CRAB's approach of treating reviewer quality as
    the thing being measured, not as a precondition.
    """

    def __init__(
        self,
        client: AnthropicClient,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
    ):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self.usage = UsageRecord()

    @property
    def model_name(self) -> str:
        return f"anthropic/{self._model}"

    def review(self, pr: PullRequest) -> list[ReviewerFinding]:
        system, user = build_reviewer_prompt(pr)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            logger.error("Anthropic API call failed for PR %s: %s", pr.pr_id, e)
            self.usage.record_error()
            return []

        # Extract usage
        if hasattr(response, "usage"):
            self.usage.record(
                input_tokens=getattr(response.usage, "input_tokens", 0),
                output_tokens=getattr(response.usage, "output_tokens", 0),
            )
        else:
            self.usage.record(0, 0)

        # Extract content
        content_blocks = getattr(response, "content", [])
        if not content_blocks:
            return []
        text = content_blocks[0].text if hasattr(content_blocks[0], "text") else ""

        try:
            return parse_reviewer_findings(text, pr.pr_id, self.model_name)
        except ValueError as e:
            logger.error("Failed to parse reviewer response for PR %s: %s", pr.pr_id, e)
            return []


class AnthropicJudge(Judge):
    """Judge using the Anthropic API for the issue-match task (S8.3.1)."""

    def __init__(
        self,
        client: AnthropicClient,
        model: str = "claude-opus-4-6",
        max_tokens: int = 1024,
    ):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self.usage = UsageRecord()

    @property
    def model_name(self) -> str:
        return f"anthropic/{self._model}"

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        results: list[MatchResult] = []
        for gt_issue in pr.ground_truth:
            system, user = build_judge_match_prompt(pr, gt_issue, findings)
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=0,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
            except Exception as e:
                logger.error(
                    "Anthropic judge call failed for GT %s: %s", gt_issue.issue_id, e
                )
                self.usage.record_error()
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
                continue

            if hasattr(response, "usage"):
                self.usage.record(
                    input_tokens=getattr(response.usage, "input_tokens", 0),
                    output_tokens=getattr(response.usage, "output_tokens", 0),
                )
            else:
                self.usage.record(0, 0)

            content_blocks = getattr(response, "content", [])
            text = content_blocks[0].text if content_blocks and hasattr(content_blocks[0], "text") else ""
            try:
                results.append(parse_judge_match(text, gt_issue.issue_id))
            except ValueError as e:
                logger.error(
                    "Failed to parse judge response for GT %s: %s", gt_issue.issue_id, e
                )
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
        return results


# --- OpenAI adapters -----------------------------------------------------


class OpenAIJudge(Judge):
    """Judge using the OpenAI API. Used for multi-family judge panels.

    Note: only the judge is implemented for OpenAI in the pilot. A
    corresponding reviewer adapter could be added when needed for cross-
    family reviewer comparisons.
    """

    def __init__(
        self,
        client: OpenAIClient,
        model: str = "gpt-4o",
        max_tokens: int = 1024,
    ):
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self.usage = UsageRecord()

    @property
    def model_name(self) -> str:
        return f"openai/{self._model}"

    def match_findings_to_ground_truth(
        self,
        pr: PullRequest,
        findings: list[ReviewerFinding],
    ) -> list[MatchResult]:
        results: list[MatchResult] = []
        for gt_issue in pr.ground_truth:
            system, user = build_judge_match_prompt(pr, gt_issue, findings)
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                logger.error(
                    "OpenAI judge call failed for GT %s: %s", gt_issue.issue_id, e
                )
                self.usage.record_error()
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
                continue

            if hasattr(response, "usage") and response.usage is not None:
                self.usage.record(
                    input_tokens=getattr(response.usage, "prompt_tokens", 0),
                    output_tokens=getattr(response.usage, "completion_tokens", 0),
                )
            else:
                self.usage.record(0, 0)

            choices = getattr(response, "choices", [])
            if not choices:
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
                continue
            text = choices[0].message.content or ""
            try:
                results.append(parse_judge_match(text, gt_issue.issue_id))
            except ValueError as e:
                logger.error(
                    "Failed to parse OpenAI judge response for GT %s: %s",
                    gt_issue.issue_id,
                    e,
                )
                results.append(
                    MatchResult(ground_truth_issue_id=gt_issue.issue_id, finding_id=None)
                )
        return results
