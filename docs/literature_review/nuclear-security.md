# Literature review — LLM simulation in nuclear security and international relations

The close domain. What exists, what it has settled, and what it leaves open.

## 1. The literature

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Rivera, Mukobi, Reuel, Lamparth, Smith, Schneider (2024) | *Escalation Risks from Language Models in Military and Diplomatic Decision-Making*, FAccT | Founding study. Eight nation-agents, 14-day crisis, 27 preset actions, five models. All were prone to sudden, even nuclear escalation; none de-escalated over a simulation and all showed arms-racing. Qualitative reading of the models' own justifications found agents equated higher military spending and deterrent posture with greater power and security. |
| Lamparth, Corso, Ganz, Mastro, Schneider, Trinkunas (2024) | *Human vs. Machine*, AIES | The only large human benchmark: 214 national security experts in a Taiwan Strait scenario. LLM simulations could not account for player characteristics, showing no significant difference even for traits as extreme as "pacifist" or "aggressive sociopath"; simulated team dialogue lacked quality and maintained a farcical harmony. |
| Payne (2026) | *AI Arms and Influence*, KCL | 21 games, 300+ turns, three frontier models. Extended interconnected play enables analysis of memory, adaptation and reputation that single-shot designs cannot capture. Models spontaneously attempted deception, signalled intentions they did not intend to follow, and assessed their own strategic abilities before acting. Nuclear threats in 95% of scenarios. |
| Xu, Li, Chen, Xu (2025) | *Nuclear Deployed!*, ACL Findings | 14,400 agentic simulations across 12 models. Agents engaged in catastrophic behaviour and deception without deliberate inducement, and stronger reasoning ability often increased rather than mitigated these risks. Makes model choice an experimental variable. |
| — (2025) | *Red Lines and Grey Zones in the Fog of War* | Builds on Rivera's design while adapting nation descriptions, scenario construction, action set and models, adding legal and moral risk metrics absent from prior work. |
| — (2025) | *Managing Escalation in Off-the-Shelf LLMs* | Mitigation side. Notes crisis bargaining requires taking the opponent's perspective and slowing a problem down to let cooler heads prevail — precisely what LLMs lack. |
| — (2026) | *LLMs as Strategic Actors* | A theory-grounded framing taxonomy operationalising realism, liberal institutionalism and constructivism for interpretable comparison across models. The closest existing use of IR theory in this literature — but as *output coding*, not persona input. |
| Hogan, Brennen (2024) | *Open-Ended Wargames with LLMs* ("Snow Globe"), IQT Labs | Reference open-source implementation. Every stage from scenario preparation to post-game analysis can be carried out by AI, humans or a combination, with actions not restricted to predefined options, and support for advisor roles. |
| Hua, Fan, Li, Mei, Ji, Ge, Hemphill, Zhang (2023) | *War and Peace (WarAgent)* | Each country agent employs a "secretary agent" verifying appropriateness and logical consistency, with a Board for international relations and a Stick as internal record. Also the field's only serious leakage test: counterfactual fine-tuning where WWI did not happen still produced global war. |
| — (2025) | *From Script to Stage* | Reproduces the 13-day Cuban Missile Crisis with two state agents, chosen for data availability, clear decision nodes and traceable results — outcome leakage as feature, not confound. |
| — (2025) | *Increasing AI Explainability by LLM Driven Standard Processes* | Role-conditioned extensive-form CMC game reaching de-escalation in 56 of 60 runs and 100% of four-step paths. Presented as reproducing history; equally consistent with knowing the ending. |
| Emery (2021) | Pre-LLM computer-assisted wargaming | Cited within Rivera et al.: wargames with heavy computer automation were more likely to lead to nuclear use. Escalation bias is not purely an LLM artifact. |

## 2. What this literature has settled

That off-the-shelf models escalate in wargame settings, including from neutral starting
conditions, and do so unpredictably. This is replicated across research groups, model
families, scenarios and action sets. It is no longer an open question, and it has a pre-LLM
precedent.

The consequence for any new work: **absolute escalation rates are not findings.** Only
contrasts against a no-apparatus control are attributable to anything the researcher built.

## 3. Gaps

**Escalation measurement is saturated.** Six of twelve entries above measure whether models
escalate. Marginal value of a thirteenth is near zero.

**The advisory apparatus is universally plumbing.** In every study a nation is one agent, or a
leader with an undifferentiated staff. Lamparth's team alone simulated intra-team dialogue,
found it degenerate, and moved on rather than attempting a structural repair.

**Personas are national, never individual.** Every study conditions on country profiles,
capabilities and histories. Nobody conditions on the intellectual commitments of named
strategists; nobody grounds a security persona in primary theoretical text.

**Trait differentiation is documented as failing, and unrepaired.** Lamparth's null on
"pacifist" versus "aggressive sociopath" is the field's most important negative result. No
follow-up asks whether richer grounding rescues what trait labels could not.

**Validation has no standard.** WarAgent's counterfactual fine-tuning is the only genuine
leakage test, and it is one manipulation on one model whose reasoning the authors concede the
fine-tuning degraded. The Cuban Missile Crisis reproductions treat known outcomes as
validation targets.

**Doctrine is never varied.** Scenario, model and action set are all manipulated. The
theoretical literature that shapes how professionals reason about crises is never an input
variable.

**The unit of analysis is fixed at the state.** See `docs/literature/ir-theory-and-simulation.md`
— this is not an oversight but a paradigm commitment, and it is the largest gap of all.

## 4. Gaps this project fills

1. **Corpus-grounded strategist personas.** Named theorists conditioned on their own writings,
   with citation verification and an out-of-record escape hatch. Nothing in the domain does
   this.

2. **A direct test of Lamparth's null.** M1/M2/M3 asks whether grounding produces the
   differentiation trait labels did not. Publishable either way.

3. **The advisory layer as the experimental object.** Enforced context partitioning, theorists
   blind to each other, compression through a logged brief, and `consensus_only` versus
   `full_range` measuring what compression drops. A structural response to farcical harmony
   rather than an avoidance of it.

4. **Deltas rather than absolute rates.** `escalation_prior` reframes a settled question as an
   open one: does structured expert input change the decision?

5. **Causal influence attribution.** Fifteen forced-exclusion arms in which a theorist is
   absent from panel, roster and prompt. No comparable study attributes outcomes to individual
   expert inputs at all.

6. **Doctrine as independent variable.** The `era` field and phase 3's corpus swap make
   theoretical literature the manipulation, scenario and seeds fixed.

7. **A shift in the unit of analysis** from state to individual and to the structure of expert
   community — the theoretical argument, developed separately in
   `docs/literature/ir-theory-and-simulation.md`.

## 5. Caveats

Blank author cells are papers where search returned title, abstract and findings but not
authorship; verify before citing, as several are recent preprints. Emery (2021) is known only
secondhand through Rivera et al.'s bibliography and should be chased directly — it is the
pre-LLM precedent and it strengthens the argument that escalation bias is not merely an
artifact of language models.