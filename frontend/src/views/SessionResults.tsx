/**
 * Session results, in the order `docs/framework/measurement.md` requires them to be read.
 *
 * Provenance and warnings come **above** the charts, not in a footer, because they are gates
 * on interpretation rather than footnotes. Then the distributions, because the distribution
 * is the result. Then the contrasts, because they are the only interpretable quantity.
 * Everything after that is secondary and is labelled as such.
 */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import ArmComparison from '../components/ArmComparison'
import EngagementTable from '../components/EngagementTable'
import InfluencePanel from '../components/InfluencePanel'
import PipelineSankey from '../components/PipelineSankey'
import ProvenanceBanner from '../components/ProvenanceBanner'
import RungHistogram from '../components/RungHistogram'
import TermCloud from '../components/TermCloud'
import WarningList from '../components/WarningList'
import { percent } from '../lib/format'
import type { RepresentativeView } from '../types/api'
import type { SessionSummary } from '../types/artsoc'

export default function SessionResults() {
  const { sessionId = '' } = useParams()
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [detail, setDetail] = useState<RepresentativeView | null>(null)
  const [focusArm, setFocusArm] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const loaded = await api.summary(sessionId)
        setSummary(loaded)
        // Default the secondary panels to a full-loop arm: the control consults nobody, so
        // engagement and term frequency would be empty and read as a bug rather than as the
        // control arm doing exactly what it is for.
        const consulted = loaded.arms.find((a) => a.consulted_panel) ?? loaded.arms[0]
        setFocusArm(consulted?.arm ?? '')
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [sessionId])

  useEffect(() => {
    if (!focusArm) return
    setDetail(null)
    void (async () => {
      try {
        setDetail(await api.representative(sessionId, focusArm))
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [sessionId, focusArm])

  if (error) {
    return (
      <div className="banner danger">
        <strong>COULD NOT LOAD THIS SESSION</strong>
        {error}
      </div>
    )
  }
  if (!summary) return <p className="empty">Loading…</p>

  const arms = summary.arms
  const focus = arms.find((a) => a.arm === focusArm)
  const records = detail?.representative.record ? [detail.representative.record] : []

  return (
    <>
      <div className="row">
        <h1 style={{ margin: 0 }}>{summary.label || 'Session'}</h1>
        <span className="faint mono small">{summary.session_id.slice(0, 8)}</span>
        <div className="spacer" />
        <Link to="/sessions">
          <button className="ghost small">All sessions</button>
        </Link>
      </div>

      <section className="panel">
        <header>
          <h2>How this may and may not be read</h2>
        </header>
        <ProvenanceBanner summary={summary} />
        <h4 style={{ marginTop: '1rem' }}>Diagnostics</h4>
        <WarningList warnings={summary.warnings ?? []} />
      </section>

      <section className="panel">
        <header>
          <h2>Rung distributions</h2>
          <p className="subtitle">
            The distribution is the result. A single replication reaching a nuclear rung is an
            anecdote; the proportion of n that crossed the threshold is a finding — and even
            that is only interpretable as a delta against the control.
          </p>
        </header>

        <div className="grid two">
          {arms.map((arm) => (
            <div key={arm.arm}>
              <div className="row">
                <h3 style={{ margin: 0 }}>{arm.arm}</h3>
                {arm.arm === summary.control_arm && <span className="pill control">control</span>}
                <div className="spacer" />
                <span className="mono small faint">n={arm.n}</span>
              </div>
              <RungHistogram distribution={arm.rung_distribution} n={arm.n} compact />
              <p className="small faint">
                mean {arm.mean_rung.toFixed(3)} · median {arm.median_rung} · P(nuclear){' '}
                {percent(arm.p_nuclear)}
                {arm.consulted_panel ? (
                  <>
                    {' '}· panel {arm.declared_panel_size}, {percent(arm.mean_run_coverage, 0)}{' '}
                    consulted per run · out-of-record {percent(arm.out_of_record_rate, 1)}
                  </>
                ) : (
                  ' · no panel consulted (control)'
                )}
              </p>
            </div>
          ))}
        </div>
      </section>

      <ArmComparison
        arms={arms}
        deltas={summary.deltas}
        controlArm={summary.control_arm ?? 'escalation_prior'}
        hasControl={summary.has_control ?? false}
      />

      <section className="panel">
        <header>
          <div className="row">
            <h2 style={{ margin: 0 }}>Arm detail</h2>
            <div className="spacer" />
            <label htmlFor="focus" style={{ margin: 0 }}>
              showing
            </label>
            <select
              id="focus"
              value={focusArm}
              style={{ width: 'auto' }}
              onChange={(e) => setFocusArm(e.target.value)}
            >
              {arms.map((arm) => (
                <option key={arm.arm} value={arm.arm}>
                  {arm.arm}
                </option>
              ))}
            </select>
          </div>
          <p className="subtitle">
            Everything below describes one arm. None of it is a contrast, so none of it is a
            finding on its own.
          </p>
        </header>

        {focus && !focus.consulted_panel && (
          <div className="banner info">
            <strong>NO PANEL IN THIS ARM</strong>
            <code>{focus.arm}</code> runs the President and the intelligence brief alone. That
            is what makes it the control; the empty panels below are correct, not missing data.
          </div>
        )}
      </section>

      {detail ? (
        <>
          <section className="panel">
            <header>
              <h2>{detail.flow.label}</h2>
              <p className="subtitle">
                What varied upstream of each terminal rung across {detail.flow.n_records}{' '}
                replications of {detail.arm}. Not an escalation path: phase 1 makes one
                decision per replication, so there is no sequence of rungs to draw.
              </p>
            </header>
            <PipelineSankey flow={detail.flow} />
          </section>

          <TermCloud records={records} mock={summary.mock ?? false} />

          <EngagementTable engagement={detail.engagement} />

          <section className="panel">
            <header>
              <h2>Illustrative single run</h2>
              <p className="subtitle">{detail.representative.selection_note}</p>
            </header>
            <div className="row">
              <span className="muted small">
                seed {detail.representative.record.seed} · rung{' '}
                {detail.representative.record.rung} ·{' '}
                {detail.representative.record.action.action}
              </span>
              <div className="spacer" />
              <Link to={`/sessions/${sessionId}/runs/${detail.arm}`}>
                <button className="primary small">Open the loop for this run</button>
              </Link>
            </div>
          </section>
        </>
      ) : (
        <p className="empty">Loading arm detail…</p>
      )}

      <InfluencePanel arms={arms} />
    </>
  )
}
