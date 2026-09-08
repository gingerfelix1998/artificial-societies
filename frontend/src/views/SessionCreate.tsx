/**
 * Create a session: pick a scenario, pick arms, confirm the cost.
 *
 * **Nothing here varies an experimental parameter.** Every control selects among committed
 * configs — a scenario file and some arm files. `n`, `seed0` and where output goes are the
 * only operational choices, which is the same line `artsoc run` draws (invariant 5). A
 * control that let a viewer construct a configuration no file in `configs/` describes would
 * break that by another route and make the results untraceable.
 *
 * **The control arm is pre-selected and locked.** Absolute escalation rates are not
 * findings, so a session without `escalation_prior` produces nothing interpretable. Making
 * it optional would mean offering a session that cannot be read.
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useSessions } from '../context/SessionContext'
import { titleCase } from '../lib/format'
import type { ArmInfo, CallEstimate, ScenarioInfo } from '../types/api'

const CONTROL_ARM = 'escalation_prior'

export default function SessionCreate() {
  const navigate = useNavigate()
  const { start } = useSessions()

  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([])
  const [arms, setArms] = useState<ArmInfo[]>([])
  const [scenarioId, setScenarioId] = useState<string>('')
  const [selected, setSelected] = useState<string[]>([CONTROL_ARM, 'baseline'])
  const [n, setN] = useState(100)
  const [seed0, setSeed0] = useState(1)
  const [label, setLabel] = useState('')
  const [estimate, setEstimate] = useState<CallEstimate | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showExclusion, setShowExclusion] = useState(false)

  useEffect(() => {
    void (async () => {
      try {
        const loaded = await api.scenarios()
        setScenarios(loaded)
        setScenarioId((current) => current || loaded[0]?.scenario_id || '')
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [])

  useEffect(() => {
    if (!scenarioId) return
    void (async () => {
      try {
        setArms(await api.arms(scenarioId))
      } catch (e) {
        setError((e as Error).message)
      }
    })()
  }, [scenarioId])

  const spec = useMemo(
    () => ({ label, scenario_id: scenarioId, arms: selected, n, seed0 }),
    [label, scenarioId, selected, n, seed0],
  )

  // Re-priced whenever the spec changes, so the estimate on screen always describes the
  // session the button would start.
  useEffect(() => {
    setEstimate(null)
    if (!scenarioId || selected.length === 0 || n < 1) return
    let stale = false
    void (async () => {
      try {
        const priced = await api.estimate(spec)
        if (!stale) setEstimate(priced)
      } catch (e) {
        if (!stale) setError((e as Error).message)
      }
    })()
    return () => {
      stale = true
    }
  }, [spec, scenarioId, selected.length, n])

  const scenario = scenarios.find((s) => s.scenario_id === scenarioId)
  const core = arms.filter((a) => !a.is_exclusion_arm)
  const exclusion = arms.filter((a) => a.is_exclusion_arm)

  const toggle = (arm: string) => {
    if (arm === CONTROL_ARM) return
    setSelected((current) =>
      current.includes(arm) ? current.filter((a) => a !== arm) : [...current, arm],
    )
  }

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const sessionId = await start(spec)
      navigate(`/sessions/${sessionId}/running`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <>
      <h1>New session</h1>
      <p className="muted small" style={{ maxWidth: '70ch' }}>
        A session runs several arms over one scenario and contrasts them. Arms are config
        files in <code>configs/arms/</code>; this page selects among them and cannot define
        one.
      </p>

      {error && (
        <div className="banner danger">
          <strong>REQUEST FAILED</strong>
          {error}
        </div>
      )}

      <section className="panel">
        <header>
          <h2>Scenario</h2>
          <p className="subtitle">
            One injected event, deliberately ambiguous. An unambiguous event is decided by
            the intelligence brief alone and the panel stops mattering.
          </p>
        </header>
        <div className="grid three">
          {scenarios.map((s) => (
            <button
              key={s.scenario_id}
              className={`card ${s.scenario_id === scenarioId ? 'selected' : ''}`}
              onClick={() => setScenarioId(s.scenario_id)}
            >
              <h3>{s.label}</h3>
              <span className="pill">
                {s.self_nation} vs {s.adversary_nation}
              </span>
              <p className="why">{s.description}</p>
            </button>
          ))}
        </div>
        {scenario && (scenario.observable_signature ?? []).length > 0 && (
          <details className="small" style={{ marginTop: '0.75rem' }}>
            <summary className="muted">
              What collection could see ({(scenario.observable_signature ?? []).length} indicators)
            </summary>
            <ul className="muted small" style={{ marginTop: '0.4rem' }}>
              {(scenario.observable_signature ?? []).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <p className="faint small">
              The signature is consistent with more than one reading. What is actually
              happening is host-only and reaches no agent in the simulation.
            </p>
          </details>
        )}
      </section>

      <section className="panel">
        <header>
          <h2>Arms</h2>
          <p className="subtitle">
            <code>{CONTROL_ARM}</code> is the control and is locked on: every interpretable
            number is a delta against it, so a session without it produces nothing that may
            be reported.
          </p>
        </header>

        <div className="grid three">
          {core.map((arm) => (
            <button
              key={arm.arm}
              className={`card ${selected.includes(arm.arm) ? 'selected' : ''} ${
                arm.is_control ? 'locked' : ''
              }`}
              onClick={() => toggle(arm.arm)}
              disabled={arm.is_control}
            >
              <div className="row">
                <h3 style={{ margin: 0 }}>{arm.arm}</h3>
                {arm.is_control && <span className="pill control">control · locked</span>}
              </div>
              <p className="why">{arm.notes}</p>
              <p className="varies">
                {Object.keys(arm.varies).length === 0
                  ? 'base defaults'
                  : Object.entries(arm.varies)
                      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                      .join(', ')}
              </p>
            </button>
          ))}
        </div>

        {exclusion.length > 0 && (
          <div style={{ marginTop: '1rem' }}>
            <button className="ghost small" onClick={() => setShowExclusion((v) => !v)}>
              {showExclusion ? 'Hide' : 'Show'} the {exclusion.length} forced-exclusion arms
            </button>
            <p className="faint small" style={{ marginTop: '0.4rem', maxWidth: '80ch' }}>
              Each removes one theorist from the panel, every roster and every prompt. This
              is what makes per-theorist influence causal rather than observational — but
              their contrast is against each other, not against the control, because every
              one of them runs a panel one smaller than baseline. Running them multiplies the
              session cost by their number.
            </p>
            {showExclusion && (
              <div className="grid three" style={{ marginTop: '0.75rem' }}>
                {exclusion.map((arm) => (
                  <button
                    key={arm.arm}
                    className={`card ${selected.includes(arm.arm) ? 'selected' : ''}`}
                    onClick={() => toggle(arm.arm)}
                  >
                    <div className="row">
                      <h3 style={{ margin: 0 }}>{arm.arm}</h3>
                      <span className="pill loo">exclusion</span>
                    </div>
                    <p className="varies">
                      excludes {String(arm.varies.excluded_personas ?? '')}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      <section className="panel">
        <header>
          <h2>Replications</h2>
        </header>
        <div className="grid three">
          <div>
            <label htmlFor="n">replications per arm</label>
            <input
              id="n"
              type="number"
              min={1}
              value={n}
              onChange={(e) => setN(Math.max(1, Number(e.target.value) || 1))}
            />
            <p className="faint small" style={{ marginTop: '0.35rem' }}>
              P(nuclear) is a rare-event rate. Detecting a change in a 3% event needs far
              more than 100 replications; a mean-rung contrast needs fewer.
            </p>
          </div>
          <div>
            <label htmlFor="seed0">first seed</label>
            <input
              id="seed0"
              type="number"
              value={seed0}
              onChange={(e) => setSeed0(Number(e.target.value) || 1)}
            />
            <p className="faint small" style={{ marginTop: '0.35rem' }}>
              Seeds run consecutively, so a sweep is reproducible from two integers.
            </p>
          </div>
          <div>
            <label htmlFor="label">label</label>
            <input
              id="label"
              type="text"
              value={label}
              placeholder="what this session is for"
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
        </div>
      </section>

      <CostGate estimate={estimate} />

      <div className="row">
        <button
          className="primary"
          disabled={busy || !estimate || selected.length === 0}
          onClick={() => void submit()}
        >
          {busy ? 'Starting…' : `Confirm and run ${estimate?.total_calls.toLocaleString() ?? '—'} calls`}
        </button>
        <span className="faint small">
          Nothing is sent until this is pressed. The estimate above describes exactly this
          session.
        </span>
      </div>
    </>
  )
}

/**
 * The cost gate.
 *
 * Call counts rather than a dollar total: tokens per call vary by an order of magnitude
 * across roles and are not known until something has run, so a pre-run USD figure would be
 * the most quotable invented number on the page. Actual spend is metered per replication
 * while the session runs.
 */
function CostGate({ estimate }: { estimate: CallEstimate | null }) {
  if (!estimate) {
    return (
      <section className="panel">
        <p className="empty">Pricing this session…</p>
      </section>
    )
  }

  const live = estimate.backend !== 'mock'

  // Every role resolving to one model on a live backend means `models_override` is set in
  // configs/base.yaml. That pins the presidential decision — the primary metric — to the
  // same cheap model as everything else, so the session measures something different from
  // one without it. Worth saying before the money is spent rather than only afterwards.
  const models = new Set(estimate.arms.flatMap((arm) => arm.roles.map((role) => role.model)))
  const roleCount = Math.max(...estimate.arms.map((arm) => arm.roles.length))
  const overridden = live && models.size === 1 && roleCount > 1

  return (
    <section className="panel">
      <header>
        <h2>What this will cost</h2>
      </header>

      <div className={`banner ${live ? 'warn' : 'info'}`}>
        <strong>{live ? 'THIS SPENDS REAL MONEY' : 'MOCK BACKEND — FREE'}</strong>
        Backend <code>{estimate.backend}</code>, from <code>configs/base.yaml</code>. Up to{' '}
        {estimate.total_calls.toLocaleString()} provider calls. {estimate.note}
      </div>

      {overridden && (
        <div className="banner danger">
          <strong>THIS WILL PRODUCE A SMOKE TEST, NOT A RESULT</strong>
          Every role resolves to <code>{[...models][0]}</code>, which means{' '}
          <code>models_override</code> is set in <code>configs/base.yaml</code>. It pins the
          presidential decision — the primary metric — to the same cheap model as everything
          else, so this session measures something different from one without it rather than
          being a cheaper version of the same experiment. Remove that line before collecting
          anything you intend to report.
        </div>
      )}

      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>arm</th>
              <th className="num">n</th>
              <th className="num">calls / replication</th>
              <th className="num">calls</th>
              <th>models, by role</th>
            </tr>
          </thead>
          <tbody>
            {estimate.arms.map((arm) => (
              <tr key={arm.arm}>
                <td>
                  {arm.arm}
                  {!arm.consult_panel && <span className="faint"> · no panel</span>}
                </td>
                <td className="num">{arm.n}</td>
                <td className="num">{arm.calls_per_replication}</td>
                <td className="num">{arm.total_calls.toLocaleString()}</td>
                <td className="small faint" style={{ textAlign: 'left' }}>
                  {arm.roles.map((role) => (
                    <div key={role.role}>
                      {titleCase(role.role)} &rarr; {role.model} &times;{' '}
                      {role.calls.toLocaleString()}
                      {role.usd_per_mtok_in !== null && role.usd_per_mtok_in !== undefined && (
                        <span>
                          {' '}
                          (${role.usd_per_mtok_in}/${role.usd_per_mtok_out} per Mtok)
                        </span>
                      )}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
