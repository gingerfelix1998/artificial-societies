/**
 * Which courses of action were proposed, and which were taken.
 *
 * Two counts per action, never one. The Advisor proposes three options per replication and
 * the President takes one, so conflating them would overstate what the President did by
 * roughly threefold — and the gap between them is the interesting part: an action proposed
 * often and taken rarely is one the panel kept raising and the President kept declining.
 *
 * Rungs are shown beside each action rather than substituted for them. The rung is the
 * primary metric and is what a distribution is measured on, but "public_ultimatum" is what
 * was actually chosen, and a reader presenting this needs the action, not its bucket.
 */

import { NUCLEAR_THRESHOLD, humanise } from '../lib/format'
import type { ActionCount } from '../types/artsoc'

const ROW = 22
const LABEL_W = 172
const COUNT_W = 68

export default function CoaDistribution({
  actions,
  n,
  nWithCoas,
}: {
  actions: ActionCount[]
  n: number
  nWithCoas: number
}) {
  if (actions.length === 0) return <p className="empty">No actions recorded.</p>

  // Ordered by the ladder rather than by frequency: escalation is ordinal, and sorting by
  // count would scramble the one axis this project treats as meaningful.
  const rows = [...actions].sort((a, b) => a.rung - b.rung || a.action.localeCompare(b.action))
  const peak = Math.max(1, ...rows.map((r) => Math.max(r.proposed, r.chosen)))
  const width = 560
  const barW = width - LABEL_W - COUNT_W
  const height = rows.length * ROW + 26

  return (
    <div className="scroll-x">
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-label="Courses of action proposed and chosen"
      >
        {rows.map((row, i) => {
          const y = i * ROW + 4
          const proposedW = (row.proposed / peak) * barW
          const chosenW = (row.chosen / peak) * barW
          return (
            <g key={row.action}>
              <text
                x={LABEL_W - 8}
                y={y + ROW / 2}
                dy="0.32em"
                textAnchor="end"
                fontSize={10}
                fill={row.is_nuclear ? 'var(--nuclear)' : 'var(--ink-2)'}
              >
                {humanise(row.action)}
              </text>
              <text
                x={LABEL_W - 8}
                y={y + ROW / 2}
                dy="0.32em"
                textAnchor="end"
                fontSize={10}
                opacity={0}
              >
                {row.action}
              </text>

              {/* Proposed sits behind, chosen in front: the second is a subset of the first
                  in meaning, and drawing them as separate bars would imply otherwise. */}
              <rect
                className="bar muted"
                x={LABEL_W}
                y={y + 4}
                width={Math.max(row.proposed > 0 ? 1 : 0, proposedW)}
                height={ROW - 9}
              >
                <title>{`${row.action}: proposed ${row.proposed} time(s) across ${nWithCoas} replication(s)`}</title>
              </rect>
              <rect
                className={`bar${row.is_nuclear ? ' nuclear' : ''}`}
                x={LABEL_W}
                y={y + 7}
                width={Math.max(row.chosen > 0 ? 1 : 0, chosenW)}
                height={ROW - 15}
              >
                <title>{`${row.action}: chosen ${row.chosen} of ${n} replication(s)`}</title>
              </rect>

              <text
                x={width - 4}
                y={y + ROW / 2}
                dy="0.32em"
                textAnchor="end"
                fontSize={10}
                fontFamily="var(--mono)"
                fill="var(--ink-3)"
              >
                {row.chosen} / {row.proposed}
              </text>
            </g>
          )
        })}

        <line
          className="axis"
          x1={LABEL_W}
          x2={width - COUNT_W}
          y1={rows.length * ROW + 4}
          y2={rows.length * ROW + 4}
        />
        <text x={LABEL_W} y={height - 4} fontSize={9} fill="var(--ink-4)">
          rung {rows[0]?.rung} &rarr; {rows[rows.length - 1]?.rung}
          {rows.some((r) => r.rung >= NUCLEAR_THRESHOLD) ? ' · nuclear in red' : ''}
        </text>
      </svg>

      <div className="legend">
        <span>
          <span className="swatch" style={{ background: 'var(--rule-2)' }} /> proposed by the
          Advisor
        </span>
        <span>
          <span className="swatch" style={{ background: 'var(--ink-2)' }} /> chosen by the
          President
        </span>
      </div>
    </div>
  )
}
