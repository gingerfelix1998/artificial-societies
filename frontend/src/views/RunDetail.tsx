/**
 * One replication, in three coordinated panels driven by one playback cursor.
 *
 * **This is an illustrative single run, not the result.** The distribution over replications
 * is the finding; one transcript reaching a nuclear rung is an anecdote. The arm's
 * distribution therefore stays on this screen alongside the run, and the selection rule that
 * chose this record is printed rather than left to be guessed at.
 *
 * `host_ground_truth` is behind a toggle and labelled host-only. It is in the record so an
 * analyst can score misperception; no agent in the simulation ever saw it, and a viewer
 * meeting it unasked would read it as something the President knew.
 */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import EventLog from '../components/EventLog'
import InteractionGraphView from '../components/InteractionGraphView'
import LoopGantt from '../components/LoopGantt'
import PanelResponses from '../components/PanelResponses'
import AgentPanel from '../components/AgentPanel'
import PlaybackControls from '../components/PlaybackControls'
import RunSummary from '../components/RunSummary'
import RungHistogram from '../components/RungHistogram'
import { RUNG_LABELS, percent } from '../lib/format'
import { usePlayback } from '../lib/playback'
import type { RepresentativeView } from '../types/api'
import type { ArmSummary, SessionSummary } from '../types/artsoc'

export default function RunDetail() {
  const { sessionId = '', arm = '' } = useParams()
  const [view, setView] = useState<RepresentativeView | null>(null)
  const [agentId, setAgentId] = useState<string | null>(null)
  const [summary, setSummary] = useState<SessionSummary | null>(null)
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

  if (error) {
    return (
      <div className="banner danger">
        <strong>COULD NOT LOAD THIS RUN</strong>
        {error}
      </div>
    )
  }
  if (!view || !summary) return <p className="empty">Loading…</p>

  const record = view.representative.record
  const armSummary: ArmSummary | undefined = summary.arms.find((a) => a.arm === arm)

  return (
    <>
      <div className="row">
        <h1 style={{ margin: 0 }}>
          {arm} · seed {record.seed}
        </h1>
        <span className="pill">
          rung {record.rung} — {RUNG_LABELS[record.rung]}
        </span>
        <div className="spacer" />
        <Link to={`/sessions/${sessionId}`}>
          <button className="ghost small">Back to results</button>
        </Link>
      </div>

      <div className="banner info">
        <strong>ILLUSTRATIVE SINGLE RUN — NOT THE RESULT</strong>
        {view.representative.selection_note}
      </div>

      <div className="grid two">
        <section className="panel">
          <header>
            <h2>The arm this run came from</h2>
            <p className="subtitle">
              The distribution is the finding. This run is one bar in it.
            </p>
          </header>
          {armSummary ? (
            <>
              <RungHistogram
                distribution={armSummary.rung_distribution}
                n={armSummary.n}
                height={170}
                compact
              />
              <p className="small faint">
                n={armSummary.n} · mean {armSummary.mean_rung.toFixed(3)} · P(nuclear){' '}
                {percent(armSummary.p_nuclear)} — this replication landed on rung{' '}
                {record.rung}.
              </p>
            </>
          ) : (
            <p className="empty">No summary for this arm.</p>
          )}
        </section>

        <section className="panel">
          <header>
            <h2>What the President decided</h2>
          </header>
          <p className="mono">{record.action.action}</p>
          <p className="muted small">{record.action.justification}</p>
          <p className="faint small">
            The rung is a fixed lookup on the typed action. The justification is qualitative
            data and never touches it — two identical actions with different reasoning score
            identically, which is what stops the primary metric drifting between model
            versions.
          </p>
        </section>
      </div>

      <RunSummary
        facts={view.facts}
        narrative={view.narrative}
        runId={record.run_id}
      />

      <PanelResponses record={record} />

      <section className="panel playback-panel">
        <div className="row" style={{ marginBottom: '0.4rem' }}>
          <h2 style={{ margin: 0, fontSize: '0.95rem' }}>Playback</h2>
          <div className="spacer" />
          <span className="faint small">
            {view.steps.length} loop steps · {view.panel.length} on the panel ·{' '}
            {(record.personas_consulted ?? []).length} consulted
          </span>
        </div>
        <PlaybackControls playback={playback} />
      </section>

      <section className="panel">
        <header>
          <h2>Agent activity by loop step</h2>
          <p className="subtitle">
            Logical loop steps, not wall-clock time. Step indices are deterministic and
            reproducible from config plus seed; there is no per-call timing in the record and
            there should not be, because capturing it would mean persisting every prompt.
            Panel members who were never consulted keep their row, greyed.
          </p>
        </header>
        <LoopGantt
          steps={view.steps}
          nodes={view.graph.nodes}
          cursor={playback.cursor}
          onSelect={playback.seek}
          onSelectAgent={setAgentId}
          selectedAgent={agentId}
        />
      </section>

      <div className="detail-grid">
        <section className="panel">
          <header>
            <h2>Interaction graph</h2>
            <p className="subtitle">
              Edges appear in loop order as the cursor advances. Declining is styled apart
              from never being asked: it is a substantive act, and the escape hatch firing is
              the honest outcome rather than a gap in the data.
            </p>
          </header>
          <InteractionGraphView
            nodes={view.graph.nodes}
            edges={view.graph.edges}
            hallucinated={view.graph.hallucinated_ids ?? []}
            cursor={playback.cursor}
            onSelectAgent={setAgentId}
            selectedAgent={agentId}
          />
        </section>

        <section className="panel">
          <header>
            <h2>Event log</h2>
            <p className="subtitle">
              What each role produced, in loop order. The analytical question is repeated on
              every consultation and reply — it is recorded output, written by the Advisor.
              The <em>prompts</em> are a different thing and are not here: they are not in the
              record and do not leave the process.
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

      <AgentPanel
        agent={(view.agents ?? []).find((a) => a.id === agentId) ?? null}
        onClose={() => setAgentId(null)}
      />

      <section className="panel">
        <header>
          <div className="row">
            <h2 style={{ margin: 0 }}>Host ground truth</h2>
            <div className="spacer" />
            <button className={reveal ? 'danger small' : 'small'} onClick={() => setReveal(!reveal)}>
              {reveal ? 'Hide' : 'Reveal'}
            </button>
          </div>
          <p className="subtitle">
            What was actually happening. <strong>No agent in this simulation saw it.</strong>{' '}
            It exists so misperception can be scored after the fact, not so anyone in the loop
            could be correct — and the gap between it and the intelligence brief above is the
            thing worth looking at.
          </p>
        </header>

        {reveal && view.host_ground_truth ? (
          <>
            <div className="banner warn">
              <strong>HOST-ONLY</strong>
              {view.host_only_note}
            </div>
            {Object.entries(view.host_ground_truth).map(([eventId, truth]) => (
              <div key={eventId} style={{ marginBottom: '0.75rem' }}>
                <h4>{eventId}</h4>
                <p className="muted small">{truth}</p>
              </div>
            ))}
          </>
        ) : (
          <p className="faint small">Withheld. Press reveal to see it.</p>
        )}
      </section>
    </>
  )
}
