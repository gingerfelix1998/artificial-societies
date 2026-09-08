/**
 * One replication in full: who was asked, what they said, and what the decision rested on.
 *
 * **An illustrative single run, not the result.** The distribution over replications is the
 * finding; one transcript reaching a nuclear rung is an anecdote. The arm's distribution
 * therefore stays on this screen beside the run, and the rule that selected this record is
 * printed rather than left to be guessed at.
 *
 * Four panels share one playback cursor — the graph, the activity timeline, the event log
 * and the provenance chain. Separate state would let them drift apart on screen, and the
 * whole point of showing them together is that they are four views of one sequence.
 */

import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import AgentPanel from '../components/AgentPanel'
import EventLog from '../components/EventLog'
import InteractionGraphView from '../components/InteractionGraphView'
import LoopGantt from '../components/LoopGantt'
import PlaybackControls from '../components/PlaybackControls'
import ProvenanceDiagram from '../components/ProvenanceDiagram'
import RungHistogram from '../components/RungHistogram'
import RunSummary from '../components/RunSummary'
import { RUNG_LABELS, humanise, percent } from '../lib/format'
import { usePlayback } from '../lib/playback'
import type { ArmSummary, RepresentativeView, SessionSummary } from '../types/artsoc'

export default function RepresentativeRun() {
  const { sessionId = '', arm = '' } = useParams()
  const [view, setView] = useState<RepresentativeView | null>(null)
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [reveal, setReveal] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const [detail, session] = await Promise.all([
          api.representative(sessionId, arm, reveal),
          api.summary(sessionId),
        ])
        setView(detail)
        setSummary(session)
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [sessionId, arm, reveal])

  const playback = usePlayback(view?.steps.length ?? 0)
  const agent = useMemo(
    () => view?.agents.find((a) => a.id === selected) ?? null,
    [view, selected],
  )

  if (error) {
    return (
      <div className="notice stop">
        <strong>Could not load this run</strong>
        {error}
      </div>
    )
  }
  if (!view || !summary) return <p className="spin">Loading…</p>

  const record = view.representative.record
  const armSummary: ArmSummary | undefined = summary.arms.find((a) => a.arm === arm)

  return (
    <>
      <div className="crumb">
        <Link to="/">All simulations</Link>
        <span>/</span>
        <Link to={`/sessions/${sessionId}`}>{summary.label || summary.session_id.slice(0, 8)}</Link>
        <span>/</span>
        <Link to={`/sessions/${sessionId}/macro`}>Across all runs</Link>
        <span>/</span>
        <span>
          {arm} · seed {record.seed}
        </span>
      </div>

      <header className="section">
        <h1>{humanise(record.action.action)}</h1>
        <p className="subtitle">
          Rung {record.rung} — {RUNG_LABELS[record.rung]}. One replication of{' '}
          <code>{arm}</code>, seed {record.seed}.
        </p>
      </header>

      <div className="notice info">
        <strong>An illustrative single run — not the result</strong>
        {view.representative.selection_note}
      </div>

      <section className="section">
        <div className="grid two">
          <RunSummary
            facts={view.facts}
            narrative={view.narrative}
            record={record}
            sessionId={sessionId}
            arm={arm}
          />
          <div>
            <h4>The arm this run came from</h4>
            {armSummary ? (
              <>
                <RungHistogram distribution={armSummary.rung_distribution} n={armSummary.n} />
                <p className="tiny faint">
                  n={armSummary.n} · mean {armSummary.mean_rung.toFixed(2)} · P(nuclear){' '}
                  {percent(armSummary.p_nuclear)}. This replication landed on rung{' '}
                  {record.rung}; the distribution is the finding and this run is one bar in it.
                </p>
              </>
            ) : (
              <p className="empty">No summary for this arm.</p>
            )}
          </div>
        </div>
      </section>

      <hr className="rule" />

      <section className="section">
        <header>
          <h2>The panel</h2>
          <p className="subtitle">
            Every persona on the panel, consulted or not. Select one to read what it was
            asked, what it answered, and the record&rsquo;s account of why it was consulted.
            Declining is styled apart from never being asked: it is a substantive act, and the
            escape hatch firing is the honest outcome rather than a gap in the data.
          </p>
        </header>

        <div className="stage">
          <InteractionGraphView
            nodes={view.graph.nodes}
            edges={view.graph.edges}
            hallucinated={view.graph.hallucinated_ids ?? []}
            steps={view.steps}
            cursor={playback.cursor}
            onSelectAgent={(id) => setSelected(id === selected ? null : id)}
            selectedAgent={selected}
          />
          <div className="agent-panel">
            <AgentPanel agent={agent} onClose={() => setSelected(null)} />
          </div>
        </div>
      </section>

      <hr className="rule" />

      <section className="section">
        <header>
          <h2>What the decision rested on</h2>
          <p className="subtitle">
            Cited source text, through the positions it grounded, to the courses of action the
            Advisor proposed and the one the President took. Every link comes from an id the
            record holds — a citation, a supporting-opinion reference, a chosen option — and
            none is inferred from wording.
          </p>
        </header>
        <ProvenanceDiagram flow={view.provenance} />
      </section>

      <hr className="rule" />

      <div className="stage">
        <section className="section" style={{ marginBottom: 0 }}>
          <header>
            <h2>Activity by loop step</h2>
            <p className="subtitle">
              Logical loop steps, not wall-clock time: step indices are deterministic and
              reproducible from config plus seed. There is no per-call timing in the record
              and there should not be — capturing it would mean persisting every prompt.
            </p>
          </header>
          <LoopGantt
            steps={view.steps}
            nodes={view.graph.nodes}
            cursor={playback.cursor}
            onSelect={playback.seek}
            onSelectAgent={(id) => setSelected(id === selected ? null : id)}
            selectedAgent={selected}
          />
        </section>

        <section className="section" style={{ marginBottom: 0 }}>
          <header>
            <h2>Event log</h2>
            <p className="subtitle">
              What each role produced, in loop order. The analytical question is repeated on
              every consultation and reply — it is recorded output written by the Advisor. The
              prompts are a different thing and are not here.
            </p>
          </header>
          <EventLog
            steps={view.steps}
            record={record}
            cursor={playback.cursor}
            onSelect={playback.seek}
          />
        </section>
      </div>

      <hr className="rule" />

      <section className="section">
        <div className="row">
          <h2 style={{ margin: 0 }}>Host ground truth</h2>
          <div className="spacer" />
          <button
            className={reveal ? 'danger small' : 'small'}
            onClick={() => setReveal(!reveal)}
          >
            {reveal ? 'Hide' : 'Reveal'}
          </button>
        </div>
        <p className="subtitle" style={{ marginTop: '0.5rem' }}>
          What was actually happening. <strong>No agent in this simulation saw it.</strong> It
          exists so misperception can be scored after the fact, not so anyone in the loop could
          be correct — the gap between it and the intelligence brief is the thing worth reading.
        </p>

        {reveal && view.host_ground_truth ? (
          <>
            <div className="notice warn" style={{ marginTop: '1rem' }}>
              <strong>Host-only</strong>
              {view.host_only_note}
            </div>
            {Object.entries(view.host_ground_truth).map(([eventId, truth]) => (
              <div key={eventId} style={{ marginBottom: '1rem' }}>
                <h4>{eventId}</h4>
                <p className="muted small">{truth}</p>
              </div>
            ))}
          </>
        ) : (
          <p className="faint small">Withheld. Press reveal to see it.</p>
        )}
      </section>

      <div className="timeline">
        <PlaybackControls playback={playback} />
      </div>
    </>
  )
}
