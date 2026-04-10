"""Tests for real API adapters using mocked clients."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pilot.api_adapters import (
    AnthropicJudge,
    AnthropicReviewer,
    OpenAIJudge,
    _extract_json,
    parse_judge_match,
    parse_reviewer_findings,
)
from pilot.schemas import (
    ChangeType,
    Dimension,
    GroundTruthIssue,
    Location,
    PullRequest,
    Severity,
)


# --- Helpers ------------------------------------------------------------


def _sample_pr(pr_id: str = "PR1") -> PullRequest:
    return PullRequest(
        pr_id=pr_id,
        title="Test PR",
        language="python",
        change_type=ChangeType.NEW_FEATURE,
        diff="+print('hi')",
        ground_truth=[
            GroundTruthIssue(
                issue_id=f"{pr_id}-GT1",
                pr_id=pr_id,
                dimension=Dimension.SECURITY,
                severity=Severity.HIGH,
                location=Location(file_path="a.py", start_line=1, end_line=1),
                description="A test issue.",
            )
        ],
    )


class _MockAnthropicResponse:
    def __init__(self, text: str, input_tokens: int = 100, output_tokens: int = 50):
        self.content = [SimpleNamespace(text=text)]
        self.usage = SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        )


class _MockAnthropicClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.messages = self
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("No more mock responses")
        return _MockAnthropicResponse(self._responses.pop(0))


class _MockOpenAIResponse:
    def __init__(
        self,
        content: str,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ):
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        self.choices = [choice]
        self.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )


class _MockOpenAICompletions:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("No more mock responses")
        return _MockOpenAIResponse(self._responses.pop(0))


class _MockOpenAIClient:
    def __init__(self, responses: list[str]):
        completions = _MockOpenAICompletions(responses)
        self.chat = SimpleNamespace(completions=completions)
        self._completions = completions

    @property
    def calls(self):
        return self._completions.calls


# --- JSON extraction tests ----------------------------------------------


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_code_fence():
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_with_unmarked_fence():
    text = '```\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_with_whitespace():
    text = '   \n  {"a": 1}  \n  '
    assert _extract_json(text) == {"a": 1}


def test_extract_json_invalid_raises():
    with pytest.raises(ValueError):
        _extract_json("not json")


# --- Reviewer response parsing tests ------------------------------------


def test_parse_reviewer_findings_success():
    response = """{
      "findings": [
        {
          "location": {"file_path": "api.py", "start_line": 10, "end_line": 12},
          "dimension": "security",
          "severity": 4,
          "comment": "SQL injection risk."
        }
      ]
    }"""
    findings = parse_reviewer_findings(response, "PR1", "test-model")
    assert len(findings) == 1
    assert findings[0].dimension == Dimension.SECURITY
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].pr_id == "PR1"


def test_parse_reviewer_findings_skips_malformed():
    response = """{
      "findings": [
        {"location": {"file_path": "a.py", "start_line": 1, "end_line": 1}, "dimension": "security", "severity": 4, "comment": "Good finding."},
        {"dimension": "not_a_real_dim", "severity": 4, "comment": "Bad."}
      ]
    }"""
    findings = parse_reviewer_findings(response, "PR1", "test-model")
    assert len(findings) == 1


def test_parse_reviewer_findings_missing_findings_key():
    with pytest.raises(ValueError):
        parse_reviewer_findings('{"other": []}', "PR1", "test-model")


# --- Judge response parsing tests ---------------------------------------


def test_parse_judge_match_positive():
    response = '{"matched_finding_id": "F1", "match_confidence": "high", "justification": "Matches exactly."}'
    result = parse_judge_match(response, "GT1")
    assert result.ground_truth_issue_id == "GT1"
    assert result.finding_id == "F1"
    assert result.match_confidence == "high"


def test_parse_judge_match_no_match():
    response = '{"matched_finding_id": null, "match_confidence": null, "justification": "No match."}'
    result = parse_judge_match(response, "GT1")
    assert result.finding_id is None
    assert result.match_confidence is None


def test_parse_judge_match_invalid_confidence_becomes_none():
    response = '{"matched_finding_id": "F1", "match_confidence": "super-high"}'
    result = parse_judge_match(response, "GT1")
    assert result.finding_id == "F1"
    assert result.match_confidence is None  # Invalid confidence normalised


# --- Anthropic reviewer tests ------------------------------------------


def test_anthropic_reviewer_happy_path():
    response_text = """{
      "findings": [
        {
          "location": {"file_path": "a.py", "start_line": 1, "end_line": 1},
          "dimension": "security",
          "severity": 4,
          "comment": "Test."
        }
      ]
    }"""
    client = _MockAnthropicClient([response_text])
    reviewer = AnthropicReviewer(client=client, model="claude-test")
    pr = _sample_pr()

    findings = reviewer.review(pr)
    assert len(findings) == 1
    assert findings[0].dimension == Dimension.SECURITY
    assert reviewer.usage.call_count == 1
    assert reviewer.usage.input_tokens == 100
    assert reviewer.usage.output_tokens == 50


def test_anthropic_reviewer_handles_api_error():
    class _FailingClient:
        class _FailingMessages:
            def create(self, **kwargs):
                raise RuntimeError("API down")

        messages = _FailingMessages()

    reviewer = AnthropicReviewer(client=_FailingClient())
    pr = _sample_pr()
    findings = reviewer.review(pr)
    assert findings == []
    assert reviewer.usage.errors == 1


def test_anthropic_reviewer_handles_malformed_response():
    client = _MockAnthropicClient(["not valid json"])
    reviewer = AnthropicReviewer(client=client)
    pr = _sample_pr()
    findings = reviewer.review(pr)
    assert findings == []


# --- Anthropic judge tests ---------------------------------------------


def test_anthropic_judge_happy_path():
    response_text = (
        '{"matched_finding_id": "F001", "match_confidence": "high",'
        ' "justification": "Matches."}'
    )
    client = _MockAnthropicClient([response_text])
    judge = AnthropicJudge(client=client)
    pr = _sample_pr()
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 1
    assert results[0].finding_id == "F001"
    assert judge.usage.call_count == 1


def test_anthropic_judge_multiple_gt_issues():
    pr = PullRequest(
        pr_id="PR1",
        title="Test",
        language="python",
        change_type=ChangeType.NEW_FEATURE,
        diff="+x",
        ground_truth=[
            GroundTruthIssue(
                issue_id="GT1",
                pr_id="PR1",
                dimension=Dimension.SECURITY,
                severity=Severity.HIGH,
                location=Location(file_path="a.py", start_line=1, end_line=1),
                description="First issue",
            ),
            GroundTruthIssue(
                issue_id="GT2",
                pr_id="PR1",
                dimension=Dimension.CORRECTNESS,
                severity=Severity.MEDIUM,
                location=Location(file_path="a.py", start_line=2, end_line=2),
                description="Second issue",
            ),
        ],
    )
    client = _MockAnthropicClient(
        [
            '{"matched_finding_id": "F1", "match_confidence": "high"}',
            '{"matched_finding_id": null, "match_confidence": null}',
        ]
    )
    judge = AnthropicJudge(client=client)
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 2
    assert results[0].finding_id == "F1"
    assert results[1].finding_id is None
    assert judge.usage.call_count == 2


# --- OpenAI judge tests ------------------------------------------------


def test_openai_judge_happy_path():
    response_text = '{"matched_finding_id": "F1", "match_confidence": "high"}'
    client = _MockOpenAIClient([response_text])
    judge = OpenAIJudge(client=client)
    pr = _sample_pr()
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 1
    assert results[0].finding_id == "F1"
    assert judge.usage.call_count == 1
    assert judge.usage.input_tokens == 100
    assert judge.usage.output_tokens == 50


def test_openai_judge_handles_error():
    class _FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("API down")

    class _FailingClient:
        chat = SimpleNamespace(completions=_FailingCompletions())

    judge = OpenAIJudge(client=_FailingClient())
    pr = _sample_pr()
    results = judge.match_findings_to_ground_truth(pr, [])
    assert len(results) == 1
    assert results[0].finding_id is None  # Treated as no-match on error
    assert judge.usage.errors == 1
