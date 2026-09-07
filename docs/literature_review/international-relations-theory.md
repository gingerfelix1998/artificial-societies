# Literature review — IR theory schools and computational simulation

How the major traditions of international relations theory have been operationalised
computationally, and where this project sits. This is the document that states the
project's theoretical claim, so it also states honestly where that claim is not yet earned.

## 1. The traditions, and how each has been simulated

Wight's three traditions — realism, rationalism, revolutionism — still organise the field, and
they map cleanly onto three different answers to the question a simulation must answer first:
**who is the actor?**

| Tradition | Actor | Core claim | Computational treatment |
|---|---|---|---|
| Realism / neorealism | The unitary state | Anarchy plus material capability determines behaviour; units are functionally alike | Dominant. Nearly all LLM wargaming; classical ABM of alliance and war |
| Constructivism | States, but constituted by ideas; and the individuals and communities producing those ideas | Interests are socially constructed; norms and identity shape behaviour | Sparse but real — Cederman, Lustick, norm-emergence ABM |
| English School | International society: states bound by shared rules and institutions; and world society, whose ultimate units are individuals | Order arises from shared institutions, not only from balance | Almost none |

### 1.1 Constructivism and its computational lineage

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Wendt (1992, 1999) | *Anarchy Is What States Make of It*; *Social Theory of International Politics* | The foundational statement: structure is social, not merely material. Establishes that the same material configuration supports different behavioural logics. |
| Adler & Haas (1992); Haas (1992) | *Epistemic Communities and International Policy Coordination*, International Organization 46(1) | **The anchor for this project.** Decision-makers facing technical complexity rely on expert networks sharing normative beliefs, causal beliefs, internally defined validity criteria, and a common policy enterprise. Control over knowledge is a dimension of power, and diffusion of new ideas can produce new patterns of behaviour. |
| Adler (1992) | *The Emergence of Cooperation: National Epistemic Communities and the International Evolution of the Idea of Nuclear Arms Control*, IO 46(1) | **The closest theoretical precedent that exists.** An American epistemic community created the shared understanding and practice of nuclear arms control; in the absence of nuclear war, leaders' expectations were shaped by causal theories and abstract models developed by that community, which were diffused and ultimately embodied in the 1972 ABM treaty. Notes the community was an aggregation of several factions sharing common ground against rivals. |
| Finnemore & Sikkink (1998) | *International Norm Dynamics and Political Change* | The norm life cycle — emergence, cascade, internalisation — the standard process model for normative change. |
| Katzenstein, ed. (1996) | *The Culture of National Security* | Constructivism applied specifically to security, where realism was thought strongest. |
| Tannenwald (2007) | *The Nuclear Taboo* | Argues a normative tradition of non-use constrains nuclear choices beyond material deterrence. Already in this project's persona registry. |
| Cederman (1997) | *Emergent Actors in World Politics* | The bridge between constructivism and computation. Argues conventional theory reifies actors; models states and nations as emergent rather than preconceived, using complex adaptive systems rather than rational choice. |
| Cederman (2002) | *Endogenizing geopolitical boundaries with agent-based modeling*, PNAS | Explicitly formalises a constructivist notion of national identity in conformance with the qualitative nationalism literature, via categorical schemata over cultural traits, avoiding reification of agency. |
| Cederman (2001) | *Agent-Based Modeling in Political Science* | Methodological statement: computation simulates agents' cognitive processes to explore emergent macro phenomena not reducible to micro-level properties. |
| Axelrod (1986) | *An Evolutionary Approach to Norms*, APSR | Pre-constructivist in vocabulary but the origin of computational norm emergence, including metanorms. |
| Lustick, Miodownik et al. | PS-I / agent-based identity modelling | Identity repertoires as agent state, allowing identity to be activated and to shift — the most explicitly constructivist ABM platform in political science. *(Verify citations directly; included from general knowledge.)* |

### 1.2 English School

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Bull (1977) | *The Anarchical Society* | The three-concept structure. An international system forms when states have sufficient contact to behave as parts of a whole; an international society exists when states conceive themselves bound by common rules and share in common institutions; world society is more fundamental still, because its ultimate units are individual human beings rather than states. Five primary institutions: diplomacy, international law, the balance of power, war, and the role of great powers. |
| Wight | Primary institutions of early-20th-century international society | Diplomacy, alliances, guarantees, war and neutrality — establishing that institutions vary by type of international society. |
| Buzan (2004) | *From International to World Society* | Extends primary institutions into a richer set of primary and secondary institutions that change over time; institutions are durable recognised practices structured around shared values. |
| Buzan & Lawson (2018) | *The English School: history and primary institutions* | Responds to the charge that the School lacks clarity on empirical assessment: it is empirical without being empiricist, developing insight into how international society emerges, develops and sometimes breaks down. |
| Mellish (2024) | *Returning to Hedley Bull* | Argues for defining primary institutions by necessity, and notes disagreement among Bull, Wight, Holsti, Mayall, James and Jackson over whether the balance of power and war qualify at all. |
| — | UNGA solidarity study | Applies the English School framework to UNGA speeches 1991–2022 across three groupings using sentiment analysis and topic modelling. One of very few computational treatments, and it is text analysis rather than simulation. |

### 1.3 LLM-era theory-testing simulations

These are the most direct methodological precedents for using an artificial society to test a
social theory rather than to forecast an outcome.

| Author(s) | Work | Contribution / differentiator |
|---|---|---|
| Dai et al. (2024) | *Artificial Leviathan* | Agents with psychological drives move from a conflictual state of nature to a commonwealth under a sovereign, matching Hobbes. Congruence with the theoretical account is treated as the result. |
| Vallinder & Hughes (2024) | Iterated Donor Game | Indirect reciprocity emerges when agents observe others' recent behaviour, with sharply different trajectories across base models. |
| Ren et al. (2024) | CRSEC | Norm emergence in four modules: creation and representation, spreading, evaluation, compliance. Effectively a computational Finnemore–Sikkink life cycle. |
| Piao et al. (2025) | AgentSociety | Institutional emergence at large scale. |
| — (2025) | ProSim | Prosocial norm emergence, decay and diffusion under institutional interventions and fairness manipulations. |
| — (2026) | *Emergent Relational Order in LLM Agent Societies* | Tests a non-Western sociological theory computationally, noting that existing simulations focus on short-term coordination or dyadic exchange and that structural predictions of such theories have rarely been tested. |

## 2. Gaps

**Realism is the default because it is the easiest to code.** A unitary state with capabilities
and a payoff function is a natural agent. Constructivism requires modelling where interests
come from; the English School requires modelling shared institutions. Both are harder, and both
are correspondingly rare.

**Constructivist ABM stalled before the LLM era.** Cederman and Lustick showed identity and
categorical schemata could be formalised, but with hand-coded rules over abstract trait
landscapes. The obvious next step — agents whose beliefs come from the actual texts that
constituted the community — was not technically available. It is now.

**The English School has almost no computational tradition at all.** The single sustained
computational engagement found here is topic modelling of UNGA speeches. Nobody has simulated
international society as distinct from international system: no model in this review implements
a shared institution as a constraint agents recognise, as opposed to a payoff they optimise.

**Norm-emergence simulations are ahistorical.** CRSEC, ProSim and the Donor Game work all grow
norms from scratch in abstract environments. None instantiates a *documented* normative order
with its actual content, which is exactly what the nuclear domain offers.

**Theory-testing simulations validate by congruence.** Artificial Leviathan's finding is that
the trajectory matched Hobbes. That is suggestive, but a theory sufficiently well known to the
base model may be reproduced by recall rather than by mechanism, and none of these studies runs
the contamination analysis that *Deliberation in Silico* did.

**Epistemic communities have never been simulated.** Adler's account of how the arms-control
community's ideas became political expectations describes a causal pathway from expert
knowledge to state policy. No computational model of it exists.

## 3. Where this project sits

**The claim.** The nuclear simulation literature treats the state as the actor and the model as
its brain, which is a realist commitment expressed as an engineering default. This project
relocates the unit of analysis in two directions at once: **downward**, to the individuals whose
ideas constitute how a state understands its own situation, and **upward**, to the structure of
the community and the normative order they inhabit.

**Constructivist grounding.** The theorist panel is an *epistemic community* in Haas's precise
sense: a network sharing normative beliefs, causal beliefs, internally defined validity criteria
and a common policy enterprise. Adler's study of exactly this community for exactly this domain
supplies the causal pathway the architecture implements — expert knowledge, mediated by
advisers, shaping a leader's expectations and therefore state action. The architecture's
theorist → advisor → president → world chain is not an engineering convenience; it is Adler's
mechanism rendered executable.

Two design details follow directly from the theory rather than from software concerns. Adler's
observation that the community was several factions sharing ground against rivals is why
`consensus_only` versus `full_range` matters: collapsing an epistemic community to its consensus
discards the structure Adler identified. And Tannenwald's taboo is already in the registry as a
persona, meaning a constructivist mechanism competes with realist ones inside the panel.

**Why the domain suits it.** The nuclear security field is unusually well documented — a bounded
and near-enumerable body of theoretical literature, declassified deliberation records, ExComm
transcripts, FRUS volumes, and a normative order (non-use) whose emergence is itself extensively
studied. Constructivist claims are usually hard to operationalise because ideas are hard to
observe. Here they were written down.

## 4. What the thread does not yet earn

Stated plainly, because these are the objections a supervisor will raise first.

**The President is still a realist actor.** It has doctrine, disposition, red lines and a closed
action space, and it decides alone for a unitary nation. The constructivist move is located
entirely in where its *advice* comes from. That is defensible — it is Adler's argument, in which
epistemic communities shape state policy rather than replacing states — but it must be argued,
not assumed, or the design reads as realism with a literature review attached.

**There is no international society yet, only an international system.** Phase 2's mutual
signalling produces Bull's *system*: states with sufficient contact to behave as parts of a
whole. It does not produce *society*, which requires states conceiving themselves bound by
common rules and sharing in common institutions. To claim the English School, at least one
primary institution must be modelled as a recognised constraint rather than a payoff — the
non-use taboo is the obvious candidate, and diplomacy is the second.

**World society is absent.** Bull's world society takes individuals as ultimate units. This
project's individuals are advisers to a state, not members of a transnational society. The
theorists cannot address each other, address other nations, or constitute anything. That is the
right call for phase 1's herding controls, but it means "world society" cannot currently be
claimed at all.

**The constructivist claim needs a falsification condition.** As stated it risks being
unfalsifiable. The concrete version: if `synth_only` (anonymous, position-defined personas)
reproduces `baseline` (named theorists with records), then individual identity contributed
nothing and only abstract positions mattered — which is a weakly *structural* result, not a
constructivist one. Say so in advance.

## 5. Concrete next steps that would earn it

1. **Add an `ir_school` field to the registry** alongside `era`, and run school-restricted
   panels as arms. The registry already spans the paradigms — Waltz, Wohlstetter and
   Lieber & Press against Tannenwald, Jervis and Sagan. A `realist_panel` versus
   `constructivist_panel` contrast on an identical scenario operationalises the entire golden
   thread as an experiment, costs one YAML field and a handful of arm files, and is the single
   highest-value change available.

2. **Model one primary institution.** Implement the non-use taboo as a constraint the President
   recognises rather than a preference it weighs — for instance, an action that must be
   explicitly justified against the norm rather than merely selected. Contrast with an arm where
   the institution is absent. That is an English School experiment, and nothing in the
   literature has run one.

3. **Cite Adler (1992) as the theoretical frame in every write-up.** It converts the
   architecture from an engineering choice into an implementation of an established causal
   account, and it pre-empts "why model theorists at all?".

4. **Reframe phase 3 explicitly as norm-evolution work.** The era-restricted corpus swap is a
   Finnemore–Sikkink life cycle question: does the same situation produce different behaviour
   under different stages of normative development? That is a more interesting framing than
   "comparing two time periods".

5. **Run the contamination analysis.** If the theoretical claim is that ideas shaped outcomes,
   the alternative explanation is always that the model recalls the outcome. *Deliberation in
   Silico*'s n-gram protocol is the available answer and no theory-testing simulation in
   Section 1.3 uses it.

## 6. Caveats

Wendt, Finnemore & Sikkink, Katzenstein, Tannenwald, Lustick and Wight entries are from general
knowledge rather than retrieved sources — verify editions, page references and exact titles
before citing. The Lustick PS-I entry in particular should be confirmed directly. Bull's five
primary institutions and the three-concept structure are corroborated by retrieved sources, but
the primary quotations should be checked against *The Anarchical Society* itself rather than
secondary summaries.