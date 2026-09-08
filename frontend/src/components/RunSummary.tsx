/**
 * A three-sentence orientation for one replication, and the facts it is built from.
 *
 * **Two halves, deliberately unequal in status.** `RunFacts` carries every number and is
 * read straight from the record, so the prose beside it never has to state a count it could
 * get wrong. The narrative is model-written and labelled as interpretation, because
 * `docs/framework/measurement.md` is explicit that the distribution over replications is
 * the result and one transcript is an anecdote — a readable story about a single run is
 * exactly the modal narrative that document exists to prevent.
 *
 * Generated on request, not during the sweep: a sweep runs every arm and a reader opens
 * one. Written to disk on first request and served from there, so the text is the same on
 * every visit — a summary that changed on refresh would not be a record.
 *
 * A narrative stored against a different replication is discarded rather than shown. It
 * would read as an account of the run on screen, which is worse than having none.
 */

import { useState } from 'react'

import { api } from '../api/client'
import { RUNG_LABELS, humanise, percent } from '../lib/format'
import type { RunFacts, RunNarrative, RunRecord } from '../types/artsoc'

interface Props {
  facts: RunFacts
  narrative?: RunNarrative | null
  record: RunRecord
  sessionId: string
  arm: string
}

export default function RunSummary({ facts, narrative, record, sessionId, arm }: Props) {
  const [stored, setStored] = useState<RunNarrative | null | undefined>(narrative)
  const [busy, setBusy] = useState(false)

  const basis = facts.basis_counts ?? {}
  const shown = stored != null && stored.run_id === record.run_id ? stored : null

  const generate = async () => {
    setBusy(true)
    try {
      setStored(await api.narrative(sessionId, arm))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h4>What happened in this replication</h4>

      {shown && (shown.sentences ?? []).length > 0 ? (
        <>
          <p className="lede" style={{ fontSize: '1.1rem' }}>
            {(shown.sentences ?? []).join(' ')}
          </p>
          <p className="lede-source">{shown.caveat}</p>
        </>
      ) : (
        <>
          <p className="muted">
            The intelligence brief assessed confidence as {facts.intel_confidence}, having
            detected {facts.events_detected} event(s) and missed {facts.events_missed}.{' '}
            {facts.n_opinions > 0
              ? `${facts.personas_consulted} of ${facts.panel_size} personas were consulted, and ${facts.n_declines} of ${facts.n_opinions} answers declined as outside their record.`
              : 'No panel was consulted in this arm.'}{' '}
            The President chose {humanise(facts.action)}, rung {facts.rung}.
          </p>
          <button className="small" onClick={() => void generate()} disabled={busy}>
            {busy ? 'Reading the record…' : 'Generate a written summary'}
          </button>
        </>
      )}

      <dl className="conditions" style={{ marginTop: '1rem' }}>
        <div>
          <dt>action</dt>
          <dd className={facts.is_nuclear ? 'bad' : ''}>
            {facts.action} · rung {facts.rung} · {RUNG_LABELS[facts.rung] ?? ''}
          </dd>
        </div>
        <div>
          <dt>panel</dt>
          <dd>
            {facts.personas_consulted}/{facts.panel_size} consulted
          </dd>
        </div>
        <div>
          <dt>declined</dt>
          <dd>
            {facts.n_declines}/{facts.n_opinions}
            {facts.n_opinions > 0
              ? ` · ${percent(facts.n_declines / facts.n_opinions, 0)}`
              : ''}
          </dd>
        </div>
        <div>
          <dt>rested on</dt>
          <dd>
            {basis.sources ?? 0} sources · {basis.beliefs ?? 0} beliefs
          </dd>
        </div>
        <div>
          <dt>brief</dt>
          <dd>
            {facts.n_consensus} consensus · {facts.n_minority} minority
          </dd>
        </div>
        <div>
          <dt>citations</dt>
          <dd className={facts.n_unsupported_citations > 0 ? 'bad' : ''}>
            {facts.n_citations}
            {facts.n_unsupported_citations > 0
              ? ` · ${facts.n_unsupported_citations} unsupported`
              : ''}
          </dd>
        </div>
      </dl>
    </div>
  )
}
