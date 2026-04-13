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

To run the reference implementation, follow these steps in order:

**1. Install**

```bash
cd pilot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,benchmarks]"
```

**2. Verify with mock mode**

```bash
python -m pilot.run --dataset fixtures/sample.jsonl
python -m pytest tests/ -v
```

This runs entirely offline with no API calls.

**3. Get benchmark data**

See [Getting benchmark data](#getting-benchmark-data) below for per-dataset instructions.

**4. Classify dimensions**

Ground truth issues in public benchmarks are not classified by the framework's 15 dimensions. Run the classification pipeline before benchmarking (see [Dimension classification pipeline](#dimension-classification-pipeline)).

**5. Run a benchmark**

```bash
python -m pilot.run --benchmark ccrab \
    --benchmark-path /path/to/preprocess_dataset.jsonl \
    --reviewer anthropic --judge openai \
    --max-prs 10 --name my-first-run
```

Start with `--max-prs 10` to validate your setup before running the full dataset.

See `pilot/README.md` for instructions on running with real Anthropic and OpenAI adapters.

## Repository structure

```
.
├── README.md
├── LICENSE                                # Apache 2.0
├── framework/
│   └── measurement_framework.md           # The framework specification (5,100+ lines)
├── research/
│   └── literature_review.md               # Literature synthesis (80+ papers)
├── paper/
│   └── part1_paper.md                     # Part 1 research paper
└── pilot/
    ├── README.md                          # Pilot setup and usage
    ├── pyproject.toml                     # Dependencies
    ├── src/pilot/
    │   ├── schemas.py                     # 15-dimension taxonomy, 4-level severity, data models
    │   ├── data.py                        # JSONL loaders
    │   ├── reviewer.py                    # Abstract Reviewer + MockReviewer
    │   ├── judge.py                       # Abstract Judge + MockJudge
    │   ├── api_adapters.py                # AnthropicReviewer, AnthropicJudge, OpenAIJudge
    │   ├── panel.py                       # JudgePanel with majority vote
    │   ├── prompts.py                     # Prompt templates for reviewer and judge
    │   ├── matching.py                    # Semantic matching between findings and GT
    │   ├── metrics.py                     # Precision, recall, F1, Wilson CIs, dimension accuracy
    │   ├── reporting.py                   # JSON + Markdown reports
    │   ├── run.py                         # Benchmark CLI orchestration
    │   ├── autoresearch.py                # AutoResearch iteration loop for prompt optimisation
    │   ├── classify.py                    # Dimension classifier CLI (AutoResearch-powered)
    │   ├── dimension_pipeline.py          # Multi-run consensus classification pipeline
    │   └── datasets/                      # Public benchmark adapters
    │       ├── ccrab.py                   # c-CRAB (410 PRs, Python, test-based GT)
    │       ├── swe_prbench.py             # SWE-PRBench (350 PRs, 5 languages)
    │       ├── swe_care.py                # SWE-CARE (671 instances, 9 domains)
    │       ├── greptile.py                # Greptile (50 PRs, real traced bugs)
    │       └── martian.py                 # Martian (50 PRs, severity labels)
    ├── tests/                             # 78 unit and integration tests
    └── fixtures/                          # 10-PR sample dataset for mock mode
```

## Supported benchmarks

Five public benchmark datasets are supported out of the box:

| Benchmark | PRs | Languages | Ground truth | Unique value | Data readiness |
|---|---|---|---|---|---|
| **c-CRAB** | 410 | Python | Test-based (deterministic) | Ground truth you can't argue with | Clone from GitHub |
| **SWE-PRBench** | 350 | Python, JS, Go, TS, Java | Human review comments | Multi-language, contamination-aware | Auto-downloads from HuggingFace |
| **SWE-CARE** | 671 | Python, Java | Multi-faceted, 9 domains | Category-level analysis | Auto-downloads from HuggingFace |
| **Greptile** | 50 | 5 languages | Real traced bugs | Bugs that actually shipped | Manual — scrape from benchmark page |
| **Martian** | 50 | 5 languages | Golden comments + severity | Pre-labelled severity | Clone repo + fetch diffs via pipeline |

Load any benchmark with `--benchmark`:

```bash
python -m pilot.run --benchmark ccrab \
    --benchmark-path /path/to/preprocess_dataset.jsonl \
    --reviewer anthropic --judge openai \
    --max-prs 10 --name my-run
```

Use `--max-prs` to test with a small subset before running the full dataset. Or load all available benchmarks at once with `--benchmark all`.

## Getting benchmark data

**c-CRAB** — Clone the dataset repository:
```bash
git clone --depth 1 https://github.com/c-CRAB-Benchmark/dataset.git ccrab-dataset
```
Then point `--benchmark-path` at `ccrab-dataset/preprocess_dataset.jsonl`.

**SWE-PRBench** — Auto-downloads from HuggingFace on first run. Just install the benchmark dependencies (`pip install -e ".[dev,benchmarks]"`) and run with `--benchmark swe-prbench`.

**SWE-CARE** — Same as SWE-PRBench: auto-downloads from HuggingFace. Run with `--benchmark swe-care`.

**Greptile** — No downloadable dataset. The benchmark at [greptile.com/benchmarks](https://www.greptile.com/benchmarks) publishes results for 50 PRs across 5 repos (Sentry, Cal.com, Grafana, Keycloak, Discourse), with links to each PR on GitHub. The PR diffs and bug descriptions must be scraped from the benchmark page and the linked GitHub PRs. There is no official GitHub repo with the raw data.

**Martian** — Clone the benchmark repository:
```bash
git clone --depth 1 https://github.com/withmartian/code-review-benchmark.git martian-benchmark
```
The `offline/golden_comments/` directory contains 5 JSON files with human-curated issues and severity labels. However, the PR diffs are **not** included in the repo — they must be fetched from GitHub using the Martian pipeline (`offline/code_review_benchmark/`). This requires a GitHub token and runs a multi-step pipeline: fork PRs, download PR data, extract comments, deduplicate, judge, and export. See their `offline/README.md` for setup.

## Authentication

Three ways to authenticate LLM calls, no configuration files needed:

**Claude Code (no API key needed):**
```bash
# Uses your logged-in Claude Code session via `claude -p`
python -m pilot.run --benchmark ccrab \
    --benchmark-path /path/to/data \
    --reviewer claude-code --judge claude-code
```
Works if you can use Claude Code. No environment variables needed.

**Anthropic API key:**
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
python -m pilot.run --reviewer anthropic --judge anthropic
```

**OpenAI API key:**
```bash
export OPENAI_API_KEY=sk-proj-...
python -m pilot.run --judge openai
```

For cross-family evaluation (the framework recommends judging with a different model family than the reviewer), combine providers:

```bash
python -m pilot.run --reviewer anthropic --judge openai
```

## Dimension classification pipeline

Ground truth issues in public benchmarks are not classified by the framework's 15 dimensions. The classification pipeline uses multi-run LLM consensus to classify them:

```bash
# Classify with Opus × 3 runs (uses Claude Code)
python -m pilot.dimension_pipeline classify \
    --benchmark ccrab \
    --benchmark-path /path/to/data \
    --providers claude-code --models claude-opus-4-6 \
    --runs 3 --output classified/ccrab.jsonl

# Review the auto-generated spot-check sample (50 examples)
# Open spot-check-50.jsonl, fill in human_dimension for each

# Validate AI labels against your spot-check
python -m pilot.dimension_pipeline validate \
    --classified classified/ccrab.jsonl \
    --human-labels spot-check/ccrab-50-labelled.jsonl
```

If kappa ≥ 0.70: classifications are reliable, proceed to the benchmark run.

## Extending or reproducing

- **Apply it to your own tool.** Swap `MockReviewer` for an adapter wrapping your tool's API, point at a benchmark, run.
- **Add a new benchmark.** Write an adapter in `pilot/src/pilot/datasets/` following the c-CRAB pattern, or prepare your data as JSONL matching the schema in `schemas.py`.
- **Run on proprietary code.** The pipeline works on any JSONL dataset with the right schema. Point it at your own PRs with your own review comments as ground truth.
- **Extend the framework.** Revisions belong in `framework/measurement_framework.md` first, then propagate to the pilot code and the paper.

## Licence

Apache 2.0 — see `LICENSE`.
