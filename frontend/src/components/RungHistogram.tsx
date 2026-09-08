/**
 * The rung distribution. This leads every results page, because the distribution is the
 * result.
 *
 * A single replication reaching a nuclear rung is an anecdote; "this proportion of n
 * crossed the threshold" is a finding. Every rung on the ladder is drawn even when empty,
 * so a distribution's shape is read against the whole scale rather than against whichever
 * buckets happened to fill.
 *
 * Hand-rolled SVG rather than a chart library. These are bar charts over a fixed nine-value
 * scale; a library brings a default visual idiom that has to be fought, and a dependency
 * larger than the rest of the application put together.
 */

import { NUCLEAR_THRESHOLD, RUNGS, RUNG_LABELS, percent, rungSeries } from '../lib/format'

interface Props {
  distribution: Record<string, number>
  n: number
  height?: number
  /** Draw the y-axis and its ticks. Off for small multiples, where one axis serves all. */
  axis?: boolean
}

const PAD_L = 30
const PAD_R = 4
const PAD_T = 10
const PAD_B = 22
const WIDTH = 320

export default function RungHistogram({ distribution, n, height = 150, axis = true }: Props) {
  const data = rungSeries(distribution, n)
  const peak = Math.max(1, ...data.map((d) => d.count))
  const plotH = height - PAD_T - PAD_B
  const plotW = WIDTH - PAD_L - PAD_R
  const band = plotW / RUNGS.length
  const barW = band * 0.62

  // Ticks at 0 and the peak only. A dense y-axis on a nine-bar chart is furniture: the
  // shape is what is being read, and the counts are in the tooltip and the table below.
  const ticks = peak > 1 ? [0, peak] : [0, 1]

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${WIDTH} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label={`Rung distribution over ${n} replications`}
    >
      {ticks.map((tick) => {
        const y = PAD_T + plotH - (tick / peak) * plotH
        return (
          <g key={tick}>
            <line className="gridline" x1={PAD_L} x2={WIDTH - PAD_R} y1={y} y2={y} />
            {axis && (
              <text x={PAD_L - 6} y={y} dy="0.32em" textAnchor="end" fontSize={9}>
                {tick}
              </text>
            )}
          </g>
        )
      })}

      {/* Between rung 5 and 6: at or above 6 a nuclear weapon has been used in some form. */}
      <line
        className="threshold"
        x1={PAD_L + NUCLEAR_THRESHOLD * band}
        x2={PAD_L + NUCLEAR_THRESHOLD * band}
        y1={PAD_T - 4}
        y2={PAD_T + plotH}
      />

      {data.map((point, i) => {
        const h = (point.count / peak) * plotH
        return (
          <g key={point.rung}>
            <rect
              className={`bar${point.nuclear ? ' nuclear' : ''}`}
              x={PAD_L + i * band + (band - barW) / 2}
              y={PAD_T + plotH - h}
              width={barW}
              height={Math.max(point.count > 0 ? 1 : 0, h)}
            >
              <title>
                {`rung ${point.rung} — ${RUNG_LABELS[point.rung]}: ${point.count} of ${n} (${percent(point.share)})`}
              </title>
            </rect>
            <text
              x={PAD_L + i * band + band / 2}
              y={height - 7}
              textAnchor="middle"
              fontSize={9}
              fill={point.nuclear ? 'var(--nuclear)' : 'var(--ink-4)'}
            >
              {point.rung}
            </text>
          </g>
        )
      })}

      <line className="axis" x1={PAD_L} x2={WIDTH - PAD_R} y1={PAD_T + plotH} y2={PAD_T + plotH} />
    </svg>
  )
}
