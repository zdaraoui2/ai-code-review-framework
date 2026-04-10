# Measuring AI Code Review Quality: A Framework and Initial Validation

**Version 1.0 — April 2026**

**Abstract, framework specification, and pilot implementation for Part 1 of a three-part research series on AI code review measurement.**

---

# Abstract

We present a measurement framework for evaluating the quality of AI-generated code review. The field lacks a standardised benchmark: a 2026 survey of 99 papers identifies the absence of a systematic evaluation landscape for review tasks [Khan et al. 2026], and the dominant benchmarks — c-CRAB, SWR-Bench, CodeAnt, and CRScore — use incompatible methodologies (test-based, LLM-as-judge, developer-action proxies, and reference-free scoring), making cross-tool comparison unreliable. Our framework specifies a 15-dimension taxonomy of review quality ranked by production-incident correlation, a 6-category change-type taxonomy with an explicit priority matrix, per-category precision, recall, and F1 with Wilson score confidence intervals, a three-category false positive adjudication protocol (CFP/PF/CNF), the first published sycophancy testing protocol for code review, a multi-model experiment protocol with a novel semantic deduplication method for cost-quality Pareto analysis, and a reproducibility protocol requiring at least three runs per configuration with ICC and bootstrap BCa intervals for F1. We validate the framework through an end-to-end pilot implementation covering the full pipeline from benchmark assembly to per-category reporting. To our knowledge, this is the first framework to require false positive measurement with equal rigour to recall, to specify sycophancy testing for code review, and to mandate a controlled multi-model ensemble comparison with semantic deduplication as part of the evaluation methodology.

---

# 1. Introduction

## 1.1 The review quality paradox

Code review does not primarily find bugs. Across four independent empirical studies spanning Microsoft, open-source projects, and academic codebases, approximately 75% of review comments concern code evolvability — readability, naming, structure, maintainability — rather than functional defects [Mantyla & Lassenius 2009; Beller et al. 2014]. Defect comments constitute only 14% of all review comments at Microsoft [Bacchelli & Bird 2013], and Czerwonka et al. found that only about 15% of review comments indicate a possible defect at all [Czerwonka et al. 2015]. The ratio replicates across industrial, open-source, and academic contexts within a 10-point range.

Yet the functional defects that escape review — logic errors, concurrency bugs, security vulnerabilities, error handling gaps, resource leaks — are precisely what cause production incidents. This is the review quality paradox: the dominant category of review activity is the category least correlated with production reliability. Any evaluation that reports aggregate metrics hides this paradox behind a single number. A tool that catches every style violation and no security bugs scores well on aggregate F1 and remains dangerous in production.

The paradox sharpens with the arrival of AI code review. AI reviewers are strongest at exactly what matters least — style consistency, naming conventions, documentation gaps — and weakest at exactly what matters most — cross-file reasoning, business logic validation, architectural coherence, and inter-procedural vulnerability detection. Any framework for measuring AI code review quality must therefore treat per-category evaluation as a primary requirement, not an optional refinement.

## 1.2 The measurement gap

AI code review tools are proliferating. CodeRabbit, Qodo, Augment Code, BitsAI-CR, Greptile, HubSpot Sidekick, and a long tail of vendor offerings now reach millions of repositories and tens of thousands of weekly active developers [Sun et al. 2025; Vijayvergiya et al. 2024]. But the field has no standardised way to evaluate them. A 2026 systematic survey of 99 papers by Khan et al. explicitly identifies the absence of a "systematic SDLC-aware benchmark landscape for review tasks" [Khan et al. 2026, arXiv:2602.13377]. The field has tools, but no ruler.

Existing benchmarks use mutually incompatible methodologies. c-CRAB converts human review comments into executable tests and measures pass rates [c-CRAB 2026]. SWR-Bench uses LLM-as-judge scoring over 2,000 annotated PRs [SWR-Bench 2025]. CodeAnt and related systems rely on developer-action proxies such as comment resolution and merge rates. CRScore evaluates comment quality without references, using open-source pseudo-reference generation and producing a 0.54 Spearman correlation with human judgement [Naik et al. 2025]. Each approach measures something worth measuring. None measures the same thing as the others, and results from one cannot be directly compared to results from another.

The empirical picture from these incompatible studies is bleak. The best single-pass LLM achieves an F1 of 19.38% on SWR-Bench [SWR-Bench 2025]. The union of four leading tools covers only 41.5% of human-identified issues on c-CRAB [c-CRAB 2026]. Pull requests reviewed exclusively by AI code review agents achieve a 45.20% merge rate versus 68.37% for human-reviewed PRs — a 23 percentage-point gap [Chowdhury et al. 2026, MSR]. These numbers describe a field that has not yet delivered reliable automation. But because each comes from a different methodology, they cannot be aggregated, compared, or used to adjudicate between vendor claims.

Reproducibility compounds the problem. A recent systematic study shows that 83% of single-run leaderboard results produce rank inversions when compared to three-run aggregates ["Do Repetitions Matter?" arXiv:2509.24086]. The community routinely draws conclusions from point estimates that would flip under resampling. The Khan et al. survey notes a decline in statistical validation practices in the LLM era, not an improvement.

## 1.3 What is missing

Five specific gaps sit between the current literature and a usable measurement framework.

**Per-category metrics.** No published study reports human or AI reviewer recall by defect category beyond security. The 75:25 evolvability-to-defect ratio means aggregate metrics are dominated by the easiest categories, masking systematic failure on the hardest ones.

**False positive measurement with equal rigour to recall.** Precision is the adoption bottleneck. SWR-Bench reports precision below 10% for many techniques. BitsAI-CR at ByteDance required a dedicated ReviewFilter stage because "advanced LLMs' raw outputs fail to meet the precision requirements for production deployment" [Sun et al. 2025]. Yet most benchmarks focus on recall and treat false positives as a secondary concern.

**Sycophancy measurement.** Sycophancy is well-documented in general LLM settings: Perez et al. show it increases with model size, with the largest models exceeding 90% on some tasks, and Sharma et al. demonstrate that RLHF does not fix the problem and may incentivise it [Perez et al. 2023; Sharma et al. 2024]. But no controlled experiment measures LGTM bias — the fraction of known-bad code an AI approves — in code review. No study measures critique sycophancy, where AI reviewers retract valid findings under developer pushback. The closest analogue is an academic peer review study showing LLMs "consistently give higher recommendation scores than human reviewers" [arXiv:2408.10365]. Sycophancy in code review remains unmeasured.

**A protocol for the novel finding rate.** Ground truth is incomplete. Human reviewers miss issues. When an AI flags something absent from the ground truth, it may be hallucinating — or catching something the original reviewers missed. No existing benchmark distinguishes these cases. Naive false positive rates therefore penalise exactly the AI behaviour that justifies adoption.

**Multi-model ensemble evaluation under controlled cost constraints.** Union of review tools covers 29% more issues than the best single tool [c-CRAB 2026]. Multi-review aggregation improves F1 by 43.67% on SWR-Bench. Different LLMs produce categorically different error types [ICSE 2025, arXiv:2406.08731]. The evidence for ensemble benefits is strong and converges across code generation, code repair, and code review. But no study has compared N different models (one pass each) versus one model (N passes) versus N models (N passes) on the same code review benchmark under controlled cost constraints. The cost-quality Pareto frontier for code review architectures has not been mapped.

## 1.4 Contribution

This paper presents a measurement framework that addresses all five gaps. The framework's full specification runs to over 5,000 lines; this paper summarises its structure and validates executability. The contribution comprises eight components.

First, a 15-dimension taxonomy of review quality, ranked by production-incident correlation and organised into three tiers. Tier 1 covers high-incident-correlation dimensions (correctness, concurrency, error handling, security, resource management). Tier 2 covers moderate-incident dimensions with high long-term impact (configuration correctness, API design, test quality, architecture, data validation). Tier 3 covers evolvability dimensions (maintainability, readability, documentation, style, performance). The ranking drives weighted scoring: a tool catching security vulnerabilities scores higher than one catching naming violations at equal raw recall.

Second, a 6-category change-type taxonomy (configuration changes, architectural refactoring, dependency updates, new features, bug fixes, simple refactoring) with an explicit change-type-to-dimension priority matrix. A configuration change requires different review focus than a simple refactoring, and the framework encodes this rather than leaving it implicit.

Third, per-category precision, recall, and F1 with Wilson score confidence intervals. The framework mandates category-level reporting as a precondition for publishable results.

Fourth, a sycophancy testing protocol with two sub-protocols: LGTM bias testing, which presents known-bad code and measures approval rate, and critique sycophancy testing, which presents valid findings and measures retraction rate under simulated developer pushback. To our knowledge, this is the first published sycophancy methodology specific to code review.

Fifth, a false positive adjudication protocol with three-category classification — Confirmed False Positive (CFP), Plausible Finding (PF), and Confirmed Novel Finding (CNF). Independent expert review with inter-rater reliability measurement distinguishes hallucinated findings from genuine discoveries, preventing ground truth incompleteness from inflating false positive rates.

Sixth, a multi-model experiment protocol. The framework specifies controlled comparisons between single-model single-pass, single-model multi-pass, and multi-model configurations, with cost normalisation (tokens and wall-clock time) alongside quality metrics, enabling the first systematic cost-quality Pareto analysis for code review architectures.

Seventh, a statistical protocol. At least three runs per configuration, ICC $\geq$ 0.60 for run-to-run consistency, Wilson score intervals for proportions, bootstrap BCa with 5,000 iterations for F1, Cliff's delta for ordinal comparisons, and Holm-Bonferroni or Benjamini-Hochberg correction for multiple comparisons. These requirements directly address the rank-inversion finding from "Do Repetitions Matter?" (arXiv:2509.24086) and the decline in statistical practice documented by Khan et al.

Eighth, a pilot implementation validating that the framework is executable end-to-end. The pilot covers fixture generation, benchmark assembly, review execution against Anthropic and OpenAI adapters, multi-judge panel scoring with majority vote, and per-category reporting.

## 1.5 Paper roadmap

Section 2 surveys related work: prior code review benchmarks (CodeReviewer, c-CRAB, SWR-Bench, SWE-PRBench, CRScore), human reviewer baseline studies (Bacchelli & Bird, Sadowski et al., Bosu et al., Kemerer & Paulk), AI reviewer evaluation studies (BitsAI-CR, Qodo, Chowdhury et al.), LLM-as-judge methodology and its known biases, and statistical methods for benchmarking LLMs. Section 3 presents the framework overview and refers readers to the full framework specification for implementation-level detail. Section 4 reports the validation pilot. Section 5 discusses limitations, novel contributions, and future work. Section 6 concludes.

---

# 2. Related Work

Measuring the quality of AI code review draws on five strands of research: empirical studies of human reviewer behaviour, systems that apply LLMs to review, evaluation benchmarks, LLM-as-judge methodology, and statistical practice for classifier comparison. We survey each in turn, then argue that no existing work combines their best practices.

## 2.1 Human Reviewer Studies

The empirical literature on human code review provides both the baseline any AI system should be measured against and the taxonomy against which findings should be classified. Bacchelli and Bird's Microsoft field study (ICSE 2013) established that only 14% of review comments are defect-related and 29% are code improvements, despite managers expecting reviews to catch bugs — review, in practice, is dominated by knowledge transfer and maintainability. Mantyla and Lassenius (IEEE TSE 2009) formalised this pattern as the canonical 75:25 evolvability-to-functional ratio after classifying 759 defects. Beller et al. (MSR 2014) replicated the ratio across three open-source projects, finding the split held within a 10-percentage-point band.

Sadowski et al. (ICSE-SEIP 2018) reported on nine million reviews at Google, observing median review latency under four hours and 97% developer satisfaction with the Critique tool, while also showing that the primary review motivation is readability. Bosu et al. (MSR 2015) analysed 1.5 million review comments at Microsoft and identified reviewer file experience as the strongest reviewer-related predictor of comment usefulness, with experienced reviewers producing useful comments at roughly twice the rate of first-timers (65–71% versus 32–37%). Kemerer and Paulk (IEEE TSE 2009) used PSP data to establish the empirical ceiling on sustained review effectiveness at roughly 200 LOC per hour. Paul et al. (ICSE 2021) conducted a case-control study on Chromium OS, finding 516 security defects caught versus 374 missed, and reported an AUC of 0.91 for their predictive classifier — the only published category-level recall data beyond general bug finding. No comparable category-level recall figures exist for non-security defect types.

## 2.2 AI Code Review Systems

A growing number of systems apply LLMs to review. CodeReviewer (Li et al., FSE 2022, arXiv:2203.09095) pre-trained a model on nine languages for three review tasks and remains the most widely cited academic baseline; its limitation is that subsequent quality audits found only approximately 64% of mined comments are valid ground truth. BitsAI-CR (Sun et al., FSE 2025, arXiv:2501.15134) deployed a two-stage RuleChecker plus ReviewFilter architecture at ByteDance, achieving 75% precision with 12,000 weekly active users; its authors explicitly note that raw LLM output fails to meet production precision requirements. Google's AutoCommenter (Vijayvergiya et al., AIware 2024) is a T5X-based system deployed to tens of thousands of developers. Commercial tools — Qodo, CodeRabbit, Augment, Cursor — report headline metrics (Qodo 2.0 F1 60.1%, CodeRabbit 46% bug detection accuracy) but these are vendor claims rather than independent evaluations.

The most rigorous independent assessment is Chowdhury et al.'s MSR 2026 study (arXiv:2604.03196), which found that 12 of 13 evaluated code review agents produced signal ratios below 60% and that PRs reviewed only by a code review agent had a 23-percentage-point lower merge rate than human-reviewed PRs. This is the clearest published evidence that current AI reviewers fall substantially short of human reviewers on real-world outcomes.

## 2.3 Evaluation Benchmarks

This subsection is the centre of the gap our framework addresses, because each existing benchmark measures something different and none produce numbers comparable to any other.

The original CodeReviewer dataset (Li et al. 2022) was mined from GitHub and lacks per-category analysis; its noise level (only ~64% valid comments) makes it unreliable as ground truth. c-CRAB (arXiv:2603.23448) converts 184 PRs into 234 executable tests in Python, reporting individual tool pass rates of 20–32% and a union coverage of 41.5%; its strength is determinism, its limitation that only testable issues can be evaluated, excluding style, design, and documentation comments. SWR-Bench (arXiv:2509.01494) provides 2,000 PRs (1,000 Change plus 1,000 Clean) with LLM-as-judge validation at approximately 90% human agreement, reporting a best single-pass F1 of 19.38% and demonstrating a 43.67% F1 improvement from multi-review aggregation; its strength is comprehensiveness, its limitation that the dataset could not be located at a permanent public URL at time of writing.

SWE-PRBench (arXiv:2603.26130) provides 350 PRs with contamination-aware repository selection and LLM-as-judge validation at Cohen's kappa = 0.75, reporting 15–31% issue detection across eight frontier models and showing that all models degrade monotonically as context expands; its strength is contamination mitigation, its limitation that ground truth is bounded by what human reviewers flagged. CodeReviewQA (arXiv:2503.16167) contains 900 manually verified examples retained after discarding 87% of source data, in a multiple-choice question-answering format; its strength is data quality, its limitation that it assesses review comprehension rather than review generation. The Martian Code Review Bench (2026) offers 50 curated PRs with developer-action proxies as ground truth; its strength is independent evaluation, its limitation is scale. CRScore (Naik et al., NAACL 2025, arXiv:2409.19801) is a reference-free quality metric rather than a dataset, reporting 0.54 Spearman correlation with human judgement across three quality dimensions.

The key observation is that these benchmarks measure incompatible things: test pass rate (c-CRAB), judge-scored F1 against human comments (SWR-Bench, SWE-PRBench), multiple-choice accuracy (CodeReviewQA), merge proxy (Martian), and reference-free quality (CRScore). No two produce comparable numbers. This incompatibility is the fundamental measurement gap that motivates a standardised framework.

## 2.4 LLM-as-Judge and Evaluation Methodology

Zheng et al. (arXiv:2306.05685) introduced the LLM-as-judge paradigm and reported that GPT-4 as judge achieves 85% agreement with human preferences in pairwise comparison, exceeding the 81% inter-human baseline. Subsequent work documented systematic biases that threaten the paradigm's validity. Perez et al. (ACL Findings 2023, arXiv:2212.09251) showed that sycophancy increases with model size, exceeding 90% at 52B parameters, and that RLHF does not mitigate it. Sharma et al. (ICLR 2024, arXiv:2310.13548) demonstrated that sycophancy is pervasive across five state-of-the-art assistants. Wataoka et al. (arXiv:2410.21819) found that self-preference bias in LLM-as-judge is driven by output perplexity rather than self-recognition, affecting all eight models tested. Shi et al. (AACL-IJCNLP 2025, arXiv:2406.07791) conducted the largest study of position bias to date, covering 15 judges and over 100,000 instances, and found that capable judges can approach repetition stability above 0.95 but that naive single-order evaluation is unreliable. A 2025 leniency bias study (arXiv:2510.11822) reported that 14 LLMs used as judges exhibit true positive rates above 96% but true negative rates below 25% — they are strong at recognising quality but poor at recognising its absence. Finally, a recent study (arXiv:2509.24086) found that 83% of single-run leaderboard results produce rank inversions when compared to three-run aggregates, establishing multiple runs as a statistical necessity rather than a nicety.

## 2.5 Statistical Methodology

Rigorous measurement of classifier performance requires appropriate confidence intervals, effect sizes, and power analyses. Agresti and Coull (1998) showed that Wilson score intervals outperform the Wald normal approximation for binomial proportions, particularly at small sample sizes or extreme values. Takahashi et al. (arXiv:2309.14621) derived analytical confidence intervals for the binary F1 score, filling a methodological gap for the most commonly reported composite metric. Dietterich (1998) formalised statistical tests for comparing classifier performance, including McNemar's test for paired comparisons on the same data — directly applicable to comparing AI reviewers on a shared benchmark. Cohen (1988) established the power-analytic foundation for sample size selection that the benchmark construction protocols require. Cliff's delta, a non-parametric effect size, is the appropriate measure for ordinal comparisons such as severity calibration, where Cohen's d is inappropriate due to non-normality.

## 2.6 Synthesis and the Gap

The framework presented in this paper synthesises best practices from each of these strands: test-based evaluation where issues are testable (following c-CRAB), contamination-aware repository selection (following SWE-PRBench), reference-free quality assessment for non-testable comments (following CRScore), multi-judge panels with explicit bias mitigations (following Zheng et al., Shi et al., Wataoka et al.), and rigorous statistical practice including Wilson score intervals, bootstrap BCa, and a minimum of three runs per configuration (following Agresti and Coull, Takahashi et al., Dietterich, and the rank-inversion evidence of arXiv:2509.24086). On top of this synthesis, the framework adds three contributions that no published work provides: systematic false positive adjudication as a first-class metric (CFP/PF/CNF with a feedback loop into ground truth), a sycophancy testing protocol for code review including LGTM bias, critique sycophancy, and severity softening, and a controlled multi-model experiment protocol with a novel semantic deduplication method for comparing ensemble configurations under cost constraints. Taken together, these contributions address the measurement incompatibility identified in Section 2.3 and produce numbers that can be directly compared across AI systems and across architectures.

---

# 3. Framework Overview

This section presents the framework's design principles, summarises its major components, and highlights three novel contributions: false positive adjudication, sycophancy testing, and the multi-model experiment protocol with semantic deduplication.

## 3.1 Design Principles

Four decisions shape every component.

**Publication-grade rigour as the only tier.** The framework specifies one tier: three runs per configuration minimum, confidence intervals on every point estimate, kappa on every classification task, and pre-registered power analysis. Benchmarks that offer a lightweight "quick" mode alongside a rigorous variant invariably see the quick mode become the default.

**Per-category evaluation as non-negotiable.** Aggregate precision, recall, and F1 hide the only variation that matters. A tool that catches 100% of style issues and 0% of security defects returns the same headline F1 as one that catches half of each, but only the latter is safe to deploy. Because evolvability findings dominate natural review volume at roughly 75% (Mantyla and Lassenius 2009; Beller et al. 2014), a tool can score well on aggregate recall while missing every Tier 1 defect. The framework therefore requires metrics per dimension, and permits aggregate numbers only alongside the per-dimension breakdown under a tier-weighted formula that counts Tier 1 at three times the weight of Tier 3.

**False positive measurement with equal rigour to recall.** Existing benchmarks either ignore false positives (c-CRAB, SWR-Bench) or treat all non-ground-truth findings as false positives (CodeAnt). The latter is wrong: an AI finding not in the ground truth could be a hallucination, a judgement call, or a genuine issue that human reviewers missed. The framework gives precision the same standing as recall, requires F2 reporting for all Tier 1 dimensions, and introduces an adjudication protocol that distinguishes hallucinations from novel discoveries before precision is computed.

**Sycophancy as a first-class dimension.** Sycophancy is well-documented in general LLM settings (Perez et al. 2023; Sharma et al. 2024; OpenAI's April 2025 post-mortem) but has never been operationalised for code review. A reviewer that silently approves bad code, retracts correct findings under pushback, or softens severity when the author looks senior is actively dangerous because it provides the illusion of review without the substance.

## 3.2 Review Dimensions Taxonomy

The framework classifies all code review findings into fifteen dimensions grouped into three tiers. Tier 1 covers the five dimensions with the strongest documented link to outages and breaches: Correctness, Concurrency, Error Handling, Security, and Resource Management. Tier 2 covers dimensions that cause failures at integration boundaries or impose long-term costs: Configuration, API Design and Contracts, Test Quality, Architecture and Design, and Data Validation. Tier 3 covers code-health dimensions that dominate review volume but have low direct incident correlation: Maintainability, Readability and Naming, Documentation, Style and Formatting, and Performance.

The tier ranking is a synthesis judgement, not a statistically measured ordering. It draws on three inputs: published incident data (Azure AutoARTS, ThousandEyes cloud-service-provider outage reports, CrowdStrike-style post-mortems); defect severity when the issue escapes to production; and catch-rate difficulty, meaning how likely the defect is to be caught by linters, tests, or monitoring if review misses it. Style violations rank at the bottom of Tier 3 because formatters catch them trivially; concurrency bugs rank in Tier 1 because they are hard to reproduce in testing and review is often the last reliable defence. The framework states this synthesis explicitly so the ranking can be revised as new incident data becomes available.

Each dimension carries explicit Includes and Excludes lists and precedence rules for common overlaps: a missing input check with a security consequence classifies as Security rather than Data Validation; a bug that manifests only under concurrent execution classifies as Concurrency rather than Correctness. The framework targets kappa of at least 0.70 on dimension classification (substantial agreement on the Landis and Koch scale), revising definitions and re-calibrating if calibration samples fall below.

## 3.3 Change Type Taxonomy

The framework defines six change types with distinct risk profiles: Configuration, Architectural Refactoring, Dependency Updates, New Features, Bug Fixes, and Simple Refactoring. Every PR is tagged with one primary type and all results are reported per type. Configuration carries the highest risk rating: the cloud-service-provider outage share from configuration errors grew from 11% in 2022 to 27% in 2024 (ThousandEyes 2024), and incidents including CrowdStrike, Azure Front Door, and Facebook's October 2021 outage were configuration-originated. Dependency updates rank as high-risk by analogy with Log4Shell and the continuing stream of malicious packages on npm and PyPI.

A change-type-to-dimension priority matrix assigns each combination a priority of Critical, High, Moderate, or Low, which become scoring weights: Critical findings count at three times Moderate, High at twice, and Low-priority dimensions are excluded from the per-category score entirely. For a bug fix, Correctness and Test Quality are Critical. A tool that catches only style issues on a bug fix therefore receives zero credit for that PR, preventing the inflated score that aggregate recall would assign.

## 3.4 Metrics

Core detection metrics are precision, recall, and F-scores, reported per dimension with Wilson or bootstrap BCa confidence intervals. F1 is the default; F2 is required for every Tier 1 dimension because missing a critical defect is catastrophic while extra false positives are tolerable. Quality metrics include severity calibration (Spearman rho between AI and ground-truth severity), actionability (the fraction of comments concrete enough for a developer to implement a fix without clarification), and CRScore (Naik et al. 2025) for reference-free scoring; CRScore is permitted for automated screening but not for published results because its 0.54 Spearman correlation with human judgement explains only about 29% of the variance. Cost metrics record tokens per review, wall-clock latency, and cost per valid finding, the last being the key cost-effectiveness number. Sycophancy metrics form the fourth group: the LGTM Bias Rate, Partial LGTM Score, Critique Sycophancy Rate, and Severity Softening Index, produced by the protocols in Section 3.6.

## 3.5 False Positive Adjudication Protocol

This is the first novel contribution. Every published code-review benchmark either ignores false positives (c-CRAB, SWR-Bench) or treats all non-ground-truth findings as false positives (CodeAnt). The latter is wrong because an AI finding not in the ground truth could be a hallucination, an ambiguous judgement call, or a genuine issue the original reviewers missed. Treating all three identically penalises tools that are more thorough than their human predecessors.

The framework resolves this with a three-judge adjudication panel drawn from different model families, excluding the family of the model under evaluation. Each judge independently classifies the finding as Confirmed False Positive (the code is correct with respect to the claimed issue), Plausible Finding (a legitimate concern on which reasonable experts would disagree), or Confirmed Novel Finding (a genuine issue missed by human reviewers). Majority vote determines the classification; a three-way split defaults to Plausible. The framework targets Fleiss's kappa of at least 0.60 on the rubric, calibrated against a fifty-finding set before any tool is evaluated.

The precision formula changes accordingly. Confirmed Novel Findings count as true positives, Confirmed False Positives as false positives, and Plausible Findings are excluded and reported separately. Reports must show both standard and adjusted precision, because the gap between them quantifies ground-truth incompleteness directly. A feedback loop closes the protocol: novel findings are added back to the ground truth with a provenance tag and a version bump, and previously evaluated tools are retroactively scored against the updated set. Each round potentially enriches the benchmark.

## 3.6 Sycophancy Testing Protocol

This is the second novel contribution. The framework defines three protocols that produce quantitative, reproducible measurements of behaviours no published code-review benchmark measures.

The LGTM Bias Protocol presents the reviewer with adversarial code diffs containing one seeded defect, under the same interface and prompt used for normal reviews; the reviewer is not told a defect has been planted. The LGTM Bias Rate is the fraction of Easy-difficulty cases where the reviewer produces no findings or approves the code. The denominator is restricted to the Easy-difficulty subset, empirically calibrated so that competent human reviewers catch the defect at least 90% of the time. This restriction distinguishes sycophancy from detection failure: if humans reliably catch a defect and the AI does not, the most parsimonious explanation is bias toward approval, not inability. The Partial LGTM Score adds a severity-weighted companion metric that rewards finding some seeded issues over finding none.

Difficulty calibration requires a ten-panellist human panel, not three. The justification is mathematical: with three panellists, the only representable catch rates are zero, one-third, two-thirds, and 100%, so the 90% boundary cannot be distinguished from 100%. With ten panellists, achievable rates run in 10% increments, giving sufficient resolution to assign cases to Easy (nine or ten of ten), Medium (five to eight), Hard (two to four), and Exclude (below two). Cases within one reviewer of a boundary are expanded to fifteen panellists. Difficulty is an empirical property of reviewer behaviour, not a design parameter.

The Critique Sycophancy Protocol challenges correct findings with plausible but incorrect counter-arguments drawn from four categories: Authority Appeal, Technical Misdirection, Dismissal, and Partial Acknowledgement. The reviewer's response is classified as Maintained, Softened, or Abandoned, with the rate defined as the fraction of challenges producing Softened or Abandoned outcomes. The Severity Softening Protocol is a paired-condition experiment in which the same seeded defect is presented under neutral framing (anonymous author, factual description) and biased framing (senior author, confident description, prior approving comment). The Severity Softening Index is the difference between the Spearman correlations of AI severity with ground-truth severity under the two conditions, with case order counterbalanced to control for sequence effects.

## 3.7 LLM-as-Judge Protocol

Automated quality assessment uses a panel of three LLM judges from different model families. The family exclusion rule is absolute: no panel may contain the family under evaluation, because self-preference bias driven by output perplexity is measurable in every model studied (Wataoka et al. 2024). Binary decisions aggregate by majority vote, ordinal by median, and categorical by majority with documented defaults. Per-judge results are always reported alongside aggregates to detect residual self-preference.

Six bias mitigations are applied in concert. Position bias, which can shift pairwise accuracy by more than 10% (Shi et al. 2025), is controlled by dual-order presentation with a consistency rate of at least 0.85. Verbosity bias is controlled by structured rubrics that do not reward length. Self-preference is controlled by the family exclusion rule and metadata stripping. Leniency bias (true-negative rates below 25% in recent judge studies) is controlled by a minority-veto rule and known-invalid findings in the calibration set. Framing bias is controlled by neutral prompt phrasing tested in both directions. Anchoring bias is controlled by validating reference quality before use, with fallback to reference-free evaluation.

The judge system is validated on 50 to 100 human-judged examples with a 30% hard-case quota, targeting kappa of at least 0.70 (0.60 minimum floor). The calibration set is re-run every 500 items or after any model-version update to detect drift, and the framework specifies explicit halt conditions for kappa drop, position consistency drop, or true-negative rate collapse on known-bad examples.

## 3.8 Benchmark Assembly

The evaluation corpus has three components, evaluated independently because detection capability and sycophancy are orthogonal properties: a standard evaluation set of 350 to 500 real pull requests for detection metrics, an adversarial sycophancy set of 260 to 730 constructed cases for the LGTM Bias Rate, Partial LGTM Score, and Severity Softening Index, and a critique challenge set of 50 to 100 challenge-response sequences for the Critique Sycophancy Rate.

Category-balanced sampling is required because the natural 75/25 evolvability-to-functional distribution does not support per-dimension statistical power. The framework specifies minimums of 50 ground-truth issues per Tier 1 dimension, 30 per Tier 2, and 20 per Tier 3, derived from Wilson score interval widths at representative proportions. Ground truth uses two complementary methods: test-based (following c-CRAB, wherever the issue can be expressed as a containerised test that fails on the original code and passes on the fix) and expert curation by two independent annotators with a third breaking ties, targeting kappa of at least 0.70. Contamination mitigation operates on four layers: temporal preference for post-2024 data, repository obscurity scoring adapted from SWE-PRBench's Repository Quality Score, canary detection using 10 to 20 trivially-easy PRs known to be absent from training corpora, and a post-cutoff temporal holdout of 10 to 15% of the benchmark.

## 3.9 Statistical Protocol

Every point estimate must be reported with a 95% confidence interval. Wilson score intervals are used for precision and recall because they are asymmetric, respect the [0,1] boundary, and provide near-nominal coverage from samples as small as ten (Agresti and Coull 1998; Brown, Cai, and DasGupta 2001). The Wald interval is explicitly banned. F1 uses bootstrap BCa with 5,000 iterations as the default, because F1 is the harmonic mean of two dependent proportions and closed-form intervals are unreliable without large-sample assumptions. Effect sizes accompany every p-value: Cliff's delta for ordinal data, Cohen's d only when normality is verified. Paired tool comparisons use McNemar's test on discordant pairs. Multiple comparisons are corrected with Holm-Bonferroni for two or three tools (uniformly more powerful than plain Bonferroni) and Benjamini-Hochberg for five or more.

Reproducibility requires a minimum of three runs per configuration, a direct consequence of the finding that 83% of single-run leaderboard results produce rank inversions against three-run aggregates (arXiv:2509.24086). Intraclass correlation at 0.60 or higher is required as evidence of consistency, and power analysis is pre-registered: a publishable benchmark needs at least 200 PRs to detect a 10 percentage point difference in recall at 80% power.

## 3.10 Multi-Model Experiment Protocol

This is the third novel contribution. Evidence from adjacent domains suggests multi-model ensembles should improve code review quality: c-CRAB showed union recall of 41.5% against 32.1% for the best single tool; SWR-Bench demonstrated multi-review aggregation improving F1 by up to 43.67%; ICSE 2025 findings indicate different LLMs make categorically different errors. But no controlled experiment has compared aggregation strategies, measured the cost-quality trade-off, or identified the point of diminishing returns.

The protocol defines nine experimental conditions: a single-model baseline, self-aggregation at three and five samples, three-model and five-model configurations, four aggregation-strategy variants for the three-model case, and a cascade in which a cheap model routes uncertain cases to an expensive model. All conditions share the same benchmark, prompt, judge panel, and run count. Model selection prioritises error profile diversity over raw performance: an ensemble of three models that make the same mistakes provides no more coverage than one. Selection criteria mandate cross-family diversity, architecture diversity, and pairwise Jaccard similarity minimisation on a calibration run.

The five aggregation strategies are union (all findings after deduplication), majority vote, LLM-as-arbiter (a fourth model curates the combined pool), diversity-based selection (prioritising findings caught by only one model), and cascade. Each is applied to the same raw review outputs so differences are attributable to the strategy alone. Majority vote is included primarily to quantify the "popularity trap": Vallecillos-Ruiz et al. showed that consensus-based selection performs worse than naive baselines for code tasks because models produce syntactically similar but semantically incorrect solutions, filtering out the most valuable findings.

The experiment also introduces a two-stage semantic deduplication protocol, itself a novel contribution. Stage 1 is deterministic: findings are grouped by code location, requiring at least 50% line-range overlap within the same file. Stage 2 is semantic: an LLM judge determines whether pairs of comments within a location group describe the same underlying issue, with explicit rules for what counts as the same issue (fixing one would fix the other) versus different (different problem types on the same line). Deduplication is validated on a 100-pair calibration set targeting kappa of at least 0.70, and false merge and false split rates are reported separately because they have opposite effects on precision and recall. Cost recording is per-call, and cost parity comparisons use 20% tolerance bands so a 10% F1 improvement at five times the cost is not confused with the same improvement at 1.2 times the cost.

---

# 4. Validation

This section demonstrates that the framework is implementable. It is not
an empirical benchmark of any AI reviewer — a full 500-PR benchmark with
real APIs, human-annotated ground truth, and multiple independent runs is
the subject of Part 2. What we show here is that the specification holds
up when an engineer sits down to build it.

## 4.1 Pilot design

The pilot constructs the end-to-end measurement pipeline described by
the framework specification, runs it on a small hand-crafted fixture,
and records protocol issues that only surface during implementation.
Catching such issues on a 10-PR sample is cheap; catching them after
a 500-PR annotation effort is not.

**In scope.** The pilot covers the full data path from PRs through
to the final report: loading pull requests, invoking a reviewer,
invoking a judge panel, semantic matching between findings and
ground truth, per-dimension metrics with Wilson confidence intervals,
and the S9.7 reporting template. Both mock and real (Anthropic,
OpenAI) adapters are implemented, with the real adapters unit-tested
via injected HTTP client mocks so that code paths are exercised
without incurring API costs. A multi-judge panel with majority-vote
aggregation per S8.1 is also implemented and tested.

**Out of scope.** Five parts of the framework are deferred. Real API
runs wait until Part 2, which requires a curated benchmark and a
funded budget. Sycophancy testing (S6) depends on human-calibrated
adversarial fixtures. The multi-model experiment (S10) presupposes a
working single-model pipeline. False positive adjudication (S4.3)
is stubbed — the pilot tracks unmatched findings but does not run
the CFP/PF/CNF classification, which requires the full judge panel
on real outputs. Finally, the pilot runs the pipeline once rather
than the three-plus independent runs required by S9.6.

## 4.2 Implementation

The pilot is a 1,877-line Python package organised by framework concern.
Every module maps to one or more framework sections, as shown in Table 1.

| Framework section | Pilot module | Lines |
|---|---|---|
| S2 taxonomy, S3 change types, S4.2.1 severity | `schemas.py` | 237 |
| S4.1 core metrics, S9.1 Wilson CIs | `metrics.py` | 259 |
| S4.3 FP adjudication (stubbed) | `matching.py` | 69 |
| S8 reviewer and judge interfaces | `reviewer.py`, `judge.py` | 189 |
| S8.1 judge panel, majority vote | `panel.py` | 130 |
| S8.3.1 issue-match, real API adapters | `api_adapters.py` | 372 |
| S8.5 prompt templates | `prompts.py` | 165 |
| S9.7 reporting template | `reporting.py` | 124 |
| CLI orchestration | `run.py` | 257 |
| Data loading | `data.py` | 72 |

Three implementation choices are worth highlighting.

Wilson score confidence intervals are implemented from scratch,
including the inverse normal CDF via Beasley-Springer-Moro. The
framework requires Wilson intervals throughout (S9.1.1), but adding
a scipy dependency for `scipy.stats.norm.ppf` alone pulls in a large
numeric stack. A standalone routine is sufficient and is unit-tested
against boundary cases (0/n, n/n, 0/0, 50% at small n, 50% at n=1000)
covering both the asymmetry and width-with-sample-size behaviour.

The real API adapters take their HTTP clients as constructor
arguments rather than instantiating them internally. This dependency
injection pattern means every code path — prompt building, response
parsing, error handling, usage accounting — can be exercised in unit
tests with a mocked client, without requiring API keys to validate
that the adapter handles malformed JSON, missing fields,
markdown-wrapped responses, or upstream errors. Eighteen of the
fifty pilot tests exercise the real adapters with injected mocks.

The `Reviewer` and `Judge` classes are abstract interfaces, and a
multi-judge panel is itself a `Judge`, so any code that accepts a
single judge transparently accepts a panel. Adding a model provider
means implementing one class and registering it in the CLI
dispatcher; neither the metrics nor the reporting code is touched.
The work stayed strictly additive when the real adapters were wired
up on top of the mock-mode pipeline.

## 4.3 Sample fixtures

The evaluation fixture is 10 hand-crafted pull requests spanning six
language contexts (Python, JavaScript, Go, TypeScript, Rust, YAML) and
all six change types from Section 3 (new feature, bug fix, simple
refactoring, architectural refactoring, dependency update, configuration
change). It contains 18 ground truth issues across 10 of the 15 review
dimensions. Each issue carries a dimension, severity, file and
line-range location, a concrete description, and an optional difficulty
tag for future sycophancy calibration.

Five dimensions — api_design, architecture, documentation, maintainability,
style — have no ground truth coverage in the fixture. This is deliberate.
A 10-PR fixture is not large enough to populate all 15 dimensions at
meaningful sample sizes, and fabricating issues to force coverage would
produce an unrealistic distribution. The framework's own sample-size
requirements (S7.3.3) imply that full coverage only becomes possible at
the scale of hundreds of annotated PRs. The pilot fixture is a test
harness, not a benchmark.

The mock reviewer fixture is calibrated to produce a mixed outcome:
some ground truth issues are correctly flagged, some are missed, and
some findings are raised against issues not in the ground truth. The
mock judge fixture records the canonical match between findings and
ground truth. Together they exercise the metric computation on
realistic — not trivially all-zero or all-one — inputs.

## 4.4 Pilot results

All 50 unit tests pass. The end-to-end pipeline runs on the 10-PR fixture
in under a second on a laptop (no API calls, all computation local). The
aggregate metrics from the mock run are shown in Table 2.

| Metric | Value | 95% Wilson CI |
|---|---|---|
| Precision | 66.7% | [39.1%, 86.2%] |
| Recall | 44.4% | [24.6%, 66.3%] |
| F1 | 53.3% | — |
| True positives | 8 | — |
| False positives | 4 | — |
| False negatives | 10 | — |

The tier breakdown shows how the mock findings are distributed across
the three dimension tiers:

| Tier | Ground truth | TP | FP | FN |
|---|---|---|---|---|
| Tier 1 (correctness, concurrency, error handling, security, resources) | 11 | 6 | 1 | 5 |
| Tier 2 (configuration, API design, tests, architecture, validation) | 5 | 1 | 0 | 4 |
| Tier 3 (maintainability, readability, docs, style, performance) | 2 | 1 | 3 | 1 |

These numbers are designed into the fixture. They do not say anything
about real AI reviewer quality. What they demonstrate is that the
pipeline computes what the framework specifies: each ground truth
issue is attributed to the correct dimension, each unmatched finding
is counted as a false positive against its claimed dimension, and the
Wilson intervals are correctly wide at these sample sizes —
[39.1%, 86.2%] for precision at n=12 and [24.6%, 66.3%] for recall at
n=18, consistent with standard Wilson behaviour for small samples.

## 4.5 Framework gaps identified

The most valuable output of the pilot was not the metrics. It was the
four framework issues that only became visible once we tried to
implement the specification.

**Gap 1: dimension classification accuracy is not a defined metric.**
The pilot fixture contains a concrete case of this problem. Reviewer
finding F012 is raised against the unbounded-cache PR with claimed
dimension `correctness`, but the ground truth issue it identifies,
GT010, is labelled `concurrency` — the race condition on the
module-level cache dictionary. The judge successfully matches F012 to
GT010, and the pilot attributes the true positive to `concurrency`.
The reviewer gets recall credit for finding the issue, but the
framework never penalises it for misclassifying what kind of issue
it is. A reviewer that labels every finding as `style` would achieve
the same recall as one that labels them correctly, as long as the
semantic match still succeeds. The recommended fix is to add a
"dimension classification accuracy" metric to Section 4: the fraction
of matched findings where the reviewer's claimed dimension equals the
ground truth's dimension, reported alongside precision and recall.

**Gap 2: pre-benchmark judge calibration should be an explicit
prerequisite.** The framework requires judge validation against
human-judged examples (S8.6), but the chicken-and-egg character of
this requirement is not called out: the judge bootstraps the
benchmark, yet the benchmark is needed to validate the judge. The
pilot could not catch this because the mock judge is perfect by
construction. In a real run, the judge's decisions are the primary
input to every downstream metric, and an uncalibrated judge silently
contaminates every number in the report. The recommended fix is for
S8.6 to specify a pre-benchmark calibration step with an explicit
50-100 finding-GT pair dataset, a minimum inter-rater agreement
(kappa ≥ 0.70) against human labels, and the requirement that
calibration must pass before the benchmark runs.

**Gap 3: dimensions with insufficient coverage are silently absent
from the report.** The pilot report correctly shows null precision,
recall, and F1 for dimensions with zero ground truth issues. But the
report is silent about what this means: it does not warn that the
tool's performance on those dimensions has not been evaluated at
all. A reader scanning the table might mistake the dash for "no
issues found" rather than "no data". The recommended fix is twofold:
the report should include an explicit insufficient-data warning for
every dimension whose ground truth count falls below the S7.3.3
threshold, and the framework text should require this warning rather
than leaving it to implementers.

**Gap 4: the reporting template conflates ground truth count with
flagged count.** The S9.7 template uses a single column `n` for each
dimension, which the pilot report populates with ground truth size.
But false positives are counted independently and are not a subset
of `n`. Tier 3 in the pilot report shows `n=2` and `FP=3`, and at
first reading it is confusing because `TP + FP + FN ≠ n`. The
recommended fix is to split the column into `n_gt` (ground truth
count) and `n_flagged` (total findings the reviewer claimed in this
dimension).

None of these gaps are fatal, and all four are straightforward to
address in a framework revision. But all four would have propagated
into Part 2 had they not been caught, and at least two (gaps 1 and 2)
would have silently biased the published results. That is the value
the pilot delivered.

## 4.6 What the pilot validates and what it does not

The pilot validates four claims. The framework is internally
consistent: metrics can be computed, the judge protocol can be
implemented, the reporting template can be generated, and no section
contradicts another once a review-and-fix pass is applied. The
abstractions are at the right level: adding a reviewer or judge is
an additive change to a single adapter class. The statistical
methods behave correctly at small sample sizes — Wilson intervals
are wide where they should be wide, and collapse correctly at
boundary cases. And four concrete framework gaps were caught that
would have propagated to Part 2 had the pilot not existed.

The pilot does not validate real-world AI reviewer performance (no
real reviewer was invoked on real code), sycophancy resistance (the
protocol is deferred), multi-model ensemble effects, or
generalisation beyond the six language contexts in the fixture. It
does not validate the annotation cost estimates in Section 7, because
no real annotation happened. And it does not validate the judge
itself, because the mock judge is perfect by construction — judge
validation is itself one of the gaps identified above.

These are non-goals. The pilot's contribution is to demonstrate that
the framework is an engineering specification, not a research
manifesto: it can be implemented in under 2,000 lines of Python, it
produces the reports the framework asks for, and the places where it
does not quite work are now documented and actionable. Subsequent
empirical work will start from a revised framework and a pipeline
that has already been stress-tested.

---

# 5. Discussion

## 5.1 Comparison to Prior Work

Existing benchmarks are valuable but incompatible. This section positions the framework against each of the major prior efforts.

**Versus c-CRAB (Python-only, 184 PRs, test-based).** c-CRAB's contribution is a deterministic ground truth methodology: reviewer comments are converted to executable tests. The framework retains test-based ground truth as the gold standard for testable issues (S7.4). It adds per-category analysis across 15 dimensions, a false positive adjudication protocol for findings outside the test set, a sycophancy testing protocol (c-CRAB measures recall, not approval bias), and a multi-model experiment protocol. c-CRAB is limited to Python and to issues expressible as tests; the framework accommodates any language and extends ground truth to non-testable dimensions via expert curation.

**Versus SWR-Bench (2,000 PRs, multi-language, LLM-as-judge).** SWR-Bench demonstrated that multi-review aggregation improves F1 by up to 43.67% over single-pass review, and its scale remains the largest manually verified set in the literature. The framework adopts SWR-Bench's LLM-as-judge approach but adds a structured judge protocol with explicit bias mitigations (S8.2), a per-dimension reporting requirement, and sycophancy testing. It also addresses a practical concern: SWR-Bench's dataset cannot currently be located at any permanent public URL. The framework is dataset-agnostic -- the methodology applies to any corpus meeting the composition requirements in Section 7.

**Versus SWE-PRBench (350 PRs, contamination-aware).** SWE-PRBench's contribution is its Repository Quality Score with contamination penalty and its empirical demonstration that all eight frontier models degrade monotonically as context expands. The framework adopts SWE-PRBench's contamination mitigation (S7.6) and adds per-dimension requirements, false positive adjudication, sycophancy measurement and the multi-model protocol. SWE-PRBench's difficulty classification is complementary to the 15-dimension taxonomy and the two can be reported together.

**Versus CRScore (reference-free evaluation).** CRScore provides a reference-free metric for comment quality, achieving 0.54 Spearman correlation with human judgement at the instance level and 0.95 at the system level. The framework treats CRScore as a supplementary metric (S4.2.3). On its own, CRScore cannot distinguish hallucinations from genuine findings, cannot measure sycophancy and cannot detect dimension misclassification. The framework provides the scaffold that makes CRScore results comparable across tools and dimensions.

**Versus large-scale developer-action studies (e.g., CodeAnt 200K PRs).** Industry studies that use developer action (merge, address, dismiss) as a proxy for review quality face a fundamental confound: developer action conflates review quality with developer willingness to act. A correct finding the developer ignores counts as a failure; an incorrect finding the developer accepts counts as a success. The framework replaces the developer-action proxy with direct ground truth measurement and notes explicitly that recall relative to ground truth is a different quantity from recall relative to accepted findings.

## 5.2 Novel Contributions

Three contributions are novel to this framework. Each is specified in enough detail to be implemented, and each fills a gap documented in Section 8 of the literature review.

**1. False Positive Adjudication Protocol (S4.3).** Standard evaluation treats every finding outside the ground truth as a false positive. This is wrong. Ground truth is never complete, and an AI that catches a genuine issue the humans missed should be rewarded, not penalised. The framework specifies a three-category classification for non-ground-truth findings: Confirmed False Positive (hallucination), Plausible Finding (genuine ambiguity or judge disagreement), and Confirmed Novel Finding (a genuine issue the original reviewers missed). An independent three-judge panel performs the classification, with Fleiss's kappa reported for inter-rater agreement and a calibration step that iterates the rubric until kappa reaches 0.60. Confirmed Novel Findings flow back into the ground truth for subsequent runs, creating a feedback loop that improves benchmark completeness over time. No prior benchmark implements this distinction, and its absence systematically penalises the tools most worth evaluating.

**2. Sycophancy Testing Protocol (S6).** This is the first published methodology for measuring sycophancy in code review. The phenomenon is well-documented in general LLM settings -- Perez et al. report >90% sycophancy at 52B parameters; Sharma et al. show humans and preference models prefer convincingly written sycophantic responses over correct ones -- but no prior code review benchmark measures it. The framework defines three sub-protocols: LGTM bias testing (known-bad code, measured by approval rate), critique sycophancy testing (valid findings, measured by retraction rate under developer pushback), and severity softening (measured against a control condition). The load-bearing insight is difficulty calibration: only misses on Easy-difficulty adversarial cases -- defects with a human catch rate of 90% or higher on a ten-panellist calibration -- count toward the sycophancy rate. Ten is the smallest panel that gives sufficient resolution at the 90% boundary. Without this calibration, sycophancy cannot be distinguished from genuine inability.

**3. Multi-Model Experiment Protocol with Semantic Deduplication (S10).** The evidence that ensembles help is strong: c-CRAB shows 41.5% union recall across four tools versus 32.1% for the best single tool; SWR-Bench shows +43.67% F1 with multi-review aggregation; SWT-Bench shows ideal ensembles solve 71% more samples than the best single method; Vallecillos-Ruiz et al. show disagreement-based strategies realise up to 95% of the theoretical ensemble upper bound while majority voting falls into the "popularity trap". But no published paper has run a controlled comparison of aggregation strategies for code review. The framework specifies nine experimental conditions covering single-best, self-aggregation (N=3, N=5), multi-model with LLM aggregation (three and five models), multi-model variants (majority vote, union, diversity-based), and cascade. Conditions C6--C8 share the same raw model outputs as C4 and differ only in aggregation strategy, isolating aggregation effects from stochastic variation. The framework also specifies a two-stage semantic deduplication protocol (code-location grouping followed by LLM-judge semantic matching) because review findings are natural language, not discrete labels, and no prior work specifies how to merge semantically equivalent findings across models.

## 5.3 Limitations

**No empirical results yet.** This is a methodology paper. The framework is specified and demonstrated to be implementable end-to-end, but it has not been applied to a full benchmark run at the required scale. Empirical results are Part 2 of this research series.

**Pilot uses mock data.** The 10-PR sample is too small to draw any conclusions about AI reviewer quality. It is a test harness for the framework's code. The 66.7% precision and 44.4% recall figures from the pilot should not be cited as results -- they validate the pipeline is wired correctly.

**Human annotation cost.** Building a 500-PR benchmark at the framework's rigour standard requires approximately 2,000 to 4,000 annotator-hours, roughly one to two FTE-years. Most research teams cannot commit to this scale without institutional support. The modular design (Section 5.5) partly mitigates this by allowing smaller dimension-specific benchmarks, but the full measurement matrix requires the full annotation budget.

**Sycophancy protocol requires domain expertise.** Adversarial test case construction and difficulty calibration assume access to senior reviewers. Calibration requires ten panellists per case -- the smallest panel that can resolve the 90% difficulty boundary -- which is a substantial up-front cost before any AI review is conducted. Without this calibration, the sycophancy metric cannot distinguish inability from bias, so the protocol is not usable below this threshold of effort.

**Judge validation and drift.** The framework specifies judge validation against 50--100 human-judged examples (S8.6) with a kappa threshold of 0.70, but curating those examples is itself a significant task. Judge drift over time (S8.6.5) is flagged without a complete long-term solution. A benchmark running continuously over many months will need a re-validation cadence the current framework does not fully specify.

**Language and domain coverage.** The pilot fixtures cover six languages, but the framework does not specify how dimensional ranking or difficulty calibration should vary across them. Memory safety in C and type safety in TypeScript are different kinds of correctness issues, and a category-level benchmark that treats them uniformly will conflate language-specific strengths with general capability. Configuration and Infrastructure-as-Code review is another blind spot: the framework references it as a dimension but does not yet provide tailored rubrics or adversarial cases.

## 5.4 Broader Implications

**The review quality paradox is measurable.** Across four independent studies (Mantyla & Lassenius, Bacchelli & Bird, Beller et al., Sadowski et al.), 75% of review activity concerns evolvability rather than functional defects, yet deployment decisions for AI code reviewers are typically justified on defect-detection grounds. The framework does not resolve this paradox -- that is a normative question -- but it makes it measurable. Per-dimension reporting reveals where a tool is strong and weak, so organisations can make informed trade-offs rather than relying on an aggregate score that hides the tension.

**Precision is the bottleneck, not recall.** Evidence converges from multiple sources: SWR-Bench reports techniques with precision below 10%; BitsAI-CR required a dedicated ReviewFilter stage to bring precision to deployable levels; Chowdhury et al. (MSR 2026) found 12 of 13 code review agents had signal ratios below 60%; Qodo's data show developers experiencing fewer false positives are 2.5 times more likely to merge without reviewing AI suggestions. Yet most benchmarks focus on recall. Measuring false positives with the same rigour as false negatives is essential, because a tool with high recall and low precision actively degrades the review process by training developers to ignore its output.

**Multi-model ensembles likely dominate single-model reviews, but configuration matters.** The Vallecillos-Ruiz et al. finding on the popularity trap is a warning: naive majority voting can underperform single-model baselines because models frequently produce syntactically similar but semantically incorrect outputs. The framework's Multi-3 variants are designed to find the aggregation strategy that actually captures the inter-model diversity benefit, not merely to demonstrate that ensembles exist.

## 5.5 Future Work

The research series comprises three papers. Part 1 is the framework. Two further papers are planned.

**Part 2: Where can AI replace humans?** Apply the framework to measure AI reviewer performance across the 15 dimensions and six change types, and produce the decision matrix -- which categories are ready for AI, which require human review, which are best served by human-AI collaboration.

**Part 3: Can we remove humans?** A gap analysis and failure mode assessment: given the measurements from Part 2, what would need to be true for AI to fully replace human review in each category, and what are the realistic paths to closing those gaps.

Four extensions sit within Part 1's scope and are planned as follow-on work:

- **Modular self-service framework.** A lightweight version that organisations can apply to specific dimensions without committing to the full 500-PR benchmark. This is an adoption play rather than a research contribution, but it addresses the annotation cost barrier.
- **Continuous evaluation.** A living leaderboard that re-runs the benchmark as new models ship. The framework's version-pinning requirements (S10.3.5) and reproducibility protocol (S9.6) are designed to make this feasible.
- **Domain-specific extensions.** Infrastructure-as-Code and configuration review, dependency review, and regulated-industry extensions. Each is a measurable dimension in the current framework but lacks tailored adversarial cases and rubrics.
- **Human baseline collection.** Running the same benchmark on human reviewers to produce the first published category-level human baseline data. Section 3.5 of the literature review identifies this as a genuine novel contribution opportunity -- no published study provides recall rates by defect category (beyond security) or by change type. The framework is directly applicable to human reviewers with minimal adaptation.

---

# 6. Conclusion

AI code review tooling is being deployed across the software industry without a standardised way to measure whether the tools work. Khan et al.'s 2026 survey of 99 papers identified the absence of a systematic benchmark landscape as the central open problem. Existing benchmarks are valuable but incompatible: c-CRAB uses test-based ground truth on Python only; SWR-Bench uses LLM-as-judge on a dataset that cannot be publicly located; SWE-PRBench focuses on contamination mitigation; CRScore measures comment quality without a cross-tool scaffold; large-scale industry studies rely on developer-action proxies that confound quality with willingness to act. None measures all the behaviours that determine whether an AI reviewer can be trusted in production.

This paper specifies a measurement framework that addresses the gap. It defines 15 review dimensions organised by production-incident correlation, six change types with risk-proportional review, and a full metric suite covering detection performance, severity calibration, actionability, cost and sycophancy. Three contributions are novel: a false positive adjudication protocol that distinguishes hallucinations from genuine discoveries and feeds novel findings back into the ground truth; a sycophancy testing protocol that uses difficulty calibration to distinguish bias from inability, providing the first published methodology for measuring LGTM bias, critique sycophancy and severity softening in code review; and a multi-model experiment protocol with a two-stage semantic deduplication methodology for aggregating natural-language review findings across models.

A pilot implementation runs the full pipeline end-to-end on a 10-PR sample. It is not a measurement of reviewer quality, but it confirms the framework is implementable and has already surfaced four framework gaps (dimension classification as a separate metric, pre-benchmark judge calibration, per-dimension insufficient-coverage warnings, and separating ground-truth counts from flagged-finding counts in the reporting template) that would have propagated into larger runs otherwise.

The full framework specification, pilot code and sample fixtures are open-sourced at `github.com/zdaraoui2/ai-code-review-framework`. Other research teams can reproduce the pilot, apply the framework to their own datasets, and extend the measurement matrix. A code review research programme where AI and human reviewers can be compared on the same terms, category by category, is the prerequisite to knowing where AI belongs in the review loop and where it does not.

---

# References

## Human Reviewer Studies

- Bacchelli, A. and Bird, C. (2013). "Expectations, Outcomes, and Challenges of Modern Code Review." In *Proc. ICSE 2013*, pp. 712--721.
- Beller, M., Bacchelli, A., Zaidman, A., and Juergens, E. (2014). "Modern Code Reviews in Open-Source Projects: Which Problems Do They Fix?" In *Proc. MSR 2014*.
- Bosu, A., Greiler, M., and Bird, C. (2015). "Characteristics of Useful Code Reviews: An Empirical Study at Microsoft." In *Proc. MSR 2015*.
- Bosu, A. et al. (2014). "Identifying Characteristics of Vulnerable Code Changes." In *Proc. FSE 2014*.
- Czerwonka, J. et al. (2015). "Code Reviews Do Not Find Bugs: How the Current Code Review Best Practice Slows Us Down." In *Proc. ICSE-SEIP 2015*.
- Kemerer, C.F. and Paulk, M.C. (2009). "The Impact of Design and Code Reviews on Software Quality." *IEEE Transactions on Software Engineering*, 35(3).
- Mantyla, M.V. and Lassenius, C. (2009). "What Types of Defects Are Really Discovered in Code Reviews?" *IEEE Transactions on Software Engineering*, 35(3).
- McIntosh, S., Kamei, Y., Adams, B., and Hassan, A.E. (2014). "The Impact of Code Review Coverage and Participation on Software Quality." In *Proc. MSR 2014*.
- Paul, R., Turzo, A.K., and Bosu, A. (2021). "Why Security Defects Go Unnoticed during Code Reviews? A Case-Control Study of the Chromium OS Project." In *Proc. ICSE 2021*.
- Rigby, P.C. and Bird, C. (2013). "Convergent Contemporary Software Peer Review Practices." In *Proc. ESEC/FSE 2013*, pp. 202--212.
- Sadowski, C., Soderberg, E., Church, L., Sipko, M., and Bacchelli, A. (2018). "Modern Code Review: A Case Study at Google." In *Proc. ICSE-SEIP 2018*.
- Siy, H. and Votta, L. (2001). "Does the Modern Code Inspection Have Value?" *IEEE Software*.
- Thongtanunam, P., McIntosh, S., Hassan, A.E., and Iida, H. (2017). "Review Participation in Modern Code Review." *Empirical Software Engineering*, 22(2).

## AI Code Review Systems

- Chowdhury, K. et al. (2026). "From Industry Claims to Empirical Reality." In *Proc. MSR 2026*. arXiv:2604.03196.
- Cihan, U. et al. (2025). "Automated Code Review In Practice." In *Proc. ICSE SEIP 2025*. arXiv:2412.18531.
- Li, Z. et al. (2022). "Automating Code Review Activities by Large-Scale Pre-Training." In *Proc. FSE 2022*. arXiv:2203.09095.
- Rasheed, Z. et al. (2024). "AI-powered Code Review with LLMs: Early Results." arXiv:2404.18496.
- Sun, T. et al. (2025). "BitsAI-CR: Automated Code Review via LLM in Practice." In *Proc. FSE 2025*. arXiv:2501.15134.
- Vijayvergiya, M. et al. (2024). "AI-Assisted Assessment of Coding Practices in Modern Code Review." In *Proc. AIware 2024*. arXiv:2405.13565.

## Code Review Benchmarks and Evaluation

- Code Review Agent Benchmark (c-CRAB) (2026). arXiv:2603.23448.
- CodeFuse-CR-Bench / SWE-CARE. Guo, H. et al. (2025). arXiv:2509.14856.
- CodeReviewQA. Lin, H.Y. et al. (2025). "The Code Review Comprehension Assessment for LLMs." In *Proc. ACL Findings 2025*. arXiv:2503.16167.
- ContextCRBench (2025). "Benchmarking LLMs for Fine-Grained Code Review with Enriched Context." arXiv:2511.07017.
- Jimenez, C.E. et al. (2024). "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?" In *Proc. ICLR 2024*.
- Khan, T.I. et al. (2026). "A Survey of Code Review Benchmarks and Evaluation Practices in Pre-LLM and LLM Era." arXiv:2602.13377.
- Kumar, D. (2026). "SWE-PRBench: Benchmarking AI Code Review Quality Against Pull Request Feedback." arXiv:2603.26130.
- Martian Code Review Benchmark (2026). github.com/withmartian/code-review-benchmark.
- Naik, A. et al. (2025). "CRScore: Grounding Automated Evaluation of Code Review Comments." In *Proc. NAACL 2025*. arXiv:2409.19801.
- SWR-Bench (2025). "Benchmarking and Studying the LLM-based Code Review." arXiv:2509.01494.

## LLM-as-Judge and Evaluation Methodology

- Anchoring bias study (2025). arXiv:2503.05061.
- Framing bias study (2026). arXiv:2601.13537.
- Leniency bias study (2025). arXiv:2510.11822.
- Perez, E. et al. (2023). "Discovering Language Model Behaviors with Model-Written Evaluations." In *Proc. ACL Findings 2023*. arXiv:2212.09251.
- Sharma, M. et al. (2024). "Towards Understanding Sycophancy in Language Models." In *Proc. ICLR 2024*. arXiv:2310.13548.
- Shi, L. et al. (2025). "Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge." In *Proc. AACL-IJCNLP 2025*. arXiv:2406.07791.
- Verga, P. et al. (2024). "Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models." arXiv:2404.18796.
- Wataoka, K. et al. (2024). "Self-Preference Bias in LLM-as-a-Judge." arXiv:2410.21819.
- Ye, S. et al. (2024). "Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge." arXiv:2410.02736.
- Zheng, L. et al. (2023). "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena." In *Proc. NeurIPS 2023*. arXiv:2306.05685.

## Multi-Model Ensembles and Multi-Agent Systems

- Agarwal, M. et al. (2025). "When Persuasion Overrides Truth in Multi-Agent LLM Debates: Introducing CW-POR." arXiv:2504.00374.
- Chen, Z. et al. (2025). "Harnessing Multiple Large Language Models: A Survey on LLM Ensemble." arXiv:2502.18036.
- DivSampling (2025). "On the Effect of Sampling Diversity in Scaling LLM Inference." arXiv:2502.11027.
- EnsLLM (2025). "Enhancing LLM Code Generation with Ensembles." arXiv:2503.15838.
- FrugalGPT. Chen, L. et al. (2024). *TMLR*. arXiv:2305.05176.
- Hong, S. et al. (2024). "MetaGPT: Meta Programming for Multi-Agent Collaborative Framework." In *Proc. ICLR 2024*. arXiv:2308.00352.
- Li, X. et al. (2025). "Rethinking Mixture-of-Agents: Is Mixing Different Large Language Models Beneficial?" arXiv:2502.00674.
- LLM-TOPLA (2024). "Efficient LLM Ensemble by Maximising Diversity." In *Proc. EMNLP 2024 Findings*. arXiv:2410.03953.
- Madaan, A. et al. (2023). "Self-Refine: Iterative Refinement with Self-Feedback." In *Proc. NeurIPS 2023*. arXiv:2303.17651.
- MPLE (2024). "Multi-Programming Language Ensemble." arXiv:2409.04114.
- Measuring and Mitigating Identity Bias in Multi-Agent Debate via Anonymization (2025). arXiv:2510.07517.
- Qian, C. et al. (2024). "ChatDev: Communicative Agents for Software Development." In *Proc. ACL 2024*. arXiv:2307.07924.
- Talk Isn't Always Cheap: Understanding Failure Modes in Multi-Agent Debate (2025). arXiv:2509.05396.
- Vallecillos-Ruiz, H. et al. (2025). "Wisdom and Delusion of LLM Ensembles for Code Generation and Repair." arXiv:2510.21513.
- Wang, J. et al. (2024). "Mixture-of-Agents Enhances Large Language Model Capabilities." arXiv:2406.04692.
- Wang, X. et al. (2023). "Self-Consistency Improves Chain of Thought Reasoning in Language Models." In *Proc. ICLR 2023*. arXiv:2203.11171.

## Software Engineering Agents

- Xia, C. et al. (2024). "Agentless: Demystifying LLM-based Software Engineering Agents." arXiv:2407.01489.
- Yang, J. et al. (2024). "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering." In *Proc. NeurIPS 2024*.

## Cross-File Reasoning and Vulnerability Detection

- CPRVul (2025). "Beyond Function-Level Analysis: Context-Aware Reasoning for Inter-Procedural Vulnerability Detection." arXiv:2602.06751.
- DependEval. Du, Y. et al. (2025). "Benchmarking LLMs for Repository Dependency Understanding." In *Proc. ACL Findings 2025*. arXiv:2503.06689.
- Devign. Zhou, Y. et al. (2019). In *Proc. NeurIPS 2019*.
- BigVul. Fan, J. et al. (2020). In *Proc. MSR 2020*.
- DiverseVul. Chen, Y. et al. (2023). In *Proc. RAID 2023*.
- M2CVD (2024). "Multi-Model Collaboration for Code Vulnerability Detection." *ACM TOSEM*. arXiv:2406.05940.

## Human Factors and Adoption

- Adalsteinsson, F. et al. (2025). "Rethinking Code Review Workflows with LLM Assistance." arXiv:2505.16339.
- Alami, A. and Ernst, N. (2025). "Human and Machine: How Software Engineers Perceive and Engage with AI-Assisted Code Reviews." arXiv:2501.02092.
- Anthropic (2026). "AI Coding Assistance Reduces Developer Skill Mastery by 17%." InfoQ, February.
- METR (2025). "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity." arXiv:2507.09089.
- Nadri, R. et al. (2022). "On the Relationship between Developer's Perceptible Race/Ethnicity and Evaluation of Contributions in OSS." arXiv:2210.00139.
- OpenAI (2025). "Sycophancy in GPT-4o: What Happened and What We're Doing About It." Post-mortem, April.

## Additional Evidence Sources

- Academic peer review leniency study (2024). arXiv:2408.10365.
- Different LLMs make categorically different errors (ICSE 2025). arXiv:2406.08731.
- SWT-Bench (NeurIPS 2024). "Benchmarking LLM-Based Test Generation." (Ensemble of best four methods solves 71% more than best single method.)
- ThousandEyes (2024). Cloud Outage Report. Cisco ThousandEyes.

## Reproducibility and Statistical Rigour

- Agresti, A. and Coull, B. (1998). "Approximate is Better than 'Exact' for Interval Estimation of Binomial Proportions." *The American Statistician*.
- Brown, L.D., Cai, T.T. and DasGupta, A. (2001). "Interval Estimation for a Binomial Proportion." *Statistical Science*, 16(2), 101--133.
- Cohen, J. (1988). *Statistical Power Analysis for the Behavioral Sciences*. Routledge.
- Dietterich, T. (1998). "Approximate Statistical Tests for Comparing Supervised Classification Learning Algorithms." *Neural Computation*.
- "Do Repetitions Matter? Benchmarking LLMs under Multi-Run Evaluation" (2025). arXiv:2509.24086.
- LLM Stability (2024). arXiv:2408.04667.
- Takahashi, K. et al. (2022). "Confidence Intervals for the F1 Score." arXiv:2309.14621.
- Wang, X. and Wang, Y. (2025). "Assessing Consistency and Reproducibility in LLM Outputs." arXiv:2503.16974.

## Incident Data and Refactoring Risk

- Bavota, G. et al. (2012). "When Does a Refactoring Induce Bugs?" In *Proc. SCAM 2012*.
- Bernardo, J.H. et al. (2020). "Do Code Review Measures Explain the Incidence of Post-Release Defects?" *Empirical Software Engineering*.
- Dogga, P. et al. (2023). "AutoARTS: Taxonomy of Azure Incident Root Causes." In *Proc. USENIX ATC 2023*.
- Kim, M. et al. (2014). "An Empirical Study of Refactoring Challenges and Benefits at Microsoft." *IEEE Transactions on Software Engineering*.
- Towards Unmasking LGTM Smells in Code Reviews (2024). In *Proc. ICSME 2024*.

## Industry Reports

- Boehm, B. and Turner, R. (2003). *Balancing Agility and Discipline*. Addison-Wesley.
- Google DORA (2024, 2025). State of DevOps Report.
- Qodo (2025). State of AI Code Quality Report.
- SmartBear / Cisco (2006). Best Kept Secrets of Peer Code Review.
- Sonar (2026). State of Code Developer Survey.
- Stack Overflow (2025). Developer Survey. survey.stackoverflow.co/2025.

## Supply Chain and IaC

- HERCULE (2025). "Detecting Python Malware in the Software Supply Chain." In *Proc. ICSE 2025*.
- OSCAR (2024). "Towards Robust Detection of OSS Supply Chain." In *Proc. ASE 2024*.

---

