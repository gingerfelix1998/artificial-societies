/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Produced by `make types`, which dumps JSON Schema from the pydantic models in
 * src/artsoc/{schema,views,session,metrics}.py and compiles it here. Edit the Python
 * models and re-run `make types`; editing this file makes the two disagree silently.
 */

/* eslint-disable */

/**
 * The Advisor's compression of the panel into something the President reads.
 *
 * The compression is a modelled step, not plumbing: what gets dropped — usually minority
 * positions — is itself a finding, which is what `consensus_only` vs `full_range`
 * isolates.
 */

export interface AdvisorBrief {
  summary: string
  consensus_points?: string[]
  minority_positions?: string[]
  synthesis_mode?: string
  n_opinions?: number
}

/**
 * One answered follow-up question, stored so re-asking it costs nothing.
 */

export interface AnalysisAnswer {
  session_id: string
  arm: string
  question: string
  answer?: string
  model?: string
  caveat?: string
}

/**
 * One decontextualised question the Advisor puts to the panel.
 *
 * No scenario, no nation, no date, no capability. That keeps the elicitation analytical
 * rather than advisory, and makes answers reusable across replications.
 */

export interface AnalyticalQuestion {
  question_id: string
  text: string
  tags?: string[]
}

/**
 * One committed arm, and what it varies from base.
 *
 * `varies` is what makes the arm list interpretable: an arm is only worth running because
 * of the one field it moves, and a client picking arms should see that rather than a list
 * of names.
 */

export interface ArmInfo {
  arm: string
  scenario_id: string
  notes: string
  varies: {
    [k: string]: any
  }
  is_control: boolean
  is_exclusion_arm: boolean
  consult_panel: boolean
}

/**
 * One arm's distribution and diagnostics, with the conditions that produced them.
 */

export interface ArmSummary {
  arm: string
  n: number
  rung_distribution: {
    [k: string]: number
  }
  mean_rung: number
  median_rung: number
  p_nuclear: number
  declared_panel_size: number
  distinct_personas: number
  mean_run_coverage: number
  n_opinions: number
  out_of_record_rate: number
  n_citations: number
  n_unsupported: number
  citation_integrity: number
  backend: string
  grounded: boolean
  cache_enabled: boolean
  retrieval_mode: string
  consulted_panel: boolean
  persona_method: string
  basis_counts?: {
    [k: string]: number
  }
  beliefs_share?: number
  models?: {
    [k: string]: string
  }
  warnings?: string[]
}

/**
 * What a session will ask the provider to do, before any of it happens.
 *
 * Call counts, not dollars. A pre-run USD figure needs tokens per call, which vary by an
 * order of magnitude across roles and are not known until something has run; quoting one
 * would be inventing the most quotable number in the response. Actual spend is metered
 * from each record's `est_cost_usd` as the session runs.
 */

export interface CallEstimate {
  session_id: string
  arms: ArmEstimate[]
  total_calls: number
  backend: string
  cache_enabled: boolean
  note?: string
}

export interface ArmEstimate {
  arm: string
  n: number
  consult_panel: boolean
  calls_per_replication: number
  total_calls: number
  roles: RoleCost[]
}
/**
 * The model that will serve one role, and what it costs per million tokens.
 *
 * Published rates, quoted so a reader can do the arithmetic themselves. `None` for a model
 * with no published rate on file, which shows as a gap rather than as a fabricated number.
 */

export interface RoleCost {
  role: string
  model: string
  calls: number
  usd_per_mtok_in?: number | null
  usd_per_mtok_out?: number | null
}

/**
 * Per-persona grounding of the option the President took.
 *
 * **This is not influence and must never be labelled as it.** It says whose opinions the
 * Advisor cited when it built the option that was chosen — a recorded fact about the
 * document, not a measurement of what anyone changed. A persona could be cited in every
 * chosen option and change nothing, or be cited in none and have shifted which options
 * were proposed at all.
 *
 * Causal attribution comes from the `loo_*` forced-exclusion arms, where the persona is
 * absent from the panel, every roster and every prompt, and the world is re-run without
 * them. That is a contrast between arms and lives in the influence panel.
 */

export interface CoaSupport {
  arm: string
  n_records: number
  n_with_coas: number
  personas: PersonaCoaSupport[]
  note?: string
}
/**
 * How often one persona's opinions grounded a proposed and a chosen option.
 */

export interface PersonaCoaSupport {
  persona_id: string
  name: string
  runs_answered: number
  cited_by_any_coa: number
  cited_by_chosen_coa: number
  runs_in_chosen: number
  share_of_chosen: number
}

/**
 * One arm's contrast against the control. The only interpretable quantity here.
 */

export interface Delta {
  arm: string
  control: string
  d_mean_rung: number
  d_p_nuclear: number
}

/**
 * Per-persona engagement across an arm, plus what could not be attributed.
 */

export interface EngagementSummary {
  arm: string
  n_records: number
  personas: PersonaEngagement[]
  unattributed_unsupported: number
  note?: string
}
/**
 * What one persona did across an arm. Descriptive only.
 *
 * **No influence language belongs in this model.** How often a persona was consulted says
 * nothing about what its presence changed: routing correlates with question tags, which
 * correlate with outcome. Attribution comes from the `loo_*` forced-exclusion arms and is
 * a contrast between arms, not a column in this table.
 */

export interface PersonaEngagement {
  persona_id: string
  name: string
  in_panel_runs: number
  times_consulted: number
  matched_by_tag: number
  chosen_by_advisor: number
  topped_up: number
  n_opinions: number
  n_declines: number
  decline_rate: number
  mean_confidence: number | null
  n_citations: number
  n_unsupported: number
  basis_counts?: {
    [k: string]: number
  }
}

/**
 * The Intelligence Officer's product. Written by the IO, read by the President.
 */

export interface IntelBrief {
  summary: string
  assessed_activity: string
  confidence: string
  alternative_explanations?: string[]
  collection_gaps?: string[]
}

/**
 * Who spoke to whom in one replication, with the unused population present.
 */

export interface InteractionGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  hallucinated_ids?: string[]
}
/**
 * One participant in a replication.
 *
 * `state` distinguishes four different things that all look like "not much happened":
 *
 * * `active` — produced a position.
 * * `declined` — answered `out_of_record`. Declining is a substantive act and the escape
 *   hatch firing is the honest outcome, so it is not styled as absence.
 * * `unconsulted` — on the panel, never asked. The unused population stays visible.
 * * `excluded` — removed by intervention in a `loo_*` arm. The world operated as though
 *   they never existed, which is a different fact from nobody choosing them.
 */

export interface GraphNode {
  id: string
  label: string
  kind: string
  state: string
  n_opinions?: number
  n_declines?: number
  mean_confidence?: number | null
}
/**
 * One communication between two participants.
 *
 * Typed by `kind` so consultations, opinions, declines and the final decision can be
 * styled apart. `weight` is the number of communications of that kind between the pair,
 * for a graph where the Advisor talks to one persona three times.
 */

export interface GraphEdge {
  source: string
  target: string
  kind: string
  step_index: number
  step_indices?: number[]
  weight?: number
}

/**
 * What the simulation landing page states, and the caveats that gate reading it.
 *
 * One arm — the one the reader is looking at — plus the contrast against the control.
 * `facts` carries every number, so the generated prose beside it never has to state one.
 */

export interface LandingView {
  session_id: string
  label: string
  scenario: ScenarioInfo | null
  arm: string
  arms: string[]
  facts: SessionFacts
  coa_support: CoaSupport
  analysis?: SessionAnalysis | null
  summary: SessionSummary
}
/**
 * One committed scenario, as a client may see it.
 *
 * Two things are absent on purpose. `ground_truth_detail` is host-only and exists so
 * misperception can be scored, not so anyone reading a scenario card can know the answer.
 * `Scenario.notes` are the host's *design* commentary — what the ambiguity is meant to do
 * and why the ground truth is withheld — and describing the mechanism to a viewer is a
 * softer version of the same leak.
 *
 * What is shown instead is `observable_signature`: exactly what a collection apparatus
 * could in principle see. It is the agent-visible half of the event by definition, and it
 * is what makes the ambiguity legible without narrating it.
 */

export interface ScenarioInfo {
  scenario_id: string
  label: string
  description: string
  self_nation: string
  adversary_nation: string
  n_events: number
  observable_signature?: string[]
}
/**
 * The deterministic account of a session, for a header to state without interpreting.
 *
 * Exists for the same reason `RunFacts` does: the generated prose beside it never has to
 * carry a number it could get wrong. Every field is read or arithmetic over what was read.
 *
 * `d_mean_rung` and `d_p_nuclear` are `None` when the control arm was not run. That is the
 * honest state — absolute rates are not findings, so with no control there is no
 * interpretable quantity here at all, and a zero would read as "no difference" rather than
 * as "no comparison".
 */

export interface SessionFacts {
  arm: string
  n: number
  mean_rung: number
  median_rung: number
  p_nuclear: number
  modal_action: string
  modal_action_share: number
  d_mean_rung?: number | null
  d_p_nuclear?: number | null
  control_arm?: string | null
  declared_panel_size?: number
  mean_run_coverage?: number
  out_of_record_rate?: number
  beliefs_share?: number
  actions?: ActionCount[]
  n_with_coas?: number
}
/**
 * One action, how often it was proposed, and how often it was taken.
 */

export interface ActionCount {
  action: string
  rung: number
  is_nuclear: boolean
  proposed: number
  chosen: number
}
/**
 * Per-persona grounding of the option the President took.
 *
 * **This is not influence and must never be labelled as it.** It says whose opinions the
 * Advisor cited when it built the option that was chosen — a recorded fact about the
 * document, not a measurement of what anyone changed. A persona could be cited in every
 * chosen option and change nothing, or be cited in none and have shifted which options
 * were proposed at all.
 *
 * Causal attribution comes from the `loo_*` forced-exclusion arms, where the persona is
 * absent from the panel, every roster and every prompt, and the world is re-run without
 * them. That is a contrast between arms and lives in the influence panel.
 */

export interface SessionAnalysis {
  session_id: string
  arm: string
  sentences?: string[]
  model?: string
  caveat?: string
}
/**
 * Per-arm distributions, contrasts against the control, and the caveats.
 *
 * The caveats are fields rather than prose because a client has to be able to render them
 * above the charts. A number that travels without them is how an absolute escalation rate
 * becomes a finding about nuclear strategists, which it is not.
 */

export interface SessionSummary {
  session_id: string
  label: string
  scenario_id: string
  arms: ArmSummary[]
  deltas: Delta[]
  control_arm?: string
  has_control?: boolean
  warnings?: string[]
  backend?: string
  models?: {
    [k: string]: string
  }
  grounded?: boolean
  cache_enabled?: boolean
  retrieval_mode?: string
  est_cost_usd?: number
  smoke_test?: boolean
  mock?: boolean
}
/**
 * One arm's distribution and diagnostics, with the conditions that produced them.
 */

export interface LoopStep {
  index: number
  role: string | null
  actor: string
  recipient: string
  kind: string
  label: string
  payload_ref: string
  excerpt?: string
  question_id?: string | null
  persona_id?: string | null
}

/**
 * Cited ids resolved against a persona's own store.
 *
 * `unresolved` is the interesting half. An id the store does not contain was invented by
 * the persona, and the rate of that is a finding about the method — so it is returned as
 * its own list rather than quietly omitted from `passages`.
 */

export interface PassageLookup {
  persona_id: string
  passages: Passage[]
  unresolved: string[]
  note?: string
}
/**
 * One cited passage, resolved to the text it points at.
 */

export interface Passage {
  passage_id: string
  source: string
  section: string
  text: string
}

/**
 * An event as one nation's collection apparatus registered it.
 *
 * A separate type from `WorldEvent` on purpose. There is no `ground_truth_detail` field
 * here, so leaking the host's truth into a prompt requires changing this class rather
 * than forgetting a `del`.
 */

export interface PerceivedEvent {
  event_id: string
  t_occurred: number
  t_observed: number
  actor_nation: string
  description: string
  observable_signature?: string[]
  confidence?: number
  degraded?: boolean
  source_note?: string
}

/**
 * Replication counts flowing through the loop to each terminal rung.
 *
 * **This is not an escalation path.** Phase 1 produces exactly one `PresidentialAction`
 * per replication and `RunRecord.rung` is a single terminal value; there is no sequence of
 * rungs, because the loop is one event and one decision. Multi-step escalation arrives in
 * phase 2, when Presidents signal to each other. What this shows is what varied *upstream*
 * of each terminal rung, which is the honest version of the same affordance.
 *
 * The middle stage is the panel's basis mix rather than the synthesis mode the original
 * spec suggested. `synthesis_mode` is set by config, so within one arm it is one value and
 * the stage would carry no information. Basis mix varies per replication and is the ADR
 * 0004 diagnostic: whether stated positions rested on retrieved sources or on the belief
 * store.
 */

export interface PipelineFlow {
  arm: string
  n_records: number
  nodes: FlowNode[]
  links: FlowLink[]
  label?: string
}

export interface FlowNode {
  id: string
  label: string
  stage: number
  count: number
}

export interface FlowLink {
  source: string
  target: string
  count: number
}

/**
 * The closed set of actions available to the President.
 */

export type ActionType =
  | 'private_reassurance'
  | 'no_action'
  | 'public_statement'
  | 'private_warning'
  | 'diplomatic_sanction'
  | 'public_ultimatum'
  | 'force_dispersal'
  | 'alert_level_raise'
  | 'weapons_test'
  | 'forward_deployment'
  | 'conventional_strike'
  | 'nuclear_demonstration'
  | 'nuclear_limited_strike'
  | 'nuclear_counterforce'
  | 'nuclear_countervalue'

/**
 * Exactly one typed action, plus the justification that did not produce it.
 */

export interface PresidentialAction {
  action: ActionType
  /**
   * Qualitative data only. Never an input to the rung.
   */
  justification: string
  chosen_coa_id?: string | null
  rung: number
  is_nuclear: boolean
}

/**
 * The President's question to the Advisor.
 *
 * Deliberately a decontextualised strategic question. The Advisor has no collection
 * access; if the query carried situational detail the Advisor would acquire one by the
 * back door.
 */

export interface PresidentialQuery {
  text: string
  concerns?: string[]
}

/**
 * One completed replication, as the client sees it stream past.
 */

export interface ProgressEvent {
  session_id: string
  arm: string
  completed: number
  total: number
  rung?: number | null
  seed?: number | null
  est_cost_usd?: number
  cumulative_cost_usd?: number
  failure?: string | null
}

/**
 * Cited passages → theorist positions → proposed courses of action → the decision.
 *
 * **Complete only for records written under ADR 0006.** `CourseOfAction.supporting_opinions`
 * is what links an option to the opinions it rests on; before that field existed there was
 * nothing to draw the middle of this chain from, and inferring it by matching words would
 * be fabricating the exact relationship the diagram claims to show. A record without
 * courses of action therefore yields the passage→opinion half and says why the rest is
 * missing, rather than rendering an empty stage.
 */

export interface ProvenanceFlow {
  nodes: ProvenanceNode[]
  links: ProvenanceLink[]
  coa_stage: string
  coa_note?: string
  schema_version?: string
}
/**
 * One thing in the chain from source text to decision.
 */

export interface ProvenanceNode {
  id: string
  kind: string
  label: string
  detail?: string
  chosen?: boolean
  declined?: boolean
  persona_id?: string | null
  question_id?: string | null
}

export interface ProvenanceLink {
  source: string
  target: string
  kind: string
  chosen?: boolean
}

/**
 * The closed set of actions available to the President.
 */

export interface RepresentativeRun {
  record: RunRecord
  selection_note: string
  median_rung: number
  n_candidates: number
  n_records: number
}
/**
 * One replication, in full.
 *
 * Everything needed to reproduce and audit a single decision. `host_ground_truth` is
 * included for the analyst so misperception can be scored; it is host-side output and
 * must never be fed back into a prompt.
 */

export interface RunRecord {
  schema_version?: string
  run_id: string
  arm: string
  seed: number
  started_at: string
  wall_time_s: number
  config: {
    [k: string]: any
  }
  backend: string
  models?: {
    [k: string]: string
  }
  cache_enabled: boolean
  retrieval_mode: string
  /**
   * True only when a real corpus retriever produced the M2 context. False under StubRetriever, so a stub run can never be read as grounded.
   */
  grounded: boolean
  scenario_id: string
  injected_event_ids?: string[]
  host_ground_truth?: {
    [k: string]: string
  }
  view?: PerceivedEvent[]
  detected_event_ids?: string[]
  missed_event_ids?: string[]
  intel_brief: IntelBrief
  presidential_query?: PresidentialQuery | null
  questions?: AnalyticalQuestion[]
  routing?: RoutingRecord[]
  opinions?: TheoristOpinion[]
  advisor_brief?: AdvisorBrief | null
  courses_of_action?: CourseOfAction[]
  unsupported_citations?: string[]
  action: PresidentialAction
  rung: number
  panel_size?: number
  personas_consulted?: string[]
  llm_calls?: number
  cache_hits?: number
  retries?: number
  token_usage?: {
    [k: string]: number[]
  }
  est_cost_usd?: number
}
/**
 * An event as one nation's collection apparatus registered it.
 *
 * A separate type from `WorldEvent` on purpose. There is no `ground_truth_detail` field
 * here, so leaking the host's truth into a prompt requires changing this class rather
 * than forgetting a `del`.
 */

export interface RoutingRecord {
  question_id: string
  k_requested: number
  mode?: string
  matched_by_tag?: string[]
  chosen_by_advisor?: string[]
  topped_up?: string[]
  rationale?: string
  roster?: string[]
  hallucinated?: string[]
  selected: string[]
}
/**
 * One persona's answer to one analytical question.
 *
 * `out_of_record` is the escape hatch. Without it a persona confabulates a position to
 * fill the answer slot, and the distinction between "X held this" and "a model
 * impersonating X generated this" is lost.
 */

export interface TheoristOpinion {
  persona_id: string
  persona_name: string
  question_id: string
  position: string
  reasoning: string
  citations?: string[]
  out_of_record?: boolean
  confidence?: number
  method?: string
  basis?: string
}
/**
 * The Advisor's compression of the panel into something the President reads.
 *
 * The compression is a modelled step, not plumbing: what gets dropped — usually minority
 * positions — is itself a finding, which is what `consensus_only` vs `full_range`
 * isolates.
 */

export interface CourseOfAction {
  coa_id: string
  action: ActionType
  /**
   * The Advisor's own case for this action, grounded in citations.
   */
  rationale: string
  supporting_opinions?: string[]
}
/**
 * Exactly one typed action, plus the justification that did not produce it.
 */

export interface RepresentativeView {
  arm: string
  representative: RepresentativeRun
  steps: LoopStep[]
  graph: InteractionGraph
  panel: string[]
  agents: AgentDetail[]
  facts: RunFacts
  narrative?: RunNarrative | null
  engagement: EngagementSummary
  flow: PipelineFlow
  provenance: ProvenanceFlow
  host_ground_truth?: {
    [k: string]: string
  } | null
  host_only_note?: string
}
/**
 * One record chosen to illustrate an arm, plus the rule that chose it.
 *
 * **Not a result.** One replication reaching a nuclear rung is an anecdote; the
 * distribution over replications is the finding. `selection_note` exists so a viewer can
 * see why this record and not another, and must be rendered with it.
 */

export interface AgentDetail {
  id: string
  label: string
  kind: string
  summary: string
  answers?: AgentAnswer[]
  fields?: [any, any][]
  passages?: [any, any][]
}
/**
 * One question put to one theorist, and what came back.
 *
 * `basis` and `declined` are kept apart because they answer different questions. A
 * persona shown belief text that still declined is a different fact from one shown
 * nothing at all, and collapsing them would hide which of the two happened.
 */

export interface AgentAnswer {
  question_id: string
  question: string
  how_selected: string
  selection_rationale: string
  declined: boolean
  basis: string
  position: string
  reasoning: string
  citations?: string[]
  confidence: number
}
/**
 * The deterministic account of one replication. Every field is read, none inferred.
 *
 * This exists so the readable narrative beside it never has to carry a number. A model
 * asked to summarise can misstate a count; these cannot, because they are the record.
 */

export interface RunFacts {
  action: string
  rung: number
  is_nuclear: boolean
  panel_size: number
  personas_consulted: number
  n_opinions: number
  n_declines: number
  basis_counts: {
    [k: string]: number
  }
  synthesis_mode: string
  n_consensus: number
  n_minority: number
  events_detected: number
  events_missed: number
  events_degraded: number
  intel_confidence: string
  n_citations: number
  n_unsupported_citations: number
  grounded: boolean
  retrieval_mode: string
}
/**
 * A stored three-sentence summary, tied to the run it describes.
 */

export interface RunNarrative {
  run_id: string
  arm: string
  sentences?: string[]
  model?: string
  caveat?: string
}
/**
 * Per-persona engagement across an arm, plus what could not be attributed.
 */

export interface RunConfig {
  arm: string
  scenario_id?: string
  backend?: string
  models?: {
    [k: string]: string
  }
  max_concurrency?: number
  max_parse_retries?: number
  max_api_retries?: number
  effort?: string
  models_override?: string | null
  cache_enabled?: boolean
  retrieval_mode?: string
  retrieval_top_k?: number
  retrieval_min_terms?: number
  retrieval_belief_min_terms?: number | null
  consult_panel?: boolean
  persona_method?: string
  panel_source?: string
  panel_size?: number
  k_per_question?: number
  n_questions?: number
  synthesis_mode?: string
  routing_mode?: string
  excluded_personas?: string[]
  notes?: string
}

/**
 * A stored three-sentence summary, tied to the run it describes.
 */

export interface SessionCreated {
  session_id: string
  state: SessionState
  estimate: CallEstimate
}
/**
 * A session's spec plus where it has got to.
 */

export interface SessionState {
  spec: SessionSpec
  status?: string
  created_at?: string
  finished_at?: string | null
  progress?: ArmProgress[]
  est_cost_usd?: number
  error?: string | null
}
/**
 * What a session is: some committed arms, one scenario, n replications each.
 *
 * Frozen for the same reason `RunConfig` is: a session that could mutate its own spec
 * part-way through would make `spec.json` a description of something other than what ran.
 */

export interface SessionSpec {
  session_id?: string
  label?: string
  scenario_id: string
  arms: string[]
  n: number
  seed0?: number
}
/**
 * How far one arm has got. Written into `spec.json`'s sibling status file.
 */

export interface ArmProgress {
  arm: string
  completed: number
  total: number
  failures?: string[]
}
/**
 * What a session will ask the provider to do, before any of it happens.
 *
 * Call counts, not dollars. A pre-run USD figure needs tokens per call, which vary by an
 * order of magnitude across roles and are not known until something has run; quoting one
 * would be inventing the most quotable number in the response. Actual spend is metered
 * from each record's `est_cost_usd` as the session runs.
 */
