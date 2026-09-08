/**
 * Every warning `metrics` emitted, verbatim, above the charts.
 *
 * Not paraphrased and not filtered. These are the diagnostics that decide whether a
 * distribution may be read at all — a nominal panel, an escape hatch that is not firing,
 * positions resting on belief rather than sources — and they are printed alongside the
 * numbers in `format_report` for the same reason they appear here rather than in a footer.
 *
 * The only presentation decision is which read as severe, and that is a text match on the
 * server's own prefixes rather than a judgement made here.
 */

const SEVERE = ['NOT GROUNDED', 'SMOKE TEST', 'MOCK BACKEND', 'NO CONTROL ARM', 'NOMINAL PANEL']

export default function WarningList({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) {
    return (
      <p className="faint small">
        No diagnostics were raised. That is not the same as a result being interpretable —
        see the constraints above.
      </p>
    )
  }

  return (
    <ul className="warning-list">
      {warnings.map((warning) => (
        <li key={warning} className={SEVERE.some((s) => warning.startsWith(s)) ? 'severe' : ''}>
          {warning}
        </li>
      ))}
    </ul>
  )
}
