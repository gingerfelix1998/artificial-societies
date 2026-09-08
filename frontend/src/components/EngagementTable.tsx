/**
 * Who was consulted, who declined, and on what their positions rested. Descriptive only.
 *
 * **No column here is influence and none is labelled as one.** How often a persona was
 * consulted says nothing about what its presence changed: routing correlates with question
 * tags, which correlate with outcome, so the observational comparison is confounded. Causal
 * attribution comes from the `loo_*` forced-exclusion arms and lives in the influence panel.
 *
 * Two columns are diagnostics rather than description. A persona reached mainly by top-up
 * was consulted without anyone judging it relevant — a panel that is large only nominally.
 * And a low decline rate over positions resting on belief rather than sources is a panel
 * asserting what these theorists held rather than citing where they held it (ADR 0004).
 */

import { percent } from '../lib/format'
import type { EngagementSummary } from '../types/artsoc'

export default function EngagementTable({ engagement }: { engagement: EngagementSummary }) {
  const people = [...engagement.personas].sort((a, b) => b.times_consulted - a.times_consulted)

  return (
    <section className="section">
      <header>
        <h2>Panel engagement — {engagement.arm}</h2>
        <p className="subtitle">{engagement.note}</p>
      </header>

      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>persona</th>
              <th className="num" title="Replications in which this persona was on the panel">
                panel runs
              </th>
              <th
                className="num"
                title="Question-consultations across the arm; a replication puts several questions to the panel, so this can exceed the number of runs"
              >
                consultations
              </th>
              <th className="num">by tag</th>
              <th className="num">by advisor</th>
              <th className="num">topped up</th>
              <th className="num">declined</th>
              <th className="num">mean conf.</th>
              <th className="num">citations</th>
              <th>basis</th>
            </tr>
          </thead>
          <tbody>
            {people.map((person) => (
              <tr key={person.persona_id} className={person.times_consulted === 0 ? 'dim' : ''}>
                <td>
                  {person.name}
                  {person.times_consulted === 0 && (
                    <span className="faint"> · never consulted</span>
                  )}
                </td>
                <td className="num">{person.in_panel_runs}</td>
                <td className="num">{person.times_consulted}</td>
                <td className="num faint">{person.matched_by_tag}</td>
                <td className="num faint">{person.chosen_by_advisor}</td>
                <td className="num faint">{person.topped_up}</td>
                <td className="num">
                  {person.n_opinions > 0 ? percent(person.decline_rate, 0) : '—'}
                </td>
                <td className="num">
                  {person.mean_confidence === null ? '—' : person.mean_confidence.toFixed(2)}
                </td>
                <td className="num">
                  {person.n_citations}
                  {person.n_unsupported > 0 && (
                    <span style={{ color: 'var(--warn)' }}> ({person.n_unsupported} bad)</span>
                  )}
                </td>
                <td className="small faint" style={{ textAlign: 'left' }}>
                  {Object.entries(person.basis_counts ?? {})
                    .map(([basis, count]) => `${basis} ${count}`)
                    .join(', ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="faint small" style={{ marginTop: '0.75rem' }}>
        A replication puts several questions to the panel, so consultations exceed panel runs
        for anyone routed to more than once.{' '}
        &ldquo;bad&rdquo; citations are passage ids an opinion cited that were absent from the
        block it was shown. They are reported, never corrected: the rate is a finding about
        the method, and dropping them would erase it.
        {engagement.unattributed_unsupported > 0 && (
          <>
            {' '}
            A further {engagement.unattributed_unsupported} carried no recognisable persona
            prefix and are attributed to nobody rather than spread across the panel.
          </>
        )}
      </p>
    </section>
  )
}
