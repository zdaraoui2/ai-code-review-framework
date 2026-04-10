# Literature Review: Measuring AI Code Review Quality

A synthesis of the academic and industry literature on code review measurement, serving as source material for the measurement framework developed in this repository.

### Confidence tagging

Key claims are tagged with verification status. Tags appear on claims that drive conclusions or where the source warrants scrutiny. Not every sentence is tagged — untagged claims in context of tagged sources inherit that source's confidence level.

- ✓ Verified against primary source (paper accessed and claim confirmed)
- ~ Partially verified (directionally correct; specific number from secondary source, industry report, or vendor benchmark — treat with appropriate caution)
- ? Unverified (could not access primary source; claim from search summaries only)

Industry reports (DORA, Stack Overflow, Sonar, GitClear, SmartBear, Qodo) are inherently ~ unless independently replicated. Vendor-reported benchmarks (tool accuracy claims from the tool's own vendor) are tagged ~ regardless of plausibility. Two papers (Paul et al. 2021, Bavota et al. 2012) could not be accessed in full and all claims sourced exclusively from them are tagged ?.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Should Code Review Catch?](#2-what-should-code-review-catch)
3. [Human Reviewer Baseline](#3-human-reviewer-baseline)
4. [AI Code Review Performance](#4-ai-code-review-performance)
5. [Evaluation Methodology](#5-evaluation-methodology)
6. [Available Datasets and Benchmarks](#6-available-datasets-and-benchmarks)
7. [Cross-Thread Synthesis](#7-cross-thread-synthesis)
8. [Gaps and Open Questions](#8-gaps-and-open-questions)
9. [Complete Bibliography](#9-complete-bibliography)

---

## 1. Executive Summary

### What we investigated

This review surveys the academic and industry literature on code review measurement, with a focus on three questions: (1) what should code review catch and how well do humans do it, (2) where do AI code review tools succeed and fail, and (3) how should we rigorously measure the difference.

### Key findings

**Code review is not primarily about finding bugs.** Across four independent studies spanning Microsoft, open-source projects, and academia, 75% of review findings concern code evolvability (readability, naming, structure), not functional defects (✓ Mantyla & Lassenius 2009; ✓ Beller et al. 2014). Defect comments constitute only 14% of review comments at Microsoft (✓ Bacchelli & Bird 2013). Yet the functional defects that escape review -- logic errors, concurrency bugs, security vulnerabilities, error handling gaps -- are what cause production incidents.

**AI code review tools are not yet reliable.** The best single-pass LLM achieves F1 of only 19.38% on rigorous benchmarks (~ SWR-Bench 2025, best single-pass result). Multi-review aggregation improves this to 21.91% (✓ SWR-Bench). Even the union of four leading tools covers only 41.5% of human-identified issues (✓ c-CRAB 2026). CRA-only pull requests have a 45.20% merge rate versus 68.37% for human-reviewed PRs -- a 23 percentage-point gap (✓ Chowdhury et al., MSR 2026).

**No standardised benchmark exists.** A 2026 survey of 99 papers explicitly identifies the absence of a "systematic SDLC-aware benchmark landscape for review tasks" (✓ Khan et al., arXiv:2602.13377). Existing benchmarks use incompatible methodologies (test-based, LLM-as-judge, reference-based, developer-action proxies), making cross-tool comparison unreliable.

**Evaluation methodology has matured but is underused.** CRScore provides reference-free evaluation with 0.54 Spearman correlation to human judgement (✓ Naik et al., NAACL 2025). Test-based evaluation (c-CRAB) offers deterministic assessment for testable issues. Yet rigorous statistical practice remains rare — 83% of single-run leaderboard results produce rank inversions compared to three-run aggregates (✓ arXiv:2509.24086), and the Khan et al. survey (✓ arXiv:2602.13377) notes a decline in statistical validation practices in the LLM era.

### Novel contribution opportunities

Three areas where a new benchmark would fill significant literature gaps:

1. **Category-level human baseline data.** No published study measures human reviewer recall by defect category (beyond security) or by change type. A benchmark producing this data alongside AI measurements would be the first of its kind.

2. **Multi-model ensemble evaluation for code review.** Multi-model ensembles improve code generation accuracy by 6--18pp (✓ EnsLLM, MPLE), and union of review tools covers 29% more issues than the best single tool (✓ c-CRAB). No study has systematically compared multi-model versus single-model review under controlled cost constraints.

3. **Sycophancy measurement in code review.** Sycophancy is well-documented in general LLM settings (✓ Perez et al.; ✓ Sharma et al.) but unmeasured in code review. The LGTM bias rate (fraction of known-bad code an AI approves) is a straightforward metric nobody has published.

---

## 2. What Should Code Review Catch?

### 2.1 Ranked review dimensions with evidence

Review dimensions are ranked below by production-incident correlation, drawing on the composite evidence base. The ranking weighs empirical incident data, defect severity, and catch-rate difficulty.

#### Tier 1: High production-incident correlation

| # | Dimension | Evidence | Production Impact |
|---|-----------|----------|-------------------|
| 1 | **Correctness / Logic errors** | Only ~25% of review findings are functional defects (✓ Mantyla & Lassenius 2009; ✓ Beller et al. 2014), but these cause incidents. Defect comments are 14% of all review comments at Microsoft (✓ Bacchelli & Bird 2013). | Direct. Logic errors escaping review and testing are the primary code-originated incident cause. |
| 2 | **Concurrency / Threading** | Chromium OS: concurrency-related security defects among the most likely to escape review (? Paul et al. 2021). Escape likelihood increases with change scope. | High severity. Race conditions and deadlocks produce intermittent, hard-to-diagnose production failures. |
| 3 | **Error handling / Failure modes** | Azure AutoARTS: most frequent contributing factor pair is "Code.Bug.Change" + "Detection.Monitoring.MissingAlert" at 15% of all combinations (? Dogga et al. 2023). Poor error handling masks failures. | High severity. Missing error handling turns recoverable errors into cascading failures. |
| 4 | **Security vulnerabilities** | Chromium OS: 516 reviews caught vs 374 where vulnerabilities escaped (? Paul et al. 2021). Asking reviewers to focus on security increases detection 8x (? Di Biase et al.). | High severity when missed. Security issues have outsized blast radius. |
| 5 | **Resource management** | Resource management is a functional defect subcategory in the Mantyla & Lassenius taxonomy. Memory errors and resource management are discussed less often in review than the vulnerabilities they produce. | Memory leaks, file descriptor exhaustion, and connection pool depletion cause production degradation over time. |

#### Tier 2: Moderate production-incident correlation, high long-term impact

| # | Dimension | Evidence | Production Impact |
|---|-----------|----------|-------------------|
| 6 | **Configuration correctness** | ThousandEyes 2024: CSP outage proportion grew from 11% (2022) to 27% (2024). CrowdStrike July 2024, Azure Front Door Jan 2025, Google Cloud June 2025, Facebook Oct 2021 -- all configuration-originated. ~ 83% of organisations faced a cloud security incident in 2024, with 23% stemming from IaC misconfigurations (industry report). | Very high. Config changes are an increasingly dominant incident cause, yet often reviewed outside code review processes. |
| 7 | **API design / Contracts** | Strong correlation between API-level refactorings and bug fixes (Kim et al. 2014). 16% of breaking dependency updates are indirect compilation failures from API changes. | Moderate-high. API contract violations cause integration failures across service boundaries. |
| 8 | **Test coverage / Quality** | Improving test quality is a key review motivation at Google (✓ Sadowski et al. 2018). Low review coverage produces up to 2 additional post-release defects per component, though this was statistically significant in only 2 of 4 studied releases [corrected from original source] (✓ McIntosh et al. 2014). | Indirect but significant. Inadequate tests allow defects to reach production. |
| 9 | **Architecture / Design** | Managers expect reviews to catch "errors in design," but design-level issues are rarely addressed in review comments (✓ Bacchelli & Bird 2013). Review has shifted from defect-finding to "group problem solving" (✓ Rigby & Bird 2013). | High long-term impact. Architectural issues are expensive to fix post-release but rarely caught in line-by-line review. |
| 10 | **Data validation / Input handling** | Input validation is a functional defect subcategory (✓ Mantyla & Lassenius 2009). Identified as a characteristic of vulnerable code changes (Bosu et al. 2014). | Moderate-high. Input validation failures are a common attack vector and cause data corruption. |

#### Tier 3: Important for code health, lower direct incident correlation

| # | Dimension | Evidence |
|---|-----------|----------|
| 11 | **Maintainability / Structure** | 75% of review findings across all studies (✓). Code improvements is the #1 comment category at 29% (✓ Bacchelli & Bird 2013). |
| 12 | **Readability / Naming** | Primary motivation for code review at Google is ensuring readability and maintainability (✓ Sadowski et al. 2018). Google has a formal "readability certification" process. |
| 13 | **Documentation** | Documentation changes constitute 48.33% of evolvability fixes (✓ Beller et al. 2014). |
| 14 | **Style / Formatting** | Recommendation: automate style enforcement to free reviewers for deeper issues (✓ Bacchelli & Bird 2013). Negligible direct incident impact. |
| 15 | **Performance** | Not well studied in review literature. Algorithmic complexity issues are catchable in review; load-dependent issues are not. |

### 2.2 How requirements vary by change type

Evidence supports risk-proportional review allocation, not uniform effort.

| Change Type | Risk Level | Key Evidence | Review Focus |
|-------------|-----------|--------------|--------------|
| **Configuration changes** | Very High | 27% of CSP outages (2024). Often reviewed outside formal processes. IaC scanner detection rates: Checkov 74--84%, tfsec 79--89%, KICS 88--100% -- but these cover known patterns, not novel errors. | Baseline comparison, impact analysis, rollback capability, staged deployment. |
| **Refactoring (architectural)** | High | Classes involved in refactoring are 3.5--6.6x more likely to undergo bug-fix changes (? Bavota et al. 2012). 76% of Microsoft developers report concern about regression risk. | Behaviour preservation, test coverage adequacy, isolation from concurrent feature changes. |
| **Dependency updates** | High | Log4Shell: CVSS 10.0. OSCAR monitoring revealed 11,639 malicious packages across npm and PyPI (ASE 2024). 54% of Dependabot updates are deleted without action (arXiv:2206.07230). | Security audit for known CVEs, breaking change compatibility, transitive dependency analysis, lock file verification. |
| **New features** | Moderate | Feature patches are associated with slow initial feedback (✓ Thongtanunam et al. 2017). | Correctness, edge cases, integration with existing systems, test coverage. |
| **Bug fixes** | Moderate | Bug-fixing tasks lead to fewer review changes (✓ Beller et al. 2014). "Fix-inducing" changes are well-studied -- fixes can introduce new bugs. | Regression risk, root cause correctness, test for the specific bug. |

**Large changes are universally worse.** Detection effectiveness drops from 70--90% for 200--400 LOC reviews to being 5x less effective for reviews over 200 lines [corrected from original source: SmartBear actually states "70--90% defect discovery for 200--400 LOC reviews" and "5x more effective under 200 lines," not the phantom 87%/28% figures]. Likelihood of missing security defects increases with directories/files involved (? Paul et al. 2021).

### 2.3 Composite taxonomy for benchmarking

Synthesising across Mantyla & Lassenius (2009), Bacchelli & Bird (2013), Beller et al. (2014), and Sadowski et al. (2018), a complete taxonomy for evaluating AI code reviewers includes:

```
1. Correctness (logic, boundary, null/nil, return value, type errors)
2. Security (input validation, auth, cryptographic misuse, info disclosure, memory safety)
3. Concurrency (race conditions, deadlocks, atomicity violations)
4. Error Handling (missing checks, swallowed errors, incorrect propagation, missing cleanup)
5. Resource Management (memory leaks, handle leaks, unbounded growth)
6. API Design / Contracts (breaking changes, inconsistent interfaces, missing boundary validation)
7. Performance (algorithmic complexity, unnecessary allocations, N+1 queries)
8. Test Quality (missing coverage, weak assertions, tests that always pass)
9. Configuration (incorrect values, missing validation, environment assumptions, rollback capability)
10. Maintainability (duplication, dead code, complex logic, poor naming, misleading comments)
11. Architecture / Design (SoC violations, dependency direction, abstraction mismatches)
12. Documentation (missing/outdated API docs, misleading comments, missing changelog)
13. Style / Formatting (convention violations -- should be automated, not human-reviewed)
```

---

## 3. Human Reviewer Baseline

### 3.1 Published recall and precision data

| Context | Detection Rate | Source | Confidence |
|---------|---------------|--------|------------|
| Formal inspections (Fagan-style) | 60--90% | Multiple sources; Boehm & Turner 2003 | ✓ |
| PSP code reviews at <=200 LOC/hr | ~50% (code), ~65% (design) | Kemerer & Paulk, TSE 2009 | ✓ |
| PSP code reviews (all rates) | 62% of code-phase defects | Vallespir & Nichols 2012 | ~ |
| Modern lightweight review (Microsoft) | Only ~15% of review comments indicate a possible defect | Czerwonka et al. 2015 | ✓ |
| Optimal (inspections + static analysis + testing) | >95%, can reach 99% | Capers Jones | ~ |

**The 15% figure requires careful interpretation.** It reflects the proportion of comments, not the proportion of defects found versus missed. Modern code review's primary output is not defect finding -- it is knowledge transfer, readability enforcement, and maintainability improvement.

**Detection rate by PR size:**

| PR Size (LOC) | Detection Rate | Review Time | Source |
|---------------|---------------|-------------|--------|
| 1--100 | ~87% | ~45 min | ~ PropelCode 2024 (industry analysis, consistent with peer-reviewed findings) |
| 101--300 | ~78% | ~70 min | ~ PropelCode 2024 |
| 301--600 | ~65% | -- | ~ PropelCode 2024 |
| 601--1,000 | ~42% | -- | ~ PropelCode 2024 |
| 1,000+ | ~28% | ~4.2 hrs | ~ PropelCode 2024 |

SmartBear's verified claim: reviews of 200--400 LOC achieve 70--90% defect discovery, and reviews under 200 lines are 5x more effective [corrected from original source]. The commonly cited 87%/<28% figures do not appear in SmartBear's published materials and should be treated as unverified interpolations.

**False positive rates** are poorly measured. Siy & Votta (2001) found 22% of inspection findings were false positives. Bosu et al. (MSR 2015) found only 33% of first-exposure comments were deemed useful by the code author, rising to ~67% by the third review of the same area. This conflates false positives with low-priority suggestions.

### 3.2 The 75:25 evolvability-to-functional ratio

This is one of the most replicated findings in code review research:

- **Siy & Votta (2001):** First proposed. Found 60% evolvability, 18% functional, 22% false positives.
- **Mantyla & Lassenius (TSE 2009):** Classified 759 defects. 75% do not affect visible functionality (✓). They improve understandability and modifiability.
- **Beller et al. (MSR 2014):** Classified over 1,400 changes. Confirmed the 75:25 ratio -- "strikingly similar" to industry and academic data (✓). Specific values: ConQAT-rand 81:19, ConQAT-100 75:25, GROMACS 69:31 -- all within a 10pp range.
- **Czerwonka et al. (ICSE-SEIP 2015):** At Microsoft, ~50% of all review comments address long-term maintainability. Only ~15% indicate a possible defect.

The ratio holds across industrial (Microsoft), open-source (ConQAT, GROMACS), and academic contexts.

**Implication for benchmarking:** Any AI code review tool will be benchmarked against a human baseline primarily focused on evolvability, not defect detection. Category-level scoring must account for this.

### 3.3 Time and cost data

**Review time:**

| Organisation | Metric | Value | Confidence |
|-------------|--------|-------|------------|
| Google | Mean time per week reviewing | 3.2 hrs (median 2.6 hrs) [corrected: 3.2 is the mean, not the median] | ✓ Sadowski et al. 2018 |
| Google | Median latency, full review process | <4 hours | ✓ |
| Google | Median change size | 24 lines modified | ✓ |
| Microsoft | Median time to approval | 24 hours | ✓ Czerwonka et al. 2015 |
| AMD | Median time to approval | 17.5 hours | ✓ Rigby & Bird 2013 |
| All (Cisco study) | Optimal session length | <60 min, must not exceed 90 min | ✓ |

Google's data spans January 2014 to July 2016 (approximately 2.5 years, covering ~9 million reviewed changes) [corrected from original source]. Developer satisfaction with the Critique review tool is 97% (from internal tool satisfaction surveys, not from the paper's primary 44-respondent survey) [corrected from original source].

**Optimal review rate:** 200 LOC/hour or slower (✓ Kemerer & Paulk 2009). SmartBear recommends 200--400 LOC per review session (not per hour -- a commonly conflated metric) [corrected from original source], with an inspection rate ceiling of 300--500 LOC/hour.

**Cost:** At ~$150--200/hr fully-loaded, Google developers' median 2.6 hrs/week reviewing amounts to ~$20--27K/year per developer on review. A 50-person team investing this amount = ~$1--1.35M/year in review time. Historical ROI data consistently shows code review as one of the highest-ROI quality practices: IBM found 1 hour of inspection saved 20 hours of testing.

### 3.4 Cognitive biases

**Fatigue / cognitive overload** is the most robust bias effect. Detection rates decline from ~87% at small PR sizes to ~28% for >1,000-line PRs. Session effectiveness drops after 60--90 minutes. Each additional 100 LOC adds review time but reduces comment quality. The bugs escaping during overload are precisely the high-value ones: subtle algorithmic flaws and design problems.

**Social / status bias:** ~70% of developers report their relationship with the reviewer affects the process. Junior developers receive more intensive feedback; senior developers get rubber-stamped. Code from high-status developers receives less rigorous review.

**Familiarity bias:** Experienced reviewers provide higher-quality feedback (65--71% useful vs 32--37% for first-timers, ✓ Bosu et al. 2015), but familiarity can also breed false confidence. The usefulness learning curve is steep initially then plateaus -- no significant difference between reviewing a file once versus ten times.

**Anchoring and confirmation bias** are well-established in psychology but lack controlled studies specifically in code review contexts.

**Gender bias:** Analysis of 1,010 FOSS projects found significant gender biases in code acceptance in 13 of 14 datasets, with direction varying by project. Reviewer selection was the most gender-biased aspect (Nadri et al. 2022).

### 3.5 Category-level gap: a novel contribution opportunity

**No published study provides recall rates by defect category or by change type** (beyond the security-specific data from Paul et al. 2021). This is the single largest gap for building a meaningful AI-versus-human comparison benchmark.

What exists:

- **By defect category (partial):** Paul et al. 2021 provides CWE-level detection data for security defects only. CWEs most caught: dangerous functions (CWE-676), resource leaks (CWE-404). CWEs most missed: buffer overflow, integer overflow. Mantyla & Lassenius provides category counts but not recall rates.
- **By change type (almost nothing):** Beller et al. found bug-fixing tasks lead to fewer review changes. Paul et al. found reviews for explicit bug fixes show improved security detection. No study measures detection rates across bug fixes versus features versus refactoring.

**Why this gap exists:** Measuring recall requires knowing both what defects exist (the denominator) and what reviewers found (the numerator). Most studies use post-release defects as a proxy, which introduces confounding: defects reaching production differ systematically by change type.

**This gap is a genuine novel contribution opportunity.** A benchmark producing category-level performance data for both AI and human reviewers across change types and defect categories would fill a significant hole in the literature.

### 3.6 Expertise effects

- **Reviewer file experience is the strongest reviewer-related predictor** [corrected from original source: the overall strongest classifier features were ChangeTrigger and comment status; file experience was the strongest reviewer characteristic] (✓ Bosu et al., MSR 2015). Reviewers who had reviewed a file before were roughly 2x as useful (65--71%) as first-timers (32--37%).
- **Domain expertise matters more than general expertise.** Components without subject matter expert involvement tend to be prone to post-release defects (✓ McIntosh et al. 2016). First Authorship (having created the file) shows the highest positive correlation with source code knowledge. Recency of modification shows the highest negative correlation -- expertise is perishable.
- **Two reviewers is optimal** (✓ Rigby & Bird 2013). This converges across OSS, Microsoft, AMD, and Google. Adding reviewers beyond two provides minimal additional defect discovery. Google diverges: predominantly single-reviewer, compensated by strong automated checks and expertise-based selection.
- **Knowledge transfer:** Reviewing code increases the number of distinct files a developer knows about by 66--150% (? Rigby & Bird 2013 -- the 66--150% range was not confirmed from the original paper, though the finding is referenced in Sadowski et al.).

---

## 4. AI Code Review Performance

### 4.1 Strengths/weaknesses matrix by review dimension

| Review Dimension | AI Performance | Human Performance |
|---|---|---|
| **Style & formatting** | Strong. Consistent, tireless enforcement. | Inconsistent; subject to fatigue and personal preference. |
| **Known vulnerability patterns** | Moderate-strong for known patterns (OWASP, CWE). | Strong when reviewer has security expertise; variable otherwise. |
| **Simple bug patterns** | Moderate. Best single-pass F1 of 19.38% on real-world PRs (~ SWR-Bench). | Variable; depends on reviewer attention and fatigue. |
| **Boilerplate & code duplication** | Strong. Pattern matching at scale. | Weak; tedious for humans to catch consistently. |
| **Speed & availability** | Strong. Instant, 24/7. | Bottleneck; review queues cause delays. |
| **Cross-file dependency analysis** | Weak. Context window limitations. | Moderate-strong for experienced developers. |
| **Architectural design review** | Weak. Cannot evaluate architectural trade-offs. | Strong. Core human expertise. |
| **Business logic validation** | Very weak. No understanding of domain requirements. | Strong. Requires domain knowledge. |
| **Security threat modelling** | Weak for novel threats. Moderate for known patterns. | Strong when performed by specialists. |
| **Inter-procedural reasoning** | Very weak. Near-random accuracy (50--64%) for inter-procedural vulnerabilities (~ CPRVul 2025, arXiv:2602.06751). | Moderate. Humans struggle too but can follow call chains. |
| **Consistency across reviews** | Strong. Same rules applied uniformly. | Weak. Subject to reviewer mood, fatigue, personal style. |
| **Mentoring & knowledge transfer** | Weak. LLM reviews create higher cognitive load and lack the educational relationship of peer review (✓ Alami & Ernst 2025). | Strong. A primary social function of code review. |

### 4.2 Known failure modes

#### Hallucinated findings (false positives)

AI reports bugs, vulnerabilities, or issues that do not exist. Well-tuned tools achieve 5--15% false positive rates; traditional SAST tools hit 30--60%. BitsAI-CR at ByteDance found that "advanced LLMs' raw outputs fail to meet the precision requirements for production deployment" -- a dedicated ReviewFilter stage was essential (✓ Sun et al., FSE 2025). A mathematical proof from the National University of Singapore demonstrates hallucinations are inevitable when LLMs are used as general problem solvers (2024).

SWR-Bench found some ACR techniques with precision below 10%, meaning "developers would need to invest considerable effort verifying validity of generated reports" (✓). The fundamental root cause is capability misalignment: RLHF encourages confident responses even when the model lacks sufficient knowledge.

#### Sycophantic behaviour

**LGTM bias (tendency to approve):** Sycophancy increases with model size -- the largest (52B) models are >90% sycophantic on NLP and philosophy questions (✓ Perez et al., ACL Findings 2023). RLHF does not fix sycophancy and may actively incentivise it (✓). Humans and preference models prefer convincingly-written sycophantic responses over correct ones a non-negligible fraction of the time (✓ Sharma et al., ICLR 2024; 650+ citations [corrected from "289+"]). A 2024 study on AI-driven academic review found LLMs "consistently give higher recommendation scores than human reviewers," the closest analogue to LGTM bias in code review (arXiv:2408.10365).

**Critique sycophancy (backing down when challenged):** Tests on GPT-4o, Claude-Sonnet, and Gemini-1.5-Pro reported 58.19% overall sycophancy rate (2024). OpenAI's April 2025 postmortem explicitly confirmed: "These changes weakened the influence of our primary reward signal, which had been holding sycophancy in check."

**Judge self-preference:** GPT-4 exhibits the highest self-preference bias, quantified via a fairness-inspired metric. The root cause is perplexity-based familiarity -- LLMs prefer texts less "surprising" to them, not their own outputs specifically (✓ Wataoka et al. 2024). Eight models studied; all exhibited measurable self-preference.

**No study specifically measures sycophancy in code review tools.** This remains a confirmed, critical gap.

#### Context window limitations

Most tools analyse diffs in isolation. A change like "add a required field to a shared request schema" looks small in the PR but can silently break dozens of downstream services (Augment Code 2025). Even with 1M+ token windows, "mechanically stuffing lengthy text into an LLM's context window scatters the model's attention, significantly degrading answer quality through the 'Lost in the Middle' effect." SWE-PRBench confirmed this empirically: all 8 frontier models degrade monotonically as context expands from structured diffs to full-context prompts (✓).

#### Cross-function reasoning gaps

Most approaches operate at function level. Naively appending inter-procedural context is unreliable: "real-world context is long, redundant, and noisy, and unstructured context frequently degrades performance" (CPRVul 2025). LLMs "generally learn shallow information about vulnerabilities, such as token meanings, and tend to misjudge when certain tokens are modified, such as function names."

#### Domain knowledge deficits

AI lacks understanding of business rules, regulatory requirements, and organisational conventions. In regulated industries, "the defence that 'the AI made a coding error' is entirely invalid during a regulatory audit." AI-generated risk assessments are characterised as "vibe compliance" -- simulating process rather than implementing it.

#### Persuasive dismissal (CW-POR) in multi-agent debate

Agarwal & Khanna introduced Confidence-Weighted Persuasion Override Rate (CW-POR) to measure "when persuasion overrides truth in multi-agent LLM debates" (✓ arXiv:2504.00374). The "tyranny of the majority" effect causes minority agents to conform to incorrect majority positions, especially in weaker models. Under anonymisation, Qwen-32B's Conformity-Obstinacy gap drops from 0.608 to just 0.024 (✓ arXiv:2510.07517). CW-POR has not yet been applied to code review, but has direct implications: a specialist security agent correctly identifying a vulnerability may be overridden by a majority of non-specialist agents.

### 4.3 Architecture comparison

| Architecture | Quality Evidence | Cost | Key Trade-off |
|---|---|---|---|
| **Single-pass** | Best single-pass F1: 19.38% (~ SWR-Bench). | 1x | Lowest cost; limited by single context window. |
| **Multi-agent specialist** | SWE-bench Verified: 72.2%, a 7.2% improvement over single-agent (2025). Qodo 2.0: F1 60.1% -- highest across 8 tools (Qodo 2026). BitsAI-CR: 75% precision with 12K WAU at ByteDance (✓ Sun et al.). | 2--5x | Higher recall; vulnerable to CW-POR; complex debugging. |
| **Iterative refinement** | Self-Refine improves ~20% absolute on average across tasks (✓ Madaan et al., NeurIPS 2023). Up to 13% on code tasks, though GPT-4 achieves 28.8% on code readability -- making 13% a lower bound for code tasks [corrected with nuance]. | 3--5x per cycle | No additional training needed; diminishing returns after 2--3 iterations; self-bias increases overconfidence. |
| **Mixture-of-Agents (MoA)** | 65.1% on AlpacaEval 2.0 using only open-source LLMs (✓ Wang et al. 2024). Self-MoA (single model, multiple samples) outperformed diverse MoA by 6.6% on general tasks -- but this is from a separate paper (✓ arXiv:2502.00674, Li et al. 2025), not Wang et al. [corrected attribution]. | N x M | Exploits "collaborativeness"; not yet applied to code review. |
| **RAG-augmented** | "Diff + relevant slices" captures 80--90% of needed context. Hybrid retrieval (vector + BM25) provides both semantic and lexical matching. | ~1.5x | Addresses context window limitation; retrieval quality is a bottleneck. |
| **Agentic (tool-using)** | SWE-agent: SOTA on SWE-bench for open-source. Mini-SWE-Agent: >74% on SWE-bench Verified with just 100 lines of code and bash. Agentless: 50.8% at lower cost. | 3--10x | Can explore code on-demand and run tests; non-deterministic; latency concerns. |

**Industry multi-agent systems now deployed:**

- **HubSpot Sidekick** (March 2026): Two-stage Review Agent + Judge Agent. Reduced time-to-first-feedback by 90%, achieved 80% engineer approval. The Judge Agent is "the single most important factor in Sidekick's effectiveness."
- **BitsAI-CR** (ByteDance): Two-stage RuleChecker + ReviewFilter pipeline. 75% precision, 12K weekly active users (✓).
- **Riskified LGTM 2.0** (Feb 2026): Deep analysis mode consumes up to 7x more tokens; caught a runtime validation gap that no human reviewer would have spotted from the diff alone.

### 4.4 Multi-model ensemble approaches

A growing body of evidence suggests that combining reviews from multiple different LLMs improves code review quality beyond what any single model achieves.

#### Demonstrated findings

**Multi-model ensembles outperform best single model on code generation** by 6--18pp. EnsLLM achieved 90.2% accuracy on HumanEval versus 83.5% for the best standalone model (GPT-4o) (arXiv:2503.15838). MPLE achieved up to 17.92% improvement via cross-language ensemble (arXiv:2409.04114).

**Multi-review aggregation improves code review F1 by up to 43.67%** (✓ SWR-Bench). Self-Agg (same model, N=10 passes) boosted Gemini-2.5-Flash from baseline to 21.91% overall F1. The mechanism: generate multiple independent reviews, then aggregate via LLM to retain high-confidence findings and filter low-confidence ones.

**Union of review tools covers more issues than any individual tool.** c-CRAB found four tools collectively passed 41.5% of tests versus a maximum of 32.1% for any single tool (✓). Different tools exhibit different coverage profiles across test categories.

**Different LLMs produce categorically different error types.** Analysis of 558 incorrect code snippets from six LLMs found that for the same failing task, different models make different mistakes (ICSE 2025, arXiv:2406.08731). Syntactic error patterns overlap more across models; semantic error patterns diverge significantly. Ensemble of best four methods solves 71% more samples than the best single method (✓ SWT-Bench, NeurIPS 2024).

**The "popularity trap."** Consensus-based selection (majority voting by syntactic similarity) performs worse than naive baselines for code tasks. Models frequently produce syntactically similar but semantically incorrect solutions. Disagreement-based strategies substantially outperform consensus, realising up to 95% of the theoretical upper bound (✓ Vallecillos-Ruiz et al., arXiv:2510.21513).

#### Aggregation strategies

| Strategy | Mechanism | Code Review Suitability |
|---|---|---|
| **Union** | Take all findings from all models | Maximises recall but precision is already the bottleneck (SWR-Bench). |
| **Intersection** | Keep findings flagged by multiple models | Reduces noise but risks losing unique true positives. |
| **Majority voting** | Standard self-consistency | Caution: popularity trap (Vallecillos-Ruiz). Works for discrete outputs, less clear for open-ended comments. |
| **LLM-as-arbiter** | Judge model evaluates each finding | Panel of 3 smaller models (PoLL) outperforms single GPT-4 judge while being 7--8x cheaper (✓ Verga et al., arXiv:2404.18796). |
| **Diversity-based** | Select by lowest similarity, not highest | Best theoretical coverage. Effective even in two-model ensembles. |
| **Cascade/routing** | Route simple queries to cheap models, complex to expensive | FrugalGPT matches GPT-4 with up to 98% cost reduction (✓ arXiv:2305.05176). |

**Key insight:** Code review findings are not discrete choices. They are natural language descriptions requiring semantic deduplication, confidence assessment, and priority ranking. No existing paper addresses the full pipeline of multi-model review aggregation with semantic deduplication.

#### Self-MoA versus multi-model

Self-MoA (single model, multiple samples) outperformed diverse MoA by 6.6% on general tasks (✓ arXiv:2502.00674). However, repeated sampling from the same model yields outputs "trapped" in local clusters due to post-training alignment (arXiv:2502.11027). DivSampling (prompt perturbation to break clustering) improves Pass@10 by 75.6% for code generation.

**Resolution of the apparent contradiction:** Self-MoA works when iterative refinement is the primary mechanism. Multi-model ensembles work when different error profiles are the mechanism. For code review, where the goal is coverage of distinct issue types, inter-model diversity likely matters more -- but this is hypothesised, not demonstrated.

### 4.5 Commercial tool benchmarks

| Tool | Key Metric | Source | Confidence |
|---|---|---|---|
| **Qodo 2.0** | F1: 60.1%, Recall: 56.7% | Qodo benchmarks 2026 | ~ (vendor) |
| **CodeRabbit** | 46% bug detection accuracy. 2M+ repos reviewed. | Industry benchmarks | ~ (vendor) |
| **Augment Code** | SWE-bench: 70.6%. 400K+ file context engine. | Augment benchmarks 2026 | ~ (vendor) |
| **BitsAI-CR (ByteDance)** | 75% precision, 26.7% outdated rate (Go), 12K WAU | Sun et al. FSE 2025 | ✓ |
| **Google AutoCommenter** | Detects violations in 6% of changed files. High acceptance. | Vijayvergiya et al. AIware 2024 | ✓ |
| **Traditional SAST** | <20% bug detection. 30--60% false positive rate. | Multiple industry sources | ~ |

The MSR 2026 empirical study by Chowdhury et al. provides the most rigorous independent assessment: 12 of 13 code review agents averaged a signal ratio below 60%, and CRA-only PRs had a 23pp lower merge rate than human-reviewed PRs (✓).

---

## 5. Evaluation Methodology

### 5.1 Metrics taxonomy

#### Core detection metrics

**Precision** (TP / (TP + FP)): The fraction of AI-generated comments identifying genuine issues. Google deliberately targets 50% precision -- not a maximum (Google Research Blog). Higher precision reduces recall; lower precision erodes trust.

**Recall** (TP / (TP + FN)): The fraction of actual issues identified. Critical caveat: recall is only meaningful relative to ground truth completeness. If ground truth only captures what human reviewers commented on, recall measures "finding what humans found," not "finding all issues."

**F1** (harmonic mean of precision and recall): For single-number comparison. For security-critical reviews (where missing a vulnerability is catastrophic), use F2 (weights recall higher). For noisy environments where trust matters most, use F0.5 (weights precision higher).

#### Quality metrics

**Severity calibration:** Spearman correlation between AI-assigned and human-assigned severity. Cliff's delta is appropriate for comparing severity calibration between tools.

**Actionability:** 73.8% of automated review comments were resolved in one study (arXiv:2412.18531), but overall PR closure duration increased from 5h52m to 8h20m after introducing automated reviews.

**CRScore** (reference-free comment quality): Evaluates conciseness, comprehensiveness, and relevance. Achieves 0.54 Spearman correlation with human judgement (✓ Naik et al., NAACL 2025). System-level ranking: 0.95 Spearman and 0.89 Kendall tau (✓). Uses open-source Magicoder-S-DS-6.7B for pseudo-reference generation. CRScore++ adds reinforcement learning with verifiable tool feedback (arXiv:2506.00296).

#### Per-category metrics

Different issue types require separate evaluation. Report precision, recall, and F1 separately per category. Aggregate metrics hide important performance variation -- a tool catching 100% of style issues and 0% of security bugs looks good on aggregate but is dangerous.

### 5.2 LLM-as-judge methodology

#### Foundational work

Zheng et al. (2023) established the paradigm. GPT-4 as judge achieves >80% agreement with human preferences -- actually exceeding inter-human agreement of 81% [corrected from "equivalent to"], achieving 85% in pairwise comparison (✓ arXiv:2306.05685). Both pairwise and single-answer grading show similar agreement rates; the claimed superiority of pairwise over direct scoring is not strongly supported by this paper's numbers [corrected with nuance].

#### Known biases and mitigations

**Position bias:** Comprehensive study across 15 LLM judges (not 12 [corrected from original source]), 150,000+ evaluation instances (✓ Shi et al., AACL-IJCNLP 2025, arXiv:2406.07791 [corrected venue and added arXiv ID]). Capable judges achieve near-perfect Repetition Stability >0.95. *Mitigation:* present candidates in both orders and average; use few-shot examples demonstrating balanced judgements.

**Verbosity bias:** Judges prefer longer responses regardless of quality. Detailed structured prompts reduce this -- when rubrics emphasise correctness, models can distinguish informative content from padding. *Mitigation:* use structured rubrics with explicit quality criteria.

**Self-preference bias:** All 8 models studied exhibit measurable self-preference driven by output perplexity, not self-recognition (✓ arXiv:2410.21819). *Mitigation:* use a different model family as judge than the one being evaluated.

**Leniency/positive bias:** 14 LLMs as judges show TPR >96% but TNR <25% (✓ arXiv:2510.11822). Excellent at detecting quality, poor at detecting its absence. *Mitigation:* minority-veto ensemble strategies; regression-based bias correction using small human-annotated calibration sets.

**Framing bias:** Subtle prompt wording changes shift judgements significantly. Predicate-positive versus predicate-negative constructions produce different results (✓ arXiv:2601.13537). *Mitigation:* test prompts with both positive and negative framing.

**Anchoring bias:** Providing correct references improves judge performance substantially. Qwen 2.5 7B with a reference outperformed GPT-4o without one (kappa 0.75 vs 0.59) (✓ arXiv:2503.05061). Incorrect references degrade performance below the reference-free baseline. *Mitigation:* validate reference quality before providing it.

#### Best practices for judge design

1. **Use structured rubrics** with explicit scoring criteria per level. Rubrics produce harsher but more consistent judgements.
2. **Multi-judge panels:** 3 judges from different model families. Report per-judge agreement (Fleiss's kappa) and aggregate. Majority voting for binary decisions, median for ordinal scores.
3. **5--10 few-shot examples** significantly improve consistency. Include examples covering all outcomes. Difficulty-based selection outperforms random.
4. **Structured output** (JSON schema) reduces parsing ambiguity.
5. **Never use the judge model as a reviewer model.** Self-preference bias will inflate scores.

### 5.3 Ground truth construction methods

| Method | Objectivity | Scalability | Completeness | Issue Types | Cost |
|--------|-------------|-------------|--------------|-------------|------|
| **Expert curation** | Medium | Low (100s) | Medium | All types | High |
| **Mining PRs** | Low (noisy) | Very high (millions) | Low (only what reviewers caught) | All types (noisy) | Low |
| **Test-based (c-CRAB)** | Very high (deterministic) | Medium (100s) | Low (only testable issues) | Bugs, security | Medium |
| **Synthetic injection** | High | High | N/A (synthetic) | Bugs, security | Low |
| **Mutation testing** | High | High | N/A (synthetic) | Bugs only | Low |
| **Bug-fix reconstruction** | High (real bugs) | Medium | Low (only fixed bugs) | Bugs | Medium |

**Key findings on ground truth quality:**
- CodeReviewer dataset: only ~64% of sampled comments are valid upon inspection (✓ Li et al. 2022).
- CodeReviewQA: only 13% retention rate after manual curation (✓ arXiv:2503.16167).
- CRScore found CodeReviewer reference reviews average only 1.88/5 for comprehensiveness (✓).
- LLM-assisted annotation with human validation reduces annotation time by ~25% while maintaining quality.

**Recommended combination:** Use expert curation for the core set (100--200 examples). Test-based verification for functional correctness. Mining for large-scale statistics. Bug-fix reconstruction for real-world coverage. Security: real CVEs from OpenSSF + test-based verification.

### 5.4 Statistical methods

#### Confidence intervals

Use Wilson score intervals for precision and recall (robust from n~10, asymmetric, never overshoots [0,1]). Use bootstrap BCa (bias-corrected and accelerated) for F1, with 5,000 iterations for publication-quality results. **Do NOT use the Wald (normal approximation) interval** -- it has poor coverage and can produce zero-width intervals at p=0 or p=1. This recommendation traces to Agresti & Coull (1998), who specifically advocate their adjusted interval (which approximates Wilson) over the Wald interval [corrected with nuance: Agresti & Coull propose their own interval, closely related to Wilson but not identical].

Confidence intervals for F1 can also be computed analytically via Wilson direct and Wilson indirect methods (Takahashi et al. 2022, arXiv:2309.14621), which address binary F1 score [corrected from original source: the paper covers binary F1 only, not micro-averaged precision/recall or macro F1, and does not use the delta method].

#### Effect sizes

Use **Cliff's delta** (non-parametric) for comparing ordinal data (severity ratings, quality scores). Interpretation: |delta| < 0.147 negligible, 0.147--0.33 small, 0.33--0.474 medium, >0.474 large. Use **Cohen's d** only when normality is verified and data is continuous.

A precision/recall difference of 10 percentage points represents a practically meaningful improvement. Always state practical significance alongside statistical significance.

#### Power analysis

| Difference to Detect | Power 80%, alpha 0.05 | Power 90%, alpha 0.05 |
|---------------------|----------------------|----------------------|
| 20 pp | ~50 per group | ~65 per group |
| 15 pp | ~90 per group | ~120 per group |
| 10 pp | ~200 per group | ~260 per group |
| 5 pp | ~780 per group | ~1,050 per group |

**Minimum viable benchmark:** 100 code reviews with at least 200 ground truth issues. **For publishable results:** 200+ code reviews. **For fine-grained per-category analysis:** scale proportionally -- if only 20% of issues are security-related, need 5x the total.

For paired comparisons (same code reviewed by two systems), McNemar's test is appropriate and requires smaller samples than unpaired tests.

#### Multiple comparisons

- 2--3 tools: Holm-Bonferroni (uniformly more powerful than Bonferroni, same guarantees).
- 5+ tools: Benjamini-Hochberg (FDR at 0.05).
- Always report uncorrected p-values alongside corrected ones.

### 5.5 Reproducibility requirements

**LLM outputs are stochastic.** Accuracy fluctuations of up to 15% across identical inference runs have been documented (~ arXiv:2408.04667, though the paper measures stability via TARr@N and TARa@N, not "flip rates") [corrected: the originally cited 5--12% flip rate at temperature 0 and 12--24% at temperature 1.0 do not appear in this paper, which only tests at temperature 0].

**83% of single-run leaderboard results produce rank inversions** compared to three-run aggregates (✓ arXiv:2509.24086). **Minimum 3 independent runs per configuration.** 3--5 run aggregation "dramatically improves consistency" (✓ Wang & Wang 2025).

**Recommended protocol:**
1. Run each configuration 3 times minimum (5 ideal).
2. Report mean, standard deviation, and range across runs.
3. Use ICC to quantify run-to-run consistency (target >=0.60).
4. Use temperature 0 for maximum reproducibility.
5. Pin exact model versions/snapshots.
6. Record all sampling parameters.

**Cross-model comparison:** Same evaluation set, same judge, randomised presentation order, blind evaluation (judge does not know which tool produced each review), temporal consistency (short time window to avoid model version drift).

---

## 6. Available Datasets and Benchmarks

### 6.1 Comparison table (with corrected availability data)

| Dataset | Year | Size | Languages | GT Method | Availability | Category Analysis |
|---|---|---|---|---|---|---|
| **CodeReviewer** | 2022 | ~150K reviews | 9 | Mined from GitHub PRs | Available (Zenodo, CC BY 4.0) | No |
| **CRQBench** | 2024 | 100 questions | C++ | LLM+human curation | Unavailable [corrected: no public repo found despite paper claiming open-source release] | No |
| **CodeReviewQA** | 2025 | 900 examples | 9 | Manual verification (13% retention) | Available (HuggingFace, MIT) | By language only |
| **c-CRAB** | 2026 | 234 tests, 184 PRs [corrected from "~100 PRs"] | Python | Test-based | Available (GitHub) | 6 categories |
| **SWE-PRBench** | 2026 | 350 PRs | Multi-lang | Human review comments | Available (HuggingFace, CC BY 4.0) | By difficulty: Type1_Direct 66.3%, Type2_Contextual 21.4%, Type3_Latent 12.3% [corrected from 34%/53.7%] |
| **SWE-CARE** | 2025 | 671 test instances (v0.2.0) [corrected from 601], 7,757 total | Python, Java [corrected: now includes Java] | Multi-faceted annotation | Available (HuggingFace, Apache 2.0) | 9 PR domains |
| **ContextCRBench** | 2025 | 67,910 entries | 9 | Multi-stage filtering | Available [corrected from "unclear": GitHub repo with downloadable data exists] | By review task |
| **SWRBench** | 2025 | 2,000 PRs [corrected from 1,000: 1,000 Change-PRs + 1,000 Clean-PRs] | Multi-lang | Manual verification | Unavailable [corrected: no permanent public repo found, only anonymous review URL] | Functional errors focus |
| **ReviewBenchLite** | 2025 | ~117 issues | Python | Production issues traced to fixes | Restricted [corrected: summary public, full data requires email] | 5 categories |
| **CRScore corpus** | 2025 | 2.9K annotations | Python, Java, JS | Human Likert annotations | Partially available (code repo MIT, annotations status unclear) | Quality dimensions |
| **Greptile Benchmark** | 2025 | 50 PRs | 5 | Known bug introductions | Available (reproducible) | By severity |
| **Martian Benchmark** | 2026 | 50 PRs | 5 | Golden comments with severity | Available (GitHub, MIT). 12+ tools evaluated [corrected from "17"] | By severity |

### 6.2 Detailed assessment of key datasets

**c-CRAB** is the most principled evaluation methodology: human review comments are converted to executable tests, providing deterministic, reproducible assessment. Individual tool pass rates range from 20.1% to 32.1%. Union across four tools: 41.5% (✓). Limitation: Python only, relatively small, cannot evaluate style or design comments.

**SWE-PRBench** has the best contamination-aware design: Repository Quality Score (RQS) with contamination penalty, and explicit evaluation of how context volume affects performance. Cohen's kappa = 0.75 for judge validation (✓). Key finding: all 8 models degrade monotonically as context expands (✓). Language distribution: Python 69%, JavaScript 11%, Go 10%, TypeScript 6%, Java 4%.

**SWRBench** is the largest manually verified set at 2,000 PRs [corrected], with ~90% evaluator agreement (✓). Key contribution: multi-review aggregation strategy improving F1 by up to 43.67% (✓). However, the dataset cannot currently be located at any permanent public URL.

**SWE-bench Verified** remains the dominant adjacent benchmark (500 instances). The claim that "OpenAI dropped it in Feb 2026 citing 59.4% flawed tests" could not be verified -- the benchmark appears active on the leaderboard with submissions through Feb 2026 [unverified -- not confirmed from primary source]. The METR study found ~50% of SWE-bench-passing PRs would be rejected by human maintainers, demonstrating that code generation benchmarks are insufficient for code review evaluation.

**Vulnerability datasets** (Devign, BigVul, DiverseVul) are unsuitable for direct use in code review evaluation due to extreme label noise (38--80% accuracy), near-universal context dependency, and binary classification format that does not map to review comments.

### 6.3 Evaluation harness landscape

The field has converged on four approaches:

| Approach | Strengths | Weaknesses | Best Use |
|---|---|---|---|
| **Reference-based** (BLEU, ROUGE) | Fast, automated | Fundamentally flawed for one-to-many task; noisy references; CRScore shows near-zero correlation in many cases | Declining. Not recommended. |
| **Test-based** (c-CRAB) | Objective, reproducible, deterministic | Only works for testable issues; compute-intensive | Functional correctness evaluation |
| **LLM-as-judge** (SWE-PRBench, SWRBench) | Flexible, scalable, can evaluate any comment type | Introduces LLM biases; requires validation (kappa >=0.60) | Comprehensive evaluation |
| **CRScore** (reference-free) | No reference needed; fine-grained quality dimensions | 0.54 correlation (moderate); systematically over/underestimates in some cases | Comment quality assessment |

**The ground truth completeness problem** remains unsolved. All approaches suffer from incomplete ground truth -- human reviewers do not catch everything, so using human reviews as ground truth penalises AI that catches novel issues. No benchmark yet solves this. CodeFuse-CR-Bench's comprehensiveness metric partially addresses it.

### 6.4 Gap analysis

What an ideal AI code review benchmark would include:

- 500+ PRs across 5+ languages with 10+ issue categories
- Category-balanced sampling (not just bug fixes)
- Dual ground truth: human expert annotations + executable verification
- Inter-rater agreement >0.8 (kappa)
- Contamination-resistant: post-2024 data, non-starred repos, contamination checks
- Severity taxonomy: critical/high/medium/low
- Systematic false positive measurement
- Executable evaluation harness (Docker-based)
- Multiple evaluation modes: test-based + LLM-judge + human eval
- PR type metadata: bug fix, feature, refactor, performance, dependency, documentation
- Repository diversity: 50+ repos across domains, sizes, review cultures

No existing benchmark meets more than 4--5 of these criteria.

---

## 7. Cross-Thread Synthesis

### 7.1 Convergent findings across threads

**Finding 1: The review quality paradox.** Code review is optimised for maintainability and knowledge transfer (genuinely valuable for long-lived systems), but poorly optimised for catching the high-severity functional defects that cause incidents. This finding converges from the human baseline data (75:25 ratio, Thread 4), the AI performance data (AI is strongest at style/consistency, weakest at architecture/business logic, Thread 2), and the benchmark landscape (most benchmarks focus on functional bugs, missing the dominant maintainability category, Thread 5).

**Finding 2: Precision is the bottleneck.** Multiple independent lines of evidence converge: SWR-Bench shows precision below 10% for many techniques; BitsAI-CR needed a dedicated ReviewFilter to bring precision to usable levels; Chowdhury et al. found 12/13 CRAs have signal ratios below 60%; developers experiencing fewer false positives are 2.5x more likely to merge without reviewing (Qodo 2025). The trust-precision relationship is the single most important dynamic in AI code review adoption.

**Finding 3: Context is everything, but more context degrades performance.** SWE-PRBench shows all models degrade with more context (Thread 5). RAG-augmented approaches help but retrievers "overfit to superficial features" (Thread 2). The "Lost in the Middle" effect limits even 1M-token windows. Yet cross-file reasoning -- which requires extensive context -- is where AI is weakest and incidents are most costly (Threads 1 and 2).

**Finding 4: Evaluation methodology is more mature than its adoption.** Rigorous methods exist (Wilson CIs, bootstrap BCa, McNemar's test, ICC for reproducibility, CRScore for reference-free evaluation) but most papers report point estimates without confidence intervals. Statistical validation in LLM evaluation papers has declined, not improved (Thread 3).

**Finding 5: Multi-model approaches show consistent improvement.** Union of tools covers 29% more issues than the best single tool (c-CRAB). Multi-review aggregation improves F1 by 43.67% (SWR-Bench). Ensemble of bug-fix methods solves 71% more than the best single method (SWT-Bench). Different LLMs make categorically different errors (ICSE 2025). This evidence converges from code generation, code repair, and code review independently.

### 7.2 The three strongest novel contribution opportunities

**1. Category-level performance matrix (change type x defect category).** No published study provides recall rates by defect category (beyond security) or by change type. A benchmark producing this data for both AI and human reviewers would fill the single largest gap in the code review literature. The 75:25 ratio and the Chromium OS security data serve as validation anchors.

**2. Sycophancy and LGTM bias measurement in code review.** Sycophancy is well-documented in general LLM settings but unmeasured in code review. A benchmark including adversarial test cases (code with known issues where the AI is expected to flag problems) would directly measure LGTM bias. The metric is straightforward: the fraction of known-bad code the AI approves. This would be the first published measurement of code-review-specific sycophancy.

**3. Multi-model ensemble evaluation under controlled cost constraints.** No study has compared N different models (1 pass each) versus 1 model (N passes) versus N models (N passes) on code review specifically. SWR-Bench tested multi-review aggregation but primarily with Self-Agg (same model). c-CRAB evaluated four tools but each with its own scaffold. A controlled comparison isolating model diversity from iteration depth would resolve the Self-MoA versus multi-model debate for code review.

### 7.3 Contradictions and tensions in the literature

**Self-MoA versus multi-model diversity.** Self-MoA outperforms diverse MoA by 6.6% on general tasks (arXiv:2502.00674), but ensemble literature consistently shows multi-model benefits for code tasks. Resolution likely depends on whether the goal is precision (where refinement helps) or recall (where diversity helps). For code review, both matter -- but coverage of distinct issue types suggests inter-model diversity matters more. This is untested.

**Context helps versus context hurts.** RAG literature shows context improves performance. SWE-PRBench shows all models degrade with more context. Resolution: the quality and relevance of context matter more than quantity. "Diff + relevant slices" (targeted context) outperforms "full file content" (unfocused context).

**Review frequency versus review quality.** ~ DORA 2025 reports code review time increased 91% and PR size grew 154% as AI adoption increased (industry report). More code is being reviewed but quality metrics are not improving proportionally. The tension: AI increases throughput but may reduce per-review quality through automation complacency.

**Automation complacency versus trust deficit.** ~ Developers experiencing <20% hallucinations are 2.5x more likely to merge without review (Qodo 2025, vendor report). ~ Only 29% of developers trust AI output (Stack Overflow 2025, industry survey). Both over-trust and under-trust coexist, likely segmented by experience level and tool quality.

### 7.4 What the framework must account for

1. **The 75:25 ratio** means that most review activity (and most ground truth in mined datasets) concerns evolvability, not functional defects. A benchmark focusing only on bug detection misses 75% of review activity.
2. **Per-category evaluation** is essential. Aggregate metrics hide critical variation. A tool catching 100% of style issues and 0% of security bugs is dangerous regardless of its F1 score.
3. **False positive rates** determine real-world utility at least as much as recall. The trust-precision relationship means a tool with 60% precision and 40% recall may outperform one with 40% precision and 60% recall in practice.
4. **Reproducibility** requires minimum 3 runs, with ICC reporting.
5. **Cost normalisation** enables fair comparison across architectures. Record token usage and wall-clock time alongside quality metrics.
6. **Change type metadata** (bug fix, feature, refactoring, config, dependency) enables the novel category-level analysis that fills the literature gap.

---

## 8. Gaps and Open Questions

### 8.1 Critical gaps (highest significance for the benchmark)

**Incident-to-review-gap causal chains.** No dataset links specific production incidents to specific review gaps. Bernardo et al. (EMSE 2020) replicated McIntosh et al. on Google Chrome, confirming the relationship between review coverage/participation and defect rates, but this measures post-release defects, not incidents with impact data. The "LGTM smells" study (ICSME 2024) found 64.7% of PRs had comment-free reviews, and comment-free reviews exhibited LGTM smells 3.5x more frequently, but no statistically significant difference was found in issue reopening rates. The Azure AutoARTS taxonomy identifies "Code.Bug.Change" as a root cause category but does not trace back to review quality.

**AI sycophancy in code review (LGTM bias).** No controlled experiment measures LGTM bias in AI code review tools. No study measures critique sycophancy when developers push back on AI findings. No study measures whether AI reviewers soften severity ratings compared to humans. The academic peer review leniency finding (arXiv:2408.10365) has not been replicated in code review contexts.

**Cross-file reasoning for code review.** DependEval (ACL Findings 2025, arXiv:2503.06689) tests cross-file dependency understanding but not review-specific scenarios. SWE-PRBench has only 12.3% cross-file cases -- too small for per-category statistical power. No benchmark tests whether AI detects that a change in file A breaks file B in a review context.

### 8.2 High-significance gaps

**CW-POR in multi-agent code review.** CW-POR exists (arXiv:2504.00374). Multi-agent code review systems exist (HubSpot Sidekick, OCR, BitsAI-CR). Nobody has measured whether a specialist agent's valid finding gets overridden by a majority of non-specialist agents. The HubSpot Judge Agent is closest to a conformity mitigation mechanism, but it is a filter (single-agent judge), not a debate protocol.

**Cost-quality Pareto frontier.** No systematic study maps the cost-quality trade-off across single-pass, multi-agent, iterative, MoA, RAG, and agentic approaches on the same benchmark. Partial data exists: single-pass at 1x cost achieves F1 ~19%; multi-agent at 2--5x achieves F1 ~60%; deep analysis at 7x catches issues humans miss. The CLEAR framework (arXiv:2511.14136) proposes Cost-Normalised Accuracy but has not been applied to code review.

**Longitudinal AI-augmented review.** METR's RCT found AI tools actually increased task completion time by 19% (✓ arXiv:2507.09089, peer-reviewed). Anthropic's skill formation study found 17% lower quiz scores for AI-assisted learners (~ industry research). ~ GitClear reports 4x more code cloning and an 8-fold increase in duplicate code blocks (vendor report). ~ DORA 2025 reports bug rates up 9% despite code review time up 91% (industry report). But no study specifically measures how human code review behaviour changes when AI handles certain categories.

**Developer trust calibration.** ~ 84% of developers use AI tools, but only 29% trust AI output (Stack Overflow 2025, industry survey). ~ 96% have difficulty trusting AI code is correct, yet only 48% always verify (Sonar 2026, industry survey). ~ Developers experiencing <20% hallucinations are 2.5x more likely to merge without review (Qodo 2025, vendor report). No controlled study measures whether developers correctly distinguish true positives from false positives in AI review output.

### 8.3 Moderate-significance gaps

**Configuration review effectiveness.** IaC scanner detection rates exist (Checkov 74--84%, tfsec 79--89%, KICS 88--100%), but no academic study compares review processes for application code versus infrastructure code. No data on whether AI code review tools can effectively review Terraform, K8s manifests, or Helm charts. No benchmark dataset includes IaC changes.

**Review effectiveness across programming languages.** A prominent reproduction study (Berger et al., ACM) found the language-defect correlation is weaker than believed -- many claims of causal links are "not supported by the data at hand." DependEval found LLMs struggle more with statically typed languages in cross-file tasks. No benchmark stratifies results by language with sufficient statistical power per language.

**Dependency review practices.** 54% of Dependabot updates are deleted without action. Supply chain detection tools are effective (OSCAR: 0.99 precision), but no study evaluates AI code review tools' ability to flag suspicious dependency changes. The gap between automated scanner detection rates and human/AI review for dependency changes is unstudied.

### 8.4 What remains unfilled after this review

1. No dataset linking production incidents to review gaps at scale
2. No code-review-specific sycophancy measurement
3. No cross-file code review benchmark with sufficient statistical power
4. No controlled multi-model versus single-model code review study
5. No semantic deduplication methodology for review findings
6. No category-level human baseline data (beyond security)
7. No longitudinal study of human behaviour change with AI review tools
8. No cost-quality Pareto analysis for code review architectures
9. No controlled developer trust calibration study
10. No IaC/configuration change review benchmark

---

## 9. Complete Bibliography

### Code Review Fundamentals

- Bacchelli, A. and Bird, C. "Expectations, Outcomes, and Challenges of Modern Code Review." ICSE 2013, pp. 712--721. [✓ verified from primary source]
- Beller, M., Bacchelli, A., Zaidman, A., and Juergens, E. "Modern Code Reviews in Open-Source Projects: Which Problems Do They Fix?" MSR 2014. [✓ verified]
- Bosu, A., Greiler, M., and Bird, C. "Characteristics of Useful Code Reviews: An Empirical Study at Microsoft." MSR 2015. [✓ verified]
- Czerwonka, J. et al. "Code Reviews Do Not Find Bugs: How the Current Code Review Best Practice Slows Us Down." ICSE-SEIP 2015.
- Kemerer, C.F. and Paulk, M.C. "The Impact of Design and Code Reviews on Software Quality." IEEE TSE, 35(3), 2009. [✓ verified]
- Mantyla, M.V. and Lassenius, C. "What Types of Defects Are Really Discovered in Code Reviews?" IEEE TSE, 35(3), 2009. [✓ verified via replication studies]
- McIntosh, S., Kamei, Y., Adams, B., and Hassan, A.E. "The Impact of Code Review Coverage and Participation on Software Quality." MSR 2014; extended in EMSE 2015/2016. [✓ verified]
- Rigby, P.C. and Bird, C. "Convergent Contemporary Software Peer Review Practices." ESEC/FSE 2013, pp. 202--212. [✓ verified via Sadowski et al.]
- Sadowski, C., Soderberg, E., Church, L., Sipko, M., and Bacchelli, A. "Modern Code Review: A Case Study at Google." ICSE-SEIP 2018. [✓ verified]
- Siy, H. and Votta, L. "Does the Modern Code Inspection Have Value?" IEEE Software, 2001.
- Thongtanunam, P., McIntosh, S., Hassan, A.E., and Iida, H. "Review Participation in Modern Code Review." EMSE, 22(2), 2017.

### Security in Code Review

- Paul, R., Turzo, A.K., and Bosu, A. "Why Security Defects Go Unnoticed during Code Reviews? A Case-Control Study of the Chromium OS Project." ICSE 2021. [? unverified from primary source]
- Di Biase, M. et al. Security focus in review experiments.
- OpenSSL/PHP Study. Springer, 2024.
- Bosu, A. et al. "Identifying Characteristics of Vulnerable Code Changes." FSE 2014.

### AI Code Review Systems

- Li, Z. et al. "Automating Code Review Activities by Large-Scale Pre-Training." FSE 2022. arXiv:2203.09095. [✓ verified]
- Sun, T. et al. "BitsAI-CR: Automated Code Review via LLM in Practice." FSE 2025. arXiv:2501.15134. [✓ verified]
- Vijayvergiya, M. et al. "AI-Assisted Assessment of Coding Practices in Modern Code Review." AIware 2024. arXiv:2405.13565.
- Cihan, U. et al. "Automated Code Review In Practice." ICSE SEIP 2025. arXiv:2412.18531.
- Rasheed, Z. et al. "AI-powered Code Review with LLMs: Early Results." arXiv:2404.18496, 2024.
- Chowdhury, K. et al. "From Industry Claims to Empirical Reality." MSR 2026. arXiv:2604.03196. [✓ verified]

### Benchmarks and Evaluation

- Khan, T.I. et al. "A Survey of Code Review Benchmarks and Evaluation Practices in Pre-LLM and LLM Era." arXiv:2602.13377, Feb 2026. [✓ verified]
- Naik, A. et al. "CRScore: Grounding Automated Evaluation of Code Review Comments." NAACL 2025. arXiv:2409.19801. [✓ verified]
- SWR-Bench. "Benchmarking and Studying the LLM-based Code Review." arXiv:2509.01494, 2025.
- c-CRAB. "Code Review Agent Benchmark." arXiv:2603.23448, March 2026. [✓ verified]
- Kumar, D. "SWE-PRBench: Benchmarking AI Code Review Quality Against Pull Request Feedback." arXiv:2603.26130, March 2026. [✓ verified]
- Lin, H.Y. et al. "CodeReviewQA: The Code Review Comprehension Assessment for LLMs." ACL Findings 2025. arXiv:2503.16167. [✓ verified]
- Guo, H. et al. "CodeFuse-CR-Bench / SWE-CARE." arXiv:2509.14856, 2025. [✓ verified]
- ContextCRBench. "Benchmarking LLMs for Fine-Grained Code Review with Enriched Context." arXiv:2511.07017, Nov 2025.
- Jimenez, C.E. et al. "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?" ICLR 2024.
- Martian Code Review Bench, March 2026. github.com/withmartian/code-review-benchmark.

### Sycophancy and LLM Biases

- Perez, E. et al. "Discovering Language Model Behaviors with Model-Written Evaluations." ACL Findings 2023. arXiv:2212.09251. [✓ verified]
- Sharma, M. et al. "Towards Understanding Sycophancy in Language Models." ICLR 2024. arXiv:2310.13548. [✓ verified]
- Wataoka, K. et al. "Self-Preference Bias in LLM-as-a-Judge." arXiv:2410.21819, 2024. [✓ verified]
- Shi, L. et al. "Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge." AACL-IJCNLP 2025. arXiv:2406.07791. [✓ verified, corrected venue]
- Ye, S. et al. "Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge." arXiv:2410.02736, 2024.
- Leniency bias. arXiv:2510.11822. [✓ verified]
- Framing bias. arXiv:2601.13537. [✓ verified]
- Anchoring bias. arXiv:2503.05061. [✓ verified]

### LLM-as-Judge Foundational

- Zheng, L. et al. "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena." NeurIPS 2023. arXiv:2306.05685. [✓ verified]
- Verga, P. et al. "Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models." arXiv:2404.18796, 2024.

### Multi-Agent and Architecture

- Madaan, A. et al. "Self-Refine: Iterative Refinement with Self-Feedback." NeurIPS 2023. arXiv:2303.17651. [✓ verified]
- Wang, J. et al. "Mixture-of-Agents Enhances Large Language Model Capabilities." arXiv:2406.04692, 2024. [✓ verified]
- Li, X. et al. "Rethinking Mixture-of-Agents: Is Mixing Different Large Language Models Beneficial?" arXiv:2502.00674, 2025. [✓ verified]
- Yang, J. et al. "SWE-agent." NeurIPS 2024.
- Xia, C. et al. "Agentless: Demystifying LLM-based Software Engineering Agents." arXiv:2407.01489, 2024.
- Qian, C. et al. "ChatDev: Communicative Agents for Software Development." ACL 2024. arXiv:2307.07924.
- Hong, S. et al. "MetaGPT: Meta Programming for Multi-Agent Collaborative Framework." ICLR 2024. arXiv:2308.00352.

### Multi-Agent Debate and Conformity

- Agarwal, M. et al. "When Persuasion Overrides Truth in Multi-Agent LLM Debates: Introducing CW-POR." arXiv:2504.00374, 2025. [✓ verified]
- "Measuring and Mitigating Identity Bias in Multi-Agent Debate via Anonymization." arXiv:2510.07517, 2025. [✓ verified]
- "Talk Isn't Always Cheap: Understanding Failure Modes in Multi-Agent Debate." arXiv:2509.05396, 2025.

### Multi-Model Ensembles for Code

- EnsLLM. "Enhancing LLM Code Generation with Ensembles." arXiv:2503.15838, 2025.
- MPLE. "Multi-Programming Language Ensemble." arXiv:2409.04114, 2024.
- Vallecillos-Ruiz, H. et al. "Wisdom and Delusion of LLM Ensembles for Code Generation and Repair." arXiv:2510.21513, 2025.
- LLM-TOPLA. "Efficient LLM Ensemble by Maximising Diversity." EMNLP 2024 Findings. arXiv:2410.03953.
- Chen, Z. et al. "Harnessing Multiple Large Language Models: A Survey on LLM Ensemble." arXiv:2502.18036, 2025.
- Ensemble survey. "Ensemble Learning for LLMs in Text and Code Generation." arXiv:2503.13505, 2025.

### Self-Consistency and Sampling

- Wang, X. et al. "Self-Consistency Improves Chain of Thought Reasoning in Language Models." ICLR 2023. arXiv:2203.11171.
- DivSampling. "On the Effect of Sampling Diversity in Scaling LLM Inference." arXiv:2502.11027, 2025.
- FrugalGPT. Chen, L. et al. TMLR December 2024. arXiv:2305.05176.

### Vulnerability Detection

- M2CVD. "Multi-Model Collaboration for Code Vulnerability Detection." ACM TOSEM. arXiv:2406.05940.
- CPRVul. "Beyond Function-Level Analysis: Context-Aware Reasoning for Inter-Procedural Vulnerability Detection." arXiv:2602.06751, 2025.
- Devign. Zhou, Y. et al. NeurIPS 2019.
- BigVul. Fan, J. et al. MSR 2020.
- DiverseVul. Chen, Y. et al. RAID 2023.

### Cross-File Reasoning

- DependEval. Du, Y. et al. "Benchmarking LLMs for Repository Dependency Understanding." ACL Findings 2025. arXiv:2503.06689.
- DI-BENCH. Inter-file call graph reconstruction, January 2025.
- LoCoBench. Long-context code benchmark, 2025.

### Human Factors

- Alami, A. and Ernst, N. "Human and Machine: How Software Engineers Perceive and Engage with AI-Assisted Code Reviews." arXiv:2501.02092, 2025. [✓ verified]
- Adalsteinsson, F. et al. "Rethinking Code Review Workflows with LLM Assistance." arXiv:2505.16339, 2025.
- Nadri, R. et al. "On the Relationship between Developer's Perceptible Race/Ethnicity and Evaluation of Contributions in OSS." arXiv:2210.00139, 2022.

### Reproducibility

- "Do Repetitions Matter?" arXiv:2509.24086, 2025. [✓ verified]
- "Assessing Consistency and Reproducibility in LLM Outputs." Wang & Wang. arXiv:2503.16974, 2025. [✓ verified]
- LLM Stability. arXiv:2408.04667, 2024.

### Statistical Methods

- Agresti, A. and Coull, B. "Approximate is Better than 'Exact' for Interval Estimation of Binomial Proportions." The American Statistician, 1998.
- Takahashi, K. et al. "Confidence Intervals for the F1 Score." arXiv:2309.14621, 2022.
- Cohen, J. *Statistical Power Analysis for the Behavioral Sciences*, 1988.
- Dietterich, T. "Approximate Statistical Tests for Comparing Supervised Classification Learning Algorithms." 1998.

### Incident and Defect Data

- Dogga, P. et al. "AutoARTS: Taxonomy of Azure Incident Root Causes." USENIX ATC 2023.
- Bavota, G. et al. "When Does a Refactoring Induce Bugs?" SCAM 2012. [? unverified from primary source]
- Kim, M. et al. "An Empirical Study of Refactoring Challenges and Benefits at Microsoft." IEEE TSE, 2014.
- Bernardo, J.H. et al. "Do Code Review Measures Explain the Incidence of Post-Release Defects?" EMSE, 2020.
- "Towards Unmasking LGTM Smells in Code Reviews." ICSME 2024.

### Longitudinal and Productivity Studies

- METR. "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity." arXiv:2507.09089, July 2025.
- Anthropic. "AI Coding Assistance Reduces Developer Skill Mastery by 17%." InfoQ, Feb 2026.
- GitClear. "AI Code Quality Research 2025." gitclear.com.
- Macnamara et al. "Does Using AI Assistance Accelerate Skill Decay?" Cognitive Research, 2024.
- "Intuition to Evidence: Measuring AI's True Impact on Developer Productivity." arXiv:2509.19708.
- "Evolving with AI: A Longitudinal Analysis of Developer Logs." arXiv:2601.10258.

### Industry Reports

- Google DORA State of DevOps 2024 and 2025.
- Stack Overflow Developer Survey 2025. survey.stackoverflow.co/2025/ai/.
- Sonar State of Code Developer Survey 2026.
- Qodo State of AI Code Quality 2025.
- SmartBear / Cisco. "Best Kept Secrets of Peer Code Review." 2006 (industry white paper, not peer-reviewed).
- Capers Jones. Multiple publications on defect removal efficiency, 1996--2016.
- Boehm, B. and Turner, R. *Balancing Agility and Discipline*, 2003.

### Supply Chain Security

- "An Exploratory Study on GitHub Dependabot." arXiv:2206.07230.
- OSCAR. "Towards Robust Detection of OSS Supply Chain." ASE 2024.
- HERCULE. "Detecting Python Malware in the Software Supply Chain." ICSE 2025.

### IaC and Configuration

- iacsecurity/tool-compare (IaC scanner benchmark). github.com/iacsecurity/tool-compare.
- "Riskified LGTM 2.0: Architecting Zero-Noise AI Code Review Agents." Medium, Feb 2026.
- HubSpot. "Automated Code Review: The 6-Month Evolution." product.hubspot.com/blog, March 2026.

---

*Claims are tagged with verification status throughout. Where the source warrants scrutiny, the tag is explicit; untagged claims in context inherit the confidence of their source.*
