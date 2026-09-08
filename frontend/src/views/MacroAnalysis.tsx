/**
 * The sweep, read in the order `docs/framework/measurement.md` requires.
 *
 * Diagnostics first, because they gate whether anything below may be read. Then the
 * distributions, because the distribution is the result. Then the contrasts, because they
 * are the only interpretable quantity. Everything after is secondary and says so.
 */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import AnalysisPanel from '../components/AnalysisPanel'
import CoaDistribution from '../components/CoaDistribution'
import Conditions from '../components/Conditions'
import EngagementTable from '../components/EngagementTable'
import InfluencePanel from '../components/InfluencePanel'
import RungHistogram from '../components/RungHistogram'
import { RUNG_LABELS, percent, signed, signedPercent } from '../lib/format'
import type { LandingView, RepresentativeView, SessionSummary } from '../types/artsoc'

export default function MacroAnalysis() {
  const { sessionId = '' } = useParams()
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [landing, setLanding] = useState<LandingView | null>(null)
  const [detail, setDetail] = useState<RepresentativeView | null>(null)
  const [arm, setArm] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const [loaded, land] = await Promise.all([
          api.summary(sessionId),
          api.landing(sessionId),
        ])
        setSummary(loaded)
        setLanding(land)
        setArm(land.arm)
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [sessionId])

  useEffect(() => {
    if (!arm) return
    setDetail(null)
    void (async () => {
      try {
        setDetail(await api.representative(sessionId, arm))
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [sessionId, arm])

  // Re-fetch the landing figures when the focused arm changes: the facts, the
  // course-of-action spread and the cached interpretation are all per-arm.
  useEffect(() => {
    if (!arm || !landing || landing.arm === arm) return
    void (async () => {
      try {
        setLanding(await api.landing(sessionId, arm))
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [sessionId, arm, landing])

  if (error) {
    return (
      <div className="notice stop">
        <strong>Could not load this session</strong>
        {error}
      </div>
    )
  }
  if (!summary || !landing) return <p className="spin">Loading…</p>

  const warnings = summary.warnings ?? []
  const severe = ['NOT GROUNDED', 'SMOKE TEST', 'MOCK BACKEND', 'NO CONTROL ARM', 'NOMINAL PANEL']
  const focus = summary.arms.find((a) => a.arm === arm)

  return (
    <>
      <div className="crumb">
        <Link to="/">All simulations</Link>
        <span>/</span>
        <Link to={`/sessions/${sessionId}`}>{summary.label || summary.session_id.slice(0, 8)}</Link>
        <span>/</span>
        <span>Across all runs</span>
      </div>

      <header className="section">
        <h1>Across all runs</h1>
        <p className="subtitle">
          {summary.arms.reduce((n, a) => n + a.n, 0)} replications over{' '}
          {summary.arms.length} arm{summary.arms.length === 1 ? '' : 's'} of{' '}
          <code>{summary.scenario_id}</code>.
        </p>
      </header>

      <section className="section">
        <h4>What gates reading these figures</h4>
        {warnings.length === 0 ? (
          <p className="faint small">
            No diagnostics were raised. That is not the same as a result being interpretable —
            see the contrasts below.
          </p>
        ) : (
          <ul className="diagnostics">
            {warnings.map((warning) => (
              <li key={warning} className={severe.some((s) => warning.startsWith(s)) ? 'severe' : ''}>
                {warning}
              </li>
            ))}
          </ul>
        )}
      </section>

      <hr className="rule" />

      <section className="section">
        <header>
          <h2>Where the decisions landed</h2>
          <p className="subtitle">
            The distribution is the result. A single replication reaching a nuclear rung is an
            anecdote; the proportion of n that crossed the threshold is a finding — and even
            that is only interpretable as a delta against the control.
          </p>
        </header>

        <div className="grid two">
          {summary.arms.map((a) => (
            <div key={a.arm}>
              <div className="row tight" style={{ marginBottom: '0.4rem' }}>
                <h3 style={{ margin: 0 }}>{a.arm}</h3>
                {a.arm === summary.control_arm && <span className="tag accent">control</span>}
                <div className="spacer" />
                <span className="mono tiny faint">n={a.n}</span>
              </div>
              <RungHistogram distribution={a.rung_distribution} n={a.n} />
              <p className="tiny faint" style={{ marginTop: '0.2rem' }}>
                mean {a.mean_rung.toFixed(2)} · median {a.median_rung} · P(nuclear){' '}
                {percent(a.p_nuclear)}
                {a.consulted_panel
                  ? ` · ${percent(a.mean_run_coverage, 0)} of the panel consulted per run · ${percent(a.out_of_record_rate, 0)} declined`
                  : ' · no panel consulted'}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <header>
          <h2>Contrasts against {summary.control_arm}</h2>
          <p className="subtitle">
            Only these deltas are interpretable. The absolute distributions above are the base
            model&rsquo;s escalation prior, not a finding about nuclear strategists — models
            escalate in wargame settings from neutral starting conditions, so what the advisory
            apparatus changed is the only part attributable to this design.
          </p>
        </header>

        {!summary.has_control ? (
          <div className="notice stop">
            <strong>Nothing here is interpretable</strong>
            The control arm was not run, so there is nothing to contrast against and no number
            on this page may be reported.
          </div>
        ) : summary.deltas.length === 0 ? (
          <p className="empty">Only the control was run. Add a full-loop arm to have a contrast.</p>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>arm</th>
                  <th className="num">n</th>
                  <th className="num">mean rung</th>
                  <th className="num">&Delta; mean rung</th>
                  <th className="num">P(nuclear)</th>
                  <th className="num">&Delta; P(nuclear)</th>
                  <th>modal rung</th>
                </tr>
              </thead>
              <tbody>
                {summary.deltas.map((d) => {
                  const a = summary.arms.find((x) => x.arm === d.arm)
                  return (
                    <tr key={d.arm}>
                      <td>{d.arm}</td>
                      <td className="num">{a?.n ?? '—'}</td>
                      <td className="num faint">{a?.mean_rung.toFixed(3) ?? '—'}</td>
                      <td className="num">{signed(d.d_mean_rung)}</td>
                      <td className="num faint">{a ? percent(a.p_nuclear) : '—'}</td>
                      <td className="num">{signedPercent(d.d_p_nuclear)}</td>
                      <td className="faint small">{a ? modal(a) : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {summary.deltas.length > 1 && (
          <p className="faint tiny" style={{ marginTop: '0.75rem' }}>
            Point differences. No confidence intervals and no multiple-comparisons correction:
            with many arms a largest delta exists whether or not one is real, so read the
            ranking descriptively.
          </p>
        )}
      </section>

      <hr className="rule" />

      <section className="section">
        <header>
          <div className="row">
            <h2 style={{ margin: 0 }}>One arm in detail</h2>
            <div className="spacer" />
            {summary.arms.map((a) => (
              <button
                key={a.arm}
                className={`chip${a.arm === arm ? ' on' : ''}`}
                onClick={() => setArm(a.arm)}
              >
                {a.arm}
              </button>
            ))}
          </div>
          <p className="subtitle">
            Everything below describes one arm. None of it is a contrast, so none of it is a
            finding on its own.
          </p>
        </header>

        {focus && !focus.consulted_panel && (
          <div className="notice info">
            <strong>No panel in this arm</strong>
            <code>{focus.arm}</code> runs the President and the intelligence brief alone. That
            is what makes it the control; the empty panels below are correct, not missing data.
          </div>
        )}
      </section>

      {landing.arm === arm && (landing.facts.n_with_coas ?? 0) > 0 && (
        <section className="section">
          <header>
            <h2>Courses of action</h2>
            <p className="subtitle">
              The Advisor proposes three options per replication and the President takes one.
              An action proposed often and taken rarely is one the panel kept raising and the
              President kept declining — which is why the two counts are never merged.
            </p>
          </header>
          <CoaDistribution
            actions={landing.facts.actions ?? []}
            n={landing.facts.n}
            nWithCoas={landing.facts.n_with_coas ?? 0}
          />
        </section>
      )}

      {detail && (
        <>
          <EngagementTable engagement={detail.engagement} />
          <hr className="rule" />
        </>
      )}

      <InfluencePanel arms={summary.arms} />

      <hr className="rule" />

      <AnalysisPanel
        sessionId={sessionId}
        arm={arm}
        initial={landing.arm === arm ? landing.analysis ?? null : null}
        mock={summary.mock ?? false}
      />

      <hr className="rule" />

      <section className="section">
        <p className="muted small">
          <Link to={`/sessions/${sessionId}/run/${arm}`}>
            Open one representative run of {arm} &rarr;
          </Link>
        </p>
      </section>

      <Conditions summary={summary} />
    </>
  )
}

function modal(arm: SessionSummary['arms'][number]): string {
  const entries = Object.entries(arm.rung_distribution)
  if (entries.length === 0) return '—'
  const [rung, count] = entries.reduce((best, current) => (current[1] > best[1] ? current : best))
  return `${rung} — ${RUNG_LABELS[Number(rung)] ?? ''} (${count}/${arm.n})`
}
