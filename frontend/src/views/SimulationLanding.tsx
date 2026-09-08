/**
 * One simulation, at a glance: the situation, how the society responded, and two ways in.
 *
 * The three-line summary is generated prose and is labelled as interpretation. Every number
 * beside it comes from `views.session_facts`, which reads the record — so the prose never
 * has to state a count it could get wrong, and the two can be checked against each other.
 *
 * The theorist line says **whose opinions the chosen course of action cited**. That is a
 * recorded property of the document the Advisor wrote, not a measure of what anyone
 * changed, and it is worded that way. Causal attribution needs the `loo_*` forced-exclusion
 * arms, where the persona is absent from the panel, every roster and every prompt; when
 * those are in the session the influence panel on the macro page carries it.
 */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import Conditions from '../components/Conditions'
import { humanise, percent, signed } from '../lib/format'
import type { LandingView } from '../types/artsoc'

export default function SimulationLanding() {
  const { sessionId = '' } = useParams()
  const [view, setView] = useState<LandingView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    void (async () => {
      try {
        setView(await api.landing(sessionId))
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [sessionId])

  const generate = async () => {
    if (!view) return
    setGenerating(true)
    try {
      const analysis = await api.analysis(sessionId, view.arm)
      setView({ ...view, analysis })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setGenerating(false)
    }
  }

  if (error) {
    return (
      <div className="notice stop">
        <strong>Could not load this simulation</strong>
        {error}
      </div>
    )
  }
  if (!view) return <p className="spin">Loading…</p>

  const { facts, scenario, summary, coa_support: support } = view
  const blocked = summary.mock || summary.smoke_test || !summary.has_control
  const top = support.personas.filter((p) => p.runs_in_chosen > 0).slice(0, 3)

  return (
    <>
      <div className="crumb">
        <Link to="/">All simulations</Link>
        <span>/</span>
        <span>{view.label || view.session_id.slice(0, 8)}</span>
      </div>

      <header className="section">
        <h1>{scenario?.label ?? view.facts.arm}</h1>
        <p className="muted">
          {scenario ? (
            <>
              {scenario.description}
            </>
          ) : (
            'The scenario file for this session is no longer on disk.'
          )}
        </p>
        <p className="faint small">
          {facts.n} replications of <code>{facts.arm}</code>
          {facts.control_arm ? (
            <>
              {' '}
              against <code>{facts.control_arm}</code>
            </>
          ) : (
            ' · no control arm'
          )}{' '}
          · {scenario?.self_nation} observing {scenario?.adversary_nation}
        </p>
      </header>

      {blocked && <BlockingNotices summary={summary} />}

      <section className="section">
        <h4>How the society responded</h4>
        {view.analysis && (view.analysis.sentences ?? []).length > 0 ? (
          <>
            <p className="lede">{(view.analysis.sentences ?? []).join(' ')}</p>
            <p className="lede-source">{view.analysis.caveat}</p>
          </>
        ) : (
          <>
            <p className="lede">
              The panel was consulted in {percent(facts.mean_run_coverage ?? 0, 0)} of its{' '}
              {facts.declared_panel_size}-persona roster per run, declining{' '}
              {percent(facts.out_of_record_rate ?? 0, 0)} of the questions put to it. The President
              chose {humanise(facts.modal_action)} most often, in{' '}
              {percent(facts.modal_action_share, 0)} of replications.
              {facts.d_mean_rung !== null && facts.d_mean_rung !== undefined
                ? ` That sits ${signed(facts.d_mean_rung, 2)} rungs against the control.`
                : ' No control arm was run, so nothing here is interpretable.'}
            </p>
            <button onClick={() => void generate()} disabled={generating}>
              {generating ? 'Reading the figures…' : 'Generate a written summary'}
            </button>
            <p className="faint tiny" style={{ marginTop: '0.5rem' }}>
              The lines above are read directly from the record. A written summary is one
              model call over the same figures, cached afterwards.
            </p>
          </>
        )}
      </section>

      <section className="section">
        <div className="figures">
          <Figure
            value={facts.mean_rung.toFixed(2)}
            label="Mean rung"
            delta={facts.d_mean_rung}
            deltaFormat={(v) => `${signed(v, 2)} vs control`}
            note={facts.control_arm ? undefined : 'no control run'}
          />
          <Figure
            value={percent(facts.p_nuclear, 1)}
            label="P(nuclear)"
            nuclear={facts.p_nuclear > 0}
            delta={facts.d_p_nuclear}
            deltaFormat={(v) => `${signed(v * 100, 2)}pp vs control`}
            note={facts.control_arm ? undefined : 'no control run'}
          />
          <Figure
            value={humanise(facts.modal_action)}
            label="Most chosen"
            note={`${percent(facts.modal_action_share, 0)} of ${facts.n} runs`}
          />
          <Figure
            value={percent(facts.out_of_record_rate ?? 0, 0)}
            label="Declined"
            note="questions outside a persona's record"
          />
        </div>
      </section>

      <section className="section">
        <h4>Whose positions the chosen option cited</h4>
        {top.length === 0 ? (
          <p className="muted small">
            {facts.n_with_coas === 0
              ? 'This arm proposed no courses of action, so there is nothing for a chosen option to have rested on. Either it is the control arm, which consults no panel, or it predates ADR 0006.'
              : 'No course of action cited a theorist in this sweep.'}
          </p>
        ) : (
          <>
            <p className="muted">
              {top.map((person, i) => (
                <span key={person.persona_id}>
                  {i > 0 && (i === top.length - 1 ? ', and ' : ', ')}
                  <strong>{person.name}</strong> in {percent(person.share_of_chosen, 0)}
                </span>
              ))}{' '}
              of the {facts.n_with_coas} replications where an option was chosen.
            </p>
            <p className="lede-source">{support.note}</p>
          </>
        )}
      </section>

      <nav className="entries">
        <Link className="entry" to={`/sessions/${sessionId}/macro`}>
          <h2>
            Across all runs <span className="arrow">&rarr;</span>
          </h2>
          <p>
            The distribution the sweep produced, the contrast against the control, and which
            courses of action were proposed against which were taken.
          </p>
          <p className="contents">
            Rung distributions · course-of-action spread · contrasts · panel engagement ·
            written interpretation and follow-up questions
          </p>
        </Link>

        <Link className="entry" to={`/sessions/${sessionId}/run/${view.arm}`}>
          <h2>
            One run in full <span className="arrow">&rarr;</span>
          </h2>
          <p>
            A single representative replication, step by step: who was asked, what they said,
            and what the decision rested on.
          </p>
          <p className="contents">
            Interactive panel · per-theorist detail · provenance from source text to decision
            · playback timeline
          </p>
        </Link>
      </nav>

      <hr className="rule" />
      <Conditions summary={summary} />
    </>
  )
}

function Figure({
  value,
  label,
  note,
  delta,
  deltaFormat,
  nuclear,
}: {
  value: string
  label: string
  note?: string
  delta?: number | null
  deltaFormat?: (value: number) => string
  nuclear?: boolean
}) {
  return (
    <div className="figure">
      <div
        className={`value${nuclear ? ' nuclear' : ''}`}
        style={value.length > 12 ? { fontSize: '1.1rem', lineHeight: 1.3 } : undefined}
      >
        {value}
      </div>
      <div className="label">{label}</div>
      {delta !== null && delta !== undefined && deltaFormat && (
        <div className="delta">{deltaFormat(delta)}</div>
      )}
      {note && <div className="note">{note}</div>}
    </div>
  )
}

/**
 * The three things that stop a number on this page being read as a result.
 *
 * Above the figures, not below them: `docs/framework/measurement.md` treats these as gates
 * on interpretation rather than footnotes.
 */
function BlockingNotices({ summary }: { summary: LandingView['summary'] }) {
  const models = [...new Set(Object.values(summary.models ?? {}))]
  return (
    <>
      {summary.mock && (
        <div className="notice stop">
          <strong>Mock backend — not a result</strong>
          Responses are deliberately content-nonsense. Arms differ here only because their
          prompts hash differently, and nothing on this page is a finding about nuclear
          strategists.
        </div>
      )}
      {summary.smoke_test && (
        <div className="notice stop">
          <strong>Smoke test — not a result</strong>
          Every role was served by {models[0]}. <code>models_override</code> pins the
          presidential decision — the primary metric — to the same cheap model as everything
          else, so this measures something different from a run without it.
        </div>
      )}
      {!summary.has_control && (
        <div className="notice stop">
          <strong>No control arm</strong>
          <code>{summary.control_arm}</code> was not run, so nothing here is interpretable.
          Absolute escalation rates are not findings — base models escalate in wargame
          settings from neutral starting conditions — and only the delta against the control
          means anything.
        </div>
      )}
    </>
  )
}
