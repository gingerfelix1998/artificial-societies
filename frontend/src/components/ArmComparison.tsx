/**
 * Contrasts against the control. The only interpretable quantity on the page.
 *
 * Off-the-shelf models escalate in wargame settings even from neutral starting conditions
 * (Rivera et al., FAccT 2024), so the absolute rung distribution of any arm — including the
 * control — is the base model's prior rather than a finding about nuclear strategists. Only
 * what the advisory apparatus *changed* is attributable to the thing this project builds.
 *
 * The header saying so is not decoration. It is the sentence most likely to be dropped
 * between reading a number here and writing it down somewhere else.
 */

import { RUNG_LABELS, percent, signed, signedPercent } from '../lib/format'
import type { ArmSummary, Delta } from '../types/artsoc'

interface Props {
  arms: ArmSummary[]
  deltas: Delta[]
  controlArm: string
  hasControl: boolean
}

export default function ArmComparison({ arms, deltas, controlArm, hasControl }: Props) {
  const byArm = new Map(arms.map((a) => [a.arm, a]))

  return (
    <section className="panel">
      <header>
        <h2>Contrasts against {controlArm}</h2>
        <p className="subtitle">
          Only these deltas are interpretable. The absolute distributions above are the base
          model&rsquo;s escalation prior, not a finding about nuclear strategists — models
          escalate in wargame settings from neutral starting conditions, so what the advisory
          apparatus changed is the only part attributable to this design.
        </p>
      </header>

      {!hasControl ? (
        <p className="banner danger" style={{ marginBottom: 0 }}>
          The control arm was not run, so there is nothing to contrast against and no number
          on this page may be reported.
        </p>
      ) : deltas.length === 0 ? (
        <p className="empty">
          Only the control was run. Add a full-loop arm to have something to contrast.
        </p>
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
              {deltas.map((d) => {
                const arm = byArm.get(d.arm)
                return (
                  <tr key={d.arm}>
                    <td>{d.arm}</td>
                    <td className="num">{arm?.n ?? '—'}</td>
                    <td className="num faint">{arm?.mean_rung.toFixed(3) ?? '—'}</td>
                    <td className="num">{signed(d.d_mean_rung)}</td>
                    <td className="num faint">
                      {arm ? percent(arm.p_nuclear, 1) : '—'}
                    </td>
                    <td className="num">{signedPercent(d.d_p_nuclear)}</td>
                    <td className="faint small">{arm ? modal(arm) : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {deltas.length > 1 && (
        <p className="faint small" style={{ marginTop: '0.75rem' }}>
          These are point differences. There are no confidence intervals and no
          multiple-comparisons correction: with many arms you will find a largest delta
          whether or not one exists. Read the ranking descriptively.
        </p>
      )}
    </section>
  )
}

function modal(arm: ArmSummary): string {
  const entries = Object.entries(arm.rung_distribution)
  if (entries.length === 0) return '—'
  const [rung, count] = entries.reduce((best, current) =>
    current[1] > best[1] ? current : best,
  )
  return `${rung} — ${RUNG_LABELS[Number(rung)] ?? ''} (${count}/${arm.n})`
}
