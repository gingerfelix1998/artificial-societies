# Literature review — artificial societies and agent modelling in social science

The methodological lineage, across every field that has tried this. The classical tradition
matters here: it set standards that the LLM literature has largely abandoned, and reclaiming
them is one of this project's cheapest sources of credibility.

## 1. The literature

### 1.1 Classical agent-based modelling

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Schelling (1971) | *Dynamic Models of Segregation* | Foundational demonstration that mild individual preferences produce strong aggregate segregation. Macro patterns require no macro intentions. |
| Axelrod (1984) | *The Evolution of Cooperation* | Tournament methodology: heterogeneous strategies under fixed rules, with replication across many runs as the unit of evidence rather than a single narrative. |
| Axelrod (1986) | *An Evolutionary Approach to Norms*, APSR | The first ABM of norm emergence, introducing metanorms — norms punishing failure to punish. Still the reference point for computational work on normative order. |
| Epstein & Axtell (1996) | *Growing Artificial Societies* | The origin of the term this project bears. Sugarscape established generative explanation: growing a phenomenon from micro-rules is a candidate account of it. |
| Epstein (2006) | *Generative Social Science* | Formalises the generativist claim and its limit — growing a pattern demonstrates sufficiency, never necessity. |
| Macy & Willer (2002); Bonabeau (2002) | Review articles | Codify the methodological standards: parameter sweeps, sensitivity analysis, docking against alternative models, reporting distributions. |

### 1.2 LLM generative agents and frameworks

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Park, O'Brien, Cai, Morris, Liang, Bernstein (2023) | *Generative Agents: Interactive Simulacra of Human Behavior* | The architectural template — memory stream, retrieval, reflection, planning — most LLM social simulation still uses. |
| Park, Zou, Shaw, Hill, Cai, Morris, Willer, Liang, Bernstein (2024) | *Generative Agent Simulations of 1,000 People* | 1,052 real individuals simulated from qualitative interviews, replicating GSS responses 85% as accurately as participants replicate their own answers two weeks later, and reducing accuracy bias across racial and ideological groups relative to demographic descriptions. **Grounding beats attributes; test-retest is the right denominator.** |
| Vezhnevets et al. (2023) | *Concordia*, Google DeepMind | A Game Master entity, inspired by tabletop role-playing, simulates the environment; agents describe intended actions in natural language and the GM translates them into outcomes, checking plausibility. The dominant general-purpose GABM library. |
| Piao et al. (2025) | *AgentSociety* | Large-scale LLM society for institutional emergence. |

### 1.3 Silicon sampling and its critics

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Argyle, Busby, Fulda, Gubler, Rytting, Wingate (2023) | *Out of One, Many*, Political Analysis | Established silicon sampling and algorithmic fidelity. Sociodemographic conditioning reproduced meaningful demographic–attitude relationships in political-opinion settings. |
| Bisbee, Clinton, Dorff, Kenkel, Larson | *Synthetic Replacements for Human Survey Data?* | Synthetic samples can resemble population averages while misrepresenting variation, subgroup relationships and individual responses. Matched marginals do not imply valid replacement. |
| Li, Li, Qiu (2025) | *ChatGPT is not A Man but Das Man* | Failure of structural consistency across demographic aggregation levels, plus homogenization that underrepresents minority opinions. |
| — (2025) | Large-scale persona-generation audit | ~1,000,000 personas across six open models and 500+ questions; substantial bias amplified by LLM-generated persona content. |
| Wang, Morgenstern, Dickerson (2024) | *LLMs Cannot Replace Human Participants Because They Cannot Portray Identity Groups* | Argues analytically and shows empirically across four models and 3,200 participants over 16 identities that LLMs both misportray and flatten demographic groups; inference-time mitigations reduce but do not remove the harms. |
| — (2023) | *CoMPosT: Characterizing and Evaluating Caricature in LLM Simulations* | Formalises caricature as measurable, and calls for documentation of simulation design including creators' positionality. |
| — (2026) | *Too human to model*, npj Complexity | Agents' conversations take no account of prior rounds without an explicit timestamped memory system, producing repetition. Continuity must be engineered, not assumed. |
| — (2025) | *LLM-based Human Simulations Have Not Yet Been Reliable* | Field-level statement of the reliability problem. |

### 1.4 Deliberation pathologies

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Baltaji et al. (2024) | *Persona Inconstancy in Multi-Agent LLM Collaboration* | The discussion initiator has outsize influence on the group's final decision, and merely mentioning participants' identities pushed the initiator to shift position before anyone else spoke. |
| Patel (2026) | *Representational Collapse in Multi-Agent LLM Committees* | Three agents under distinct role prompts produced rationale embeddings at 0.888 mean pairwise cosine similarity, effective rank 2.17 of 3.0. Role conditioning shifts phrasing without complementary reasoning. |
| — (2026) | *Diversity Collapse in Multi-Agent LLM Systems* | Attributes collapse to interaction topology rather than persona fidelity, alongside sycophancy, "disagreement collapse" and an "Artificial Hivemind" convergence regardless of prompting. |
| — (2026) | *The Deliberative Illusion* | Prior work assumes consistency implies correctness and overlooks whether diversity survives deliberation at all. |
| — (2026) | *The Cost of Consensus* | Heterogeneous teams underperformed the best homogeneous member in 6 of 8 condition–task pairs. Panel diversity is not automatically a benefit. |

### 1.5 Corpus-grounded personas

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| — (2025) | *Beyond Profile* ("CharacterBot") | Models Lu Xun from 17 essay collections comprising 638 works with full texts and segmented passages, using Authorial Perspective Reframing — rewriting first-person narrative into third person with markers such as "the author argues" to tie each statement to its originator. |
| — (2024) | *PersonaFlow* | Author-profiling and literature-node persona generation from paper abstracts via a scientific sentence classification pipeline. Abstracts not full argument; ideation not decision. |
| Van Buren (2023) | *Guided scenarios with simulated expert personae*, JPL | Early statement that teams of simulated personae with staged context can elicit expert behaviour to perform meaningful cognitive work. Strong framing, thin validation. |

### 1.6 Validation, calibration and elicitation

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| — | *Deliberation in Silico* | Validates against a verbatim EU Council transcript used exclusively for post-hoc evaluation and never given to agents. Contamination tested five ways: bigram Jaccard 0.031, trigram 0.007, below the real-versus-real baseline. Found simulated agents produced roughly twice as many explicit cross-country references as real ministers. |
| — (2026) | *Digital Pantheon* | Isolated per-agent RAG, ideological alignment via SFT and DPO, a grounding layer benchmarking provisions against the historically adopted agreement, and clause-level tracing back to originating manifesto chunks with provenance labels. |
| — (2026) | *Scalable Delphi* | Adapts Delphi with diverse expert personas, iterative refinement and rationale sharing; evaluated by calibration against verifiable proxies, sensitivity to evidence, and alignment with human panels. r=0.87–0.95, in one case closer to a human panel than two human panels were to each other. |
| — (2025) | *PersonaAgent* | Test-time persona alignment: the agent rewrites its own persona prompt to minimise a textual loss against ground-truth responses, with no parameter fine-tuning. |
| — (2026) | Dual-agent traveller alignment | A supervisory calibration agent optimises a persona by textual pseudo-gradient descent, with a smoothing step against a longer-window baseline to avoid overfitting short-term randomness. |

### 1.7 Applications and benchmarks

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Collodel (2026) | *Interpreting the Interpreter*, Central Bank of Malta | 30 synthetic traders interpreting ECB press conferences across 293 events, 1998–2026. Cross-sectional disagreement correlates ~0.5 with realised swap volatility and holds out-of-sample on genuinely unseen conferences. Rare case with real external validation. |
| Martinson, Kong, Kim, Taneja, Tambe (2025) | *LLM-based Agent Simulation for Maternal Health*, AAMAS | Decision-focused evaluation with uncertainty estimation where historical and counterfactual data are unavailable. |
| Dai et al. (2024) | *Artificial Leviathan* | Agents with psychological drives transition from a conflictual state of nature to a commonwealth under an absolute sovereign, matching Hobbes's account. Theory-testing as validation. |
| Vallinder & Hughes (2024) | Iterated Donor Game | Cultural evolution in LLM societies mirrors indirect reciprocity, with pronounced base-model differences: one model's societies rose from 50% to 77% donation over ten generations while another's declined below 15%. |
| — (2026) | *LLM Agents Predict Social Media Reactions but Do Not Outperform Text Classifiers* | 120K+ personas of 1,511 humans. Classifiers achieved better calibration (Brier 0.20 vs 0.33) and richer personas improved accuracy by ~2 points in one study and not at all in another. Agentic framing must be benchmarked against non-agentic baselines. |
| — (2026) | *Simulated Customers Never Walk Away* | Introduces decision fidelity against 2,790 real conversations with 793 verified payment outcomes, finding a "disengagement deficit": simulators reproduce buyers almost exactly but inflate non-buyers toward purchase, halving expressed resistance. |

## 2. Gaps

**Validation has no shared standard.** Every strand invents one — test-retest, necessary
conditions, n-gram contamination, verified outcomes. None has been adopted across strands, and
most published simulations validate against nothing.

**Grounding is proven and rarely done.** Park's interviews and CharacterBot's corpus work both
succeed. Applied persona work still overwhelmingly uses demographic or trait prompts, which the
critique literature has repeatedly shown to flatten and caricature.

**Deliberation is assumed beneficial and is measurably harmful.** Five independent 2024–2026
results find inter-agent communication destroys the diversity multi-agent systems exist to
exploit. Few applied simulations measure whether diversity survived; most report consensus as
convergence on truth.

**Provenance is almost never traced.** Digital Pantheon's clause-to-chunk tracing is close to
unique. In most systems there is no way to ask which input produced which output, so influence
— the quantity social scientists most want — is unrecoverable.

**Attribution is correlational.** Forced-exclusion designs are essentially absent. Influence is
inferred from co-occurrence, which is confounded wherever selection is endogenous.

**Process fidelity is neglected for outcome fidelity.** Most validation compares final states.
How a group reasoned — options raised and rejected, order of consideration, dispersion — is
richer and, being less memorable, more diagnostic of genuine simulation.

**Classical standards have been abandoned.** Parameter sweeps, sensitivity analysis and docking
are baseline in the Epstein–Axtell tradition and largely absent from LLM social simulation,
which typically reports a handful of runs and a narrative.

**Refusal is not modelled.** Almost no persona system offers an agent a way to decline. This is
one mechanism behind the flattening the critique literature documents: with no exit, a persona
must produce a position whether or not it holds one.

## 3. Gaps this project fills

1. **Structural context partitioning as experimental control.** The access matrix — type
   separation, a raising guard, a prompt-scanning canary suite — makes role differentiation a
   property of architecture rather than prompt wording. Given that role prompting shifts
   phrasing without producing complementary reasoning, this is a direct response to
   representational collapse.

2. **Prophylaxis against deliberation pathologies.** Theorists never see each other, so herding
   cannot occur by construction. Most systems in that literature discovered collapse after
   building for consensus.

3. **Forced-exclusion attribution.** Fifteen arms where a persona is absent from every roster
   and prompt, converting influence from correlational to causal.

4. **Verifiable citation provenance with an honest failure rate.** Content-addressed passage
   ids verified against exactly the block a persona was shown; unsupported citations recorded
   and reported, never corrected. Among the few designs able to distinguish a grounded claim
   from a fluent one, and the only one treating the hallucination rate as a finding.

5. **A refusal mechanism with a diagnostic threshold.** The out-of-record hatch, plus a metric
   flagging a near-zero decline rate as a *warning* rather than a success.

6. **Classical ABM discipline restored.** Monte Carlo replication, pre-declared ablation arms,
   distribution-not-narrative reporting, deterministic reproducibility from config plus seed.

7. **A model-free primary metric.** The escalation rung is a lookup on a typed action, never
   judged by a model. The field's usual pattern — an LLM judging LLM output — makes metric
   drift undetectable across model versions.

## 4. Standards worth adopting that this project does not yet meet

- **Sensitivity analysis and docking**, per Macy & Willer and Bonabeau. Currently absent.
- **Benchmarking against a non-agentic baseline**, per the social-media reactions result. If a
  simpler method reproduces the panel's effect, that must be reported.
- **The Scalable Delphi validation triad** — calibration on verifiable proxies, sensitivity to
  added evidence, alignment with human judgement — which is built precisely for unobservable
  targets and which nobody in security wargaming has adopted.
- **Base-model variation as an experimental factor**, per the Donor Game result showing
  opposite cooperative trajectories across model families.

## 5. Caveats

Blank author cells are works where search returned title and findings but not authorship.
Classical entries are from general knowledge rather than retrieved sources — verify editions
and page references. Bisbee et al. is known only secondhand through a survey of the
silicon-sampling literature.