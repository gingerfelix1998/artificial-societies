/**
 * The rung distribution. This leads every results page, because the distribution is the
 * result.
 *
 * A single replication reaching a nuclear rung is an anecdote; "this proportion of n
 * crossed the threshold" is a finding. Every rung on the ladder is drawn even when empty,
 * so a distribution's shape is read against the whole scale rather than against whichever
 * buckets happened to fill.
 *
 * The nuclear threshold is marked rather than left to the reader to count to.
 */

import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { NUCLEAR_THRESHOLD, RUNG_LABELS, percent, rungSeries } from '../lib/format'

interface Props {
  distribution: Record<string, number>
  n: number
  height?: number
  /** Rendered small alongside other arms rather than as the headline chart. */
  compact?: boolean
}

export default function RungHistogram({ distribution, n, height = 210, compact }: Props) {
  const data = rungSeries(distribution, n)

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -18 }}>
        <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: '#2e3440' }} />
        <YAxis
          allowDecimals={false}
          tickLine={false}
          axisLine={{ stroke: '#2e3440' }}
          width={44}
        />
        <Tooltip
          cursor={{ fill: 'rgba(110,168,254,0.08)' }}
          content={({ active, payload }) => {
            const point = active ? payload?.[0]?.payload : undefined
            if (!point) return null
            return (
              <div className="tip">
                <div>
                  <strong>rung {point.rung}</strong> — {RUNG_LABELS[point.rung]}
                </div>
                <div className="muted">
                  {point.count} of {n} ({percent(point.share)})
                </div>
              </div>
            )
          }}
        />
        {/* Drawn between rung 5 and 6: at or above 6 a nuclear weapon has been used. */}
        <ReferenceLine
          x={String(NUCLEAR_THRESHOLD)}
          stroke="#d05a5a"
          strokeDasharray="3 3"
          label={
            compact
              ? undefined
              : { value: 'nuclear', position: 'top', fill: '#d05a5a', fontSize: 11 }
          }
        />
        <Bar dataKey="count" radius={[2, 2, 0, 0]}>
          {data.map((point) => (
            <Cell key={point.rung} fill={point.nuclear ? '#d05a5a' : '#6ea8fe'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
