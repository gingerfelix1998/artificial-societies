/**
 * What produced these numbers, above the charts rather than under them.
 *
 * `docs/framework/measurement.md` treats provenance as a gate on interpretation, not a
 * footnote. A rung distribution copied out of this UI without knowing the backend, whether
 * retrieval was grounded, and which model served the presidential decision would be read as
 * a claim about what nuclear strategists would do — which it is not.
 *
 * The two loud cases are flagged by the server from what actually ran, never from what the
 * config asked for:
 *
 * - **mock** — output is `MOCK:`-prefixed nonsense by design. Arms differ only because
 *   their prompts hash differently.
 * - **smoke test** — every role served by one model, which means `models_override` pinned
 *   the presidential decision to the same cheap model as everything else. That measures
 *   something different from a run without it, not a cheaper version of the same thing.
 */

import type { SessionSummary } from '../types/artsoc'

export default function ProvenanceBanner({ summary }: { summary: SessionSummary }) {
  const models = summary.models ?? {}
  const distinct = [...new Set(Object.values(models))]

  return (
    <>
      {summary.mock && (
        <div className="banner danger">
          <strong>MOCK BACKEND — NOT A RESULT</strong>
          Responses are deliberately content-nonsense. Arms differ here only because their
          prompts hash differently. Nothing on this page is a finding about nuclear
          strategists.
        </div>
      )}

      {summary.smoke_test && (
        <div className="banner danger">
          <strong>SMOKE TEST — NOT A RESULT</strong>
          Every role was served by {distinct[0]}. <code>models_override</code> is set, which
          pins the presidential decision — the primary metric — to the same cheap model as
          everything else. This checks that the wiring works; it is not comparable to any run
          without the override.
        </div>
      )}

      {!summary.has_control && (
        <div className="banner danger">
          <strong>NO CONTROL ARM</strong>
          <code>{summary.control_arm}</code> was not run in this session, so nothing here is
          interpretable. Absolute escalation rates are not a finding — base models escalate
          in wargame settings from neutral starting conditions — and only the delta against
          the control means anything.
        </div>
      )}

      <dl className="provenance">
        <div>
          <dt>backend</dt>
          <dd className={summary.backend === 'mock' ? 'bad' : ''}>{summary.backend || '—'}</dd>
        </div>
        <div>
          <dt>grounded</dt>
          <dd className={summary.grounded ? 'good' : 'bad'}>{String(summary.grounded)}</dd>
        </div>
        <div>
          <dt>retrieval</dt>
          <dd>{summary.retrieval_mode || '—'}</dd>
        </div>
        <div>
          <dt>cache</dt>
          <dd>{String(summary.cache_enabled)}</dd>
        </div>
        <div>
          <dt>scenario</dt>
          <dd>{summary.scenario_id}</dd>
        </div>
        <div>
          <dt>spend</dt>
          <dd>${(summary.est_cost_usd ?? 0).toFixed(4)}</dd>
        </div>
      </dl>

      <details className="small" style={{ marginTop: '0.5rem' }}>
        <summary className="muted">Model per role, as served</summary>
        <dl className="provenance" style={{ marginTop: '0.5rem' }}>
          {Object.entries(models).map(([role, model]) => (
            <div key={role}>
              <dt>{role}</dt>
              <dd>{model}</dd>
            </div>
          ))}
          {Object.keys(models).length === 0 && <span className="faint">no models recorded</span>}
        </dl>
        <p className="faint small" style={{ marginTop: '0.4rem' }}>
          Taken from the backend that served each call, not from the config that requested
          it. A role that was never called does not appear — the control arm makes no advisor
          or theorist calls at all.
        </p>
      </details>
    </>
  )
}
