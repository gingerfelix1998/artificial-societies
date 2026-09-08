/**
 * Per-theorist attribution, from the forced-exclusion arms.
 *
 * **Cross-arm and causal, or absent.** Each `loo_*` arm runs a world in which one theorist
 * never existed: absent from the panel, from every roster the Advisor was shown, and from
 * every prompt of every role. Removing them and re-running is an intervention. The
 * observational alternative — comparing runs where a persona happened to be routed in
 * against runs where it was not — is confounded, because routing correlates with question
 * tags which correlate with outcome, and it is not computed anywhere in this project.
 *
 * **The reference is the mean of the exclusion arms, not baseline.** Every `loo_*` arm runs
 * a panel one smaller than baseline, so a delta against baseline carries two things at once:
 * this theorist's absence, and the panel being smaller. Contrasting the exclusion arms with
 * each other holds panel size fixed, leaving only which theorist is missing.
 */

import { signed, signedPercent } from '../lib/format'
import type { ArmSummary } from '../types/artsoc'

const LOO_PREFIX = 'loo_'

export default function InfluencePanel({ arms }: { arms: ArmSummary[] }) {
  const exclusion = arms.filter((a) => a.arm.startsWith(LOO_PREFIX))
  const baseline = arms.find((a) => a.arm === 'baseline')

  if (exclusion.length < 2) {
    return (
      <section className="section">
        <header>
          <h2>Per-theorist attribution</h2>
          <p className="subtitle">
            Not available in this session. Attribution is a contrast <em>between</em> the
            forced-exclusion arms, so at least two <code>loo_*</code> arms must have been run
            — this session has {exclusion.length}.
          </p>
        </header>
        <p className="faint small">
          The within-arm alternative is not offered here rather than being greyed out.
          Comparing runs where a persona happened to be consulted against runs where it was
          not is confounded: routing correlates with question tags, which correlate with
          outcome. Computing it would produce a number that reads as causal and is not.
        </p>
      </section>
    )
  }

  const meanRung = exclusion.reduce((s, a) => s + a.mean_rung, 0) / exclusion.length
  const meanNuclear = exclusion.reduce((s, a) => s + a.p_nuclear, 0) / exclusion.length
  const ranked = [...exclusion].sort((a, b) => a.mean_rung - b.mean_rung)

  return (
    <section className="section">
      <header>
        <h2>Per-theorist attribution (forced exclusion)</h2>
        <p className="subtitle">
          Reference is the mean of the {exclusion.length} exclusion arms — mean rung{' '}
          {meanRung.toFixed(3)}, P(nuclear) {(meanNuclear * 100).toFixed(1)}% — not baseline,
          so panel size is held constant and only the identity of the missing theorist varies.
        </p>
      </header>

      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>theorist removed</th>
              <th className="num">n</th>
              <th className="num">&Delta; mean rung</th>
              <th className="num">&Delta; P(nuclear)</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((arm) => (
              <tr key={arm.arm}>
                <td>{arm.arm.slice(LOO_PREFIX.length)}</td>
                <td className="num">{arm.n}</td>
                <td className="num">{signed(arm.mean_rung - meanRung)}</td>
                <td className="num">{signedPercent(arm.p_nuclear - meanNuclear)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {baseline && (
        <p className="faint small" style={{ marginTop: '0.75rem' }}>
          Baseline (panel {baseline.declared_panel_size}) has mean rung{' '}
          {baseline.mean_rung.toFixed(3)} against the exclusion mean (panel{' '}
          {ranked[0]?.declared_panel_size}) of {meanRung.toFixed(3)}, a difference of{' '}
          {signed(baseline.mean_rung - meanRung)}. That contrast is panel size, not any
          particular theorist.
        </p>
      )}

      <p className="faint small">
        A null delta is not evidence of no influence: it can also mean the theorist was rarely
        consulted, so removing them changed few replications. Read each row against how often
        that theorist was routed to in baseline. With {exclusion.length} arms and no
        multiple-comparisons correction, a largest delta exists whether or not one is real.
      </p>
    </section>
  )
}
