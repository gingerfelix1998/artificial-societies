/**
 * One row per agent, bars spanning the loop steps where that agent was active.
 *
 * **The x-axis is "Loop step", never "Time".** `llm.CallRecord` carries no timestamp, and
 * the call log is never persisted into `RunRecord` — it holds every system and user prompt,
 * which is exactly what the access-matrix tests scan, so shipping it to a browser would
 * create a second surface where context can cross a boundary. Logical steps are better than
 * a compromise here: they are deterministic, reproducible from config plus seed, and free of
 * API latency that means nothing about the simulation.
 *
 * **Panel members who were never consulted keep their row, greyed.** An absent row and an
 * inactive one say different things, and which one it is is the panel-coverage diagnostic.
 *
 * Hand-rolled SVG. It is a sequence of positioned rectangles; a chart library would add more
 * constraint than help.
 */

import { useMemo } from 'react'

import type { GraphNode, LoopStep } from '../types/artsoc'

const ROW_HEIGHT = 20
const LABEL_WIDTH = 150
const PADDING = 8

interface Props {
  steps: LoopStep[]
  nodes: GraphNode[]
  /** Steps with index <= cursor have happened. -1 reveals nothing. */
  cursor: number
  onSelect?: (index: number) => void
}

export default function LoopGantt({ steps, nodes, cursor, onSelect }: Props) {
  const rows = useMemo(() => buildRows(steps, nodes), [steps, nodes])
  const total = steps.length || 1
  const width = 900
  const trackWidth = width - LABEL_WIDTH - PADDING * 2
  const height = rows.length * ROW_HEIGHT + 34

  const x = (index: number) => LABEL_WIDTH + PADDING + (index / total) * trackWidth
  const stepWidth = Math.max(2, trackWidth / total)

  return (
    <div className="scroll-x">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img">
        <title>Agent activity by loop step</title>

        {/* The cursor, so the Gantt, the graph and the log visibly share one position. */}
        {cursor >= 0 && (
          <rect
            x={x(cursor) + stepWidth}
            y={0}
            width={Math.max(0, width - PADDING - x(cursor) - stepWidth)}
            height={height - 24}
            fill="rgba(18,20,26,0.72)"
          />
        )}

        {rows.map((row, i) => {
          const y = i * ROW_HEIGHT + 4
          return (
            <g key={row.id}>
              <text
                x={LABEL_WIDTH}
                y={y + ROW_HEIGHT / 2}
                dy="0.35em"
                textAnchor="end"
                fontSize={11}
                fill={row.state === 'unconsulted' || row.state === 'excluded' ? '#4a5160' : '#9aa3b2'}
                opacity={row.state === 'unconsulted' ? 0.5 : 1}
              >
                {row.label}
              </text>

              <rect
                x={LABEL_WIDTH + PADDING}
                y={y + 4}
                width={trackWidth}
                height={ROW_HEIGHT - 10}
                fill="#1a1d26"
                rx={2}
              />

              {row.spans.map((span) => (
                <rect
                  key={`${span.from}-${span.to}-${span.kind}`}
                  x={x(span.from)}
                  y={y + 2}
                  width={Math.max(stepWidth, x(span.to + 1) - x(span.from))}
                  height={ROW_HEIGHT - 6}
                  fill={colourFor(span.kind, row.state)}
                  opacity={row.state === 'unconsulted' ? 0.2 : 0.9}
                  rx={2}
                  style={{ cursor: onSelect ? 'pointer' : undefined }}
                  onClick={() => onSelect?.(span.to)}
                >
                  <title>
                    {row.label}: {span.kind}, steps {span.from}–{span.to}
                  </title>
                </rect>
              ))}
            </g>
          )
        })}

        <line
          x1={LABEL_WIDTH + PADDING}
          x2={width - PADDING}
          y1={height - 22}
          y2={height - 22}
          stroke="#2e3440"
        />
        {tickIndices(total).map((tick) => (
          <text key={tick} x={x(tick)} y={height - 8} fontSize={10} fill="#6b7383">
            {tick}
          </text>
        ))}
        <text x={LABEL_WIDTH} y={height - 8} textAnchor="end" fontSize={10} fill="#6b7383">
          Loop step
        </text>
      </svg>
    </div>
  )
}

interface Span {
  from: number
  to: number
  kind: string
}

interface Row {
  id: string
  label: string
  state: string
  spans: Span[]
}

/**
 * A row per participant, with a bar per contiguous stretch of activity.
 *
 * Gaps are deliberate. The Advisor shows as a long row with visible idle stretches while
 * theorists answer, which is what the loop actually does — a single bar from first to last
 * step would imply it was busy throughout.
 */
function buildRows(steps: LoopStep[], nodes: GraphNode[]): Row[] {
  const active = new Map<string, Span[]>()

  const touch = (id: string, index: number, kind: string) => {
    const spans = active.get(id) ?? []
    const last = spans[spans.length - 1]
    if (last && last.kind === kind && index <= last.to + 1) {
      last.to = index
    } else {
      spans.push({ from: index, to: index, kind })
    }
    active.set(id, spans)
  }

  for (const step of steps) {
    touch(step.actor, step.index, step.kind)
    if (step.recipient !== step.actor) touch(step.recipient, step.index, step.kind)
  }

  // Instruments first, in loop order, then personas — active before declined before
  // unconsulted, so the shape of the panel is readable without reading every label.
  const order = ['world', 'intelligence_officer', 'president', 'advisor']
  const rank = (node: GraphNode) => {
    const fixed = order.indexOf(node.id)
    if (fixed >= 0) return [0, fixed] as const
    const states = ['active', 'declined', 'unconsulted', 'excluded']
    return [1, states.indexOf(node.state)] as const
  }

  return [...nodes]
    .sort((a, b) => {
      const [ga, ra] = rank(a)
      const [gb, rb] = rank(b)
      return ga - gb || ra - rb || a.label.localeCompare(b.label)
    })
    .map((node) => ({
      id: node.id,
      label: node.label,
      state: node.state,
      spans: active.get(node.id) ?? [],
    }))
}

function colourFor(kind: string, state: string): string {
  if (state === 'excluded') return '#8b5a8f'
  switch (kind) {
    case 'perception':
      return '#4a5160'
    case 'decline':
      return '#e0a355'
    case 'decide':
      return '#d05a5a'
    case 'consult':
    case 'select':
      return '#3d5a8a'
    default:
      return '#6ea8fe'
  }
}

function tickIndices(total: number): number[] {
  const step = Math.max(1, Math.ceil(total / 12))
  return Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step).filter(
    (i) => i < total,
  )
}
