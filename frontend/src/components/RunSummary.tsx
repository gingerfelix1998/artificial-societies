/**
 * A three-sentence orientation for one replication, and the facts it is built from.
 *
 * **Two halves, deliberately unequal in status.** `RunFacts` carries every number and is
 * read straight from the record, so the prose beside it never has to state a count it could
 * get wrong. The narrative is model-written and is labelled as interpretation, because
 * `docs/framework/measurement.md` is explicit that the distribution over replications is
 * the result and one transcript is an anecdote — a readable story about a single run is
 * exactly the modal narrative that document exists to prevent.
 *
 * The narrative is generated once when the arm finishes and stored, so this text is the
 * same on every visit. A summary that changed on refresh would not be a record.
 *
 * When no narrative exists — a session run before the feature, or a summary call that
 * failed — the facts stand alone. That degradation is the intended behaviour, not an error
 * state: the half that matters is the half that cannot be wrong.
 */

import type { RunFacts, RunNarrative } from '../types/artsoc'
import { RUNG_LABELS } from '../lib/format'

interface Props {
  facts: RunFacts
  narrative?: RunNarrative | null
  /** The record this describes, so a stored narrative can be checked against it. */
  runId: string
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="summary-stat">
      <span className="summary-stat-value">{value}</span>
      <span className="faint small">{label}</span>
      {hint ? <span className="faint small">{hint}</span> : null}
    </div>
  )
}

export default function RunSummary({ facts, narrative, runId }: Props) {
  const basis = facts.basis_counts ?? {}
  const fromSources = basis.sources ?? 0
  const fromBeliefs = basis.beliefs ?? 0

  // A narrative stored against a different replication would be worse than none: it would
  // read as an account of the run on screen. Checked rather than assumed.
  const shown = narrative != null && narrative.run_id === runId ? narrative : null
  const stale = narrative != null && shown == null
  const sentences = shown?.sentences ?? []

  return (
    <section className="panel">
      <header>
        <h2>What happened in this replication</h2>
        <p className="subtitle">
          One replication, not the result. The distribution over replications is the finding;
          the arm&rsquo;s histogram is below.
        </p>
      </header>

      <div className="summary-stats">
        <Stat
          label="Action taken"
          value={facts.action}
          hint={`rung ${facts.rung} — ${RUNG_LABELS[facts.rung] ?? ''}${
            facts.is_nuclear ? ' · nuclear' : ''
          }`}
        />
        <Stat
          label="Panel"
          value={`${facts.personas_consulted}/${facts.panel_size}`}
          hint={`${facts.n_declines} of ${facts.n_opinions} answers declined`}
        />
        <Stat
          label="Positions rested on"
          value={`${fromSources} sources · ${fromBeliefs} beliefs`}
          hint={facts.grounded ? `retrieval: ${facts.retrieval_mode}` : 'not grounded'}
        />
        <Stat
          label="Brief carried"
          value={`${facts.n_consensus} consensus · ${facts.n_minority} minority`}
          hint={`synthesis: ${facts.synthesis_mode}`}
        />
        <Stat
          label="Collection"
          value={`${facts.events_detected} seen · ${facts.events_missed} missed`}
          hint={`${facts.events_degraded} degraded · stated ${facts.intel_confidence}`}
        />
        <Stat
          label="Citations"
          value={String(facts.n_citations)}
          hint={
            facts.n_unsupported_citations > 0
              ? `${facts.n_unsupported_citations} unsupported`
              : 'none unsupported'
          }
        />
      </div>

      {shown != null && sentences.length > 0 ? (
        <div className="narrative">
          <span className="pill warn">Interpretation, not a finding</span>
          <p>{sentences.join(' ')}</p>
          <p className="faint small">
            {shown.caveat} Written once by <code>{shown.model}</code> when this arm finished,
            from the agent-visible record — it was not shown the host&rsquo;s ground truth,
            so it cannot say whether the assessment was correct.
          </p>
        </div>
      ) : (
        <p className="faint small">
          {stale
            ? 'A stored summary exists but describes a different replication, so it is not shown.'
            : 'No written summary for this run. The figures above are read from the record.'}
        </p>
      )}
    </section>
  )
}
