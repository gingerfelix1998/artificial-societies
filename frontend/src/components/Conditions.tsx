/**
 * What produced these numbers, as a strip rather than a banner.
 *
 * The loud cases — mock, smoke test, no control — are notices at the top of a page, because
 * they stop a figure being read at all. These are the quieter conditions that still gate
 * how it is read: which retriever ran, whether caching means the variance is decision-step
 * or whole-system, and which model served each role.
 *
 * `grounded` comes from the retriever that produced the text, never from the config that
 * asked for it — a config can claim grounding it did not perform.
 */

import type { SessionSummary } from '../types/artsoc'

export default function Conditions({ summary }: { summary: SessionSummary }) {
  const models = Object.entries(summary.models ?? {})

  return (
    <section className="section">
      <h4>Conditions</h4>
      <dl className="conditions">
        <div>
          <dt>backend</dt>
          <dd className={summary.backend === 'mock' ? 'bad' : ''}>{summary.backend || '—'}</dd>
        </div>
        <div>
          <dt>grounded</dt>
          <dd className={summary.grounded ? 'good' : 'bad'}>{String(summary.grounded)}</dd>
        </div>
        {/* Beside `grounded`, never instead of it: a reviewer reading grounded=true has to
            be able to tell what it was grounded in without opening a manifest, and once one
            panel can draw on two kinds of source the boolean alone no longer says. */}
        <div>
          <dt>corpus</dt>
          <dd className={summary.corpus_tier === 'mixed' ? 'bad' : ''}>
            {summary.corpus_tier || '—'}
          </dd>
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

      <p className="faint tiny" style={{ marginTop: '0.6rem' }}>
        {summary.cache_enabled
          ? 'Caching is on, so theorist answers repeat across replications: the dispersion above is variance in the decision step given fixed advisory input, not whole-system variance.'
          : 'Caching is off, so every stage varies per replication: the dispersion above is whole-system variance.'}
      </p>

      {models.length > 0 && (
        <details className="small" style={{ marginTop: '0.75rem' }}>
          <summary className="faint">Model per role, as served</summary>
          <dl className="conditions" style={{ marginTop: '0.6rem', border: 'none' }}>
            {models.map(([role, model]) => (
              <div key={role}>
                <dt>{role.replace(/_/g, ' ')}</dt>
                <dd>{model}</dd>
              </div>
            ))}
          </dl>
          <p className="faint tiny">
            Taken from the backend that served each call, not the config that requested it. A
            role never called does not appear — the control arm makes no advisor or theorist
            calls at all.
          </p>
        </details>
      )}
    </section>
  )
}
