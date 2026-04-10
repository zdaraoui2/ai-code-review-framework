# Measuring AI Code Review Quality

A measurement framework, a reference implementation, and a research paper for evaluating the quality of AI-generated code review.

## The problem

AI code review tools are proliferating — CodeRabbit, Qodo, Augment Code, BitsAI-CR, Greptile, and many others now reach millions of repositories. But the field has no standardised way to evaluate them. Existing benchmarks use mutually incompatible methodologies: test-based (c-CRAB), LLM-as-judge (SWR-Bench, SWE-PRBench), developer-action proxies (CodeAnt), and reference-free quality metrics (CRScore). Cross-tool comparison is unreliable because the ruler changes between measurements.

Compounding this, the dominant category of review activity is not the category that matters for production reliability. Across four independent studies, roughly 75% of review comments concern code evolvability — readability, naming, structure — not functional defects. Yet the functional defects (logic errors, concurrency bugs, security vulnerabilities) are what cause production incidents. Any evaluation that reports aggregate metrics hides this *review quality paradox* behind a single number.

## The contribution

This repository contains a comprehensive measurement framework addressing these gaps, structured as four artefacts.

| Artefact | Location | What it is |
|---|---|---|
| **Measurement framework specification** | `framework/measurement_framework.md` | A complete, prescriptive framework covering the 15-dimension review taxonomy, the 6-category change-type taxonomy with priority matrix, per-dimension metrics with confidence intervals, a judge protocol with bias mitigations, a false positive adjudication protocol, a sycophancy testing protocol, a multi-model experiment protocol, and a statistical protocol. |
| **Literature review** | `research/literature_review.md` | A synthesis of over 80 academic and industry sources on code review measurement, with verification-status tags on every claim that drives a conclusion. |
| **Reference implementation** | `pilot/` | An end-to-end Python implementation of the framework, with mock and real (Anthropic, OpenAI) adapters, a multi-judge panel, and a full test suite. Demonstrates that the framework is an executable specification rather than a research manifesto. |
| **Part 1 research paper** | `paper/part1_paper.md` | *Measuring AI Code Review Quality: A Framework and Initial Validation.* The methodology paper that motivates and presents the framework. |

## Novel contributions

The framework introduces three contributions not present in any published code-review benchmark:

**False positive adjudication.** Most existing benchmarks treat any AI finding not in the ground truth as a false positive. This is wrong: the finding could be a hallucination, an ambiguous judgement call, or a genuine issue the original reviewers missed. The framework specifies a three-category adjudication protocol — Confirmed False Positive, Plausible Finding, Confirmed Novel Finding — with a feedback loop that adds genuine novel findings back into the ground truth. This separates hallucination from thoroughness.

**Sycophancy testing for code review.** Sycophancy is well-documented in general LLM settings but has never been operationalised for code review. The framework specifies three sub-protocols — LGTM bias testing, critique sycophancy testing, and severity softening — with difficulty calibration by a ten-panellist human panel. The panel size is not arbitrary: with fewer reviewers, the achievable catch rates cannot distinguish the 90% Easy-difficulty boundary from 100%, which is where the LGTM bias measurement lives.

**Multi-model experiment protocol with semantic deduplication.** Evidence from adjacent domains suggests multi-model ensembles should improve code review quality (c-CRAB's union recall is 41.5% versus 32.1% for the best single tool; SWR-Bench shows multi-review aggregation improves F1 by up to 43.67%). The framework specifies a controlled comparison across nine experimental conditions with five aggregation strategies, and introduces a two-stage semantic deduplication method for combining natural-language review comments across models — a problem no published paper has solved.

## Quick start

Read the Part 1 paper first (`paper/part1_paper.md`) for the motivation and high-level framework. Then read the framework specification (`framework/measurement_framework.md`) for implementation-level detail.

To run the reference implementation:

```bash
cd pilot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pilot.run --dataset fixtures/sample.jsonl
python -m pytest tests/ -v
```

The pilot runs in mock mode by default, with no API costs. See `pilot/README.md` for instructions on running with real Anthropic and OpenAI adapters.

## Repository structure

```
.
├── README.md                          # This file
├── LICENSE                            # Apache 2.0
├── framework/
│   └── measurement_framework.md       # The framework specification
├── research/
│   └── literature_review.md           # Literature synthesis
├── paper/
│   └── part1_paper.md                 # Part 1: Measuring AI Code Review Quality
└── pilot/
    ├── README.md                      # Pilot setup and usage
    ├── pyproject.toml                 # Dependencies
    ├── src/pilot/                     # Source code
    │   ├── schemas.py                 # Pydantic models
    │   ├── data.py                    # JSONL loaders
    │   ├── reviewer.py                # Abstract Reviewer + MockReviewer
    │   ├── judge.py                   # Abstract Judge + MockJudge
    │   ├── api_adapters.py            # AnthropicReviewer, AnthropicJudge, OpenAIJudge
    │   ├── panel.py                   # JudgePanel with majority vote
    │   ├── prompts.py                 # Prompt templates
    │   ├── matching.py                # Semantic matching
    │   ├── metrics.py                 # Precision, recall, F1, Wilson CIs
    │   ├── reporting.py               # JSON + Markdown reports
    │   └── run.py                     # CLI orchestration
    ├── tests/                         # Unit and integration tests
    └── fixtures/                      # 10-PR sample dataset
```

## Extending or reproducing

If you want to use this framework:

- **Apply it to your own tool.** Fork the pilot, swap `MockReviewer` for an adapter that wraps your tool's API, and run the pipeline on a benchmark that matters to you.
- **Build a new benchmark.** The pilot's data loader expects a JSONL format with the schema defined in `pilot/src/pilot/schemas.py`. Adapt existing benchmarks (c-CRAB, SWE-PRBench) to this format, or curate your own.
- **Extend the framework.** Revisions belong in `framework/measurement_framework.md` first, then propagate to the pilot code and the paper.

## Licence

Apache 2.0 — see `LICENSE`.
