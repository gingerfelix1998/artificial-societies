/**
 * Who spoke to whom, with the unused population present.
 *
 * Four node states that all look like "not much happened" are kept apart on purpose:
 *
 * - **active** — produced a position.
 * - **declined** — answered `out_of_record`. Declining is a substantive act and the escape
 *   hatch firing is the honest outcome, so it is styled distinctly rather than as absence.
 * - **unconsulted** — on the panel, never asked. Greyed but present, because "nobody asked
 *   them" and "they were not there" are different facts and the difference is the
 *   panel-coverage diagnostic.
 * - **excluded** — removed by intervention in a `loo_*` arm. The world operated as though
 *   they never existed.
 *
 * Ids the Advisor named that were not on the roster appear as dashed edges to a phantom
 * node. The hallucination rate is a finding about how reliably a model routes, and putting
 * it in a tooltip would bury it.
 *
 * Layout is `d3-force`, run to a fixed number of ticks so the picture is the same every time
 * the same run is opened — a graph that settles differently on each visit is not a record.
 */

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import { useMemo } from 'react'

import type { GraphEdge, GraphNode, LoopStep } from '../types/artsoc'

const WIDTH = 720
const HEIGHT = 520
const TICKS = 260

const STATE_COLOUR: Record<string, string> = {
  active: 'var(--accent)',
  declined: 'var(--declined)',
  unconsulted: 'var(--unconsulted)',
  excluded: 'var(--excluded)',
}

interface Positioned extends SimulationNodeDatum {
  id: string
  label: string
  kind: string
  state: string
  n_opinions: number
  n_declines: number
}

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  hallucinated: string[]
  /** The loop, so the deliberation at the cursor can be captioned where it happened. */
  steps: LoopStep[]
  /** An edge is drawn once any step it covers has happened. -1 draws none. */
  cursor: number
  /** Selecting a node opens its detail panel. It does not move the playback cursor:
   *  "show me this agent" and "take me to this moment" are different intents. */
  onSelectAgent?: (id: string) => void
  selectedAgent?: string | null
}

export default function InteractionGraphView({
  nodes,
  edges,
  hallucinated,
  steps,
  cursor,
  onSelectAgent,
  selectedAgent,
}: Props) {
  const layout = useMemo(() => {
    const positioned: Positioned[] = nodes.map((node, i) => ({
      id: node.id,
      label: node.label,
      kind: node.kind,
      state: node.state,
      n_opinions: node.n_opinions ?? 0,
      n_declines: node.n_declines ?? 0,
      // Seeded on a circle rather than at random, so the simulation is deterministic and
      // the same run always draws the same picture.
      x: WIDTH / 2 + Math.cos((i / nodes.length) * Math.PI * 2) * 210,
      y: HEIGHT / 2 + Math.sin((i / nodes.length) * Math.PI * 2) * 175,
    }))

    const index = new Map(positioned.map((n) => [n.id, n]))
    const links: SimulationLinkDatum<Positioned>[] = edges
      .filter((e) => index.has(e.source) && index.has(e.target) && e.source !== e.target)
      .map((e) => ({ source: index.get(e.source)!, target: index.get(e.target)! }))

    forceSimulation(positioned)
      .force('charge', forceManyBody().strength(-420))
      .force('link', forceLink<Positioned, SimulationLinkDatum<Positioned>>(links).distance(120))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', forceCollide(40))
      .stop()
      .tick(TICKS)

    return index
  }, [nodes, edges])

  // Revealed by the steps an edge covers, not by the first one. The Advisor consults each
  // persona in turn, and lighting the whole edge at its first consultation made every
  // deliberation after that invisible to someone stepping through.
  const happened = (edge: GraphEdge) =>
    (edge.step_indices ?? [edge.step_index]).some((index) => index <= cursor)
  const visible = edges.filter(happened)

  // The one deliberation the cursor is on. Everything else recedes so a viewer stepping
  // through sees which act is happening rather than a picture that only grows.
  const current = cursor >= 0 ? (steps[cursor] ?? null) : null
  const isCurrentEdge = (edge: GraphEdge) =>
    current !== null &&
    edge.source === current.actor &&
    edge.target === current.recipient &&
    edge.kind === current.kind

  // The Advisor formulating questions and choosing whom to ask are steps with no
  // counterpart — it is talking to itself. They are drawn as a ring on the node rather than
  // dropped, because they are two of the three places the Advisor exercises judgement and a
  // graph that silently omitted them would under-state what the Advisor does.
  const selfSteps = new Map<string, number>()
  for (const edge of visible) {
    if (edge.source !== edge.target) continue
    const done = (edge.step_indices ?? [edge.step_index]).filter((i) => i <= cursor).length
    selfSteps.set(edge.source, (selfSteps.get(edge.source) ?? 0) + done)
  }

  return (
    <div>
      <div className="scroll-x chart">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" height={HEIGHT} role="img">
          <title>Communications between participants in this replication</title>

          <g>
            {visible.map((edge, i) => {
              const source = layout.get(edge.source)
              const target = layout.get(edge.target)
              if (!source || !target || source === target) return null
              const isHallucination = edge.kind === 'hallucinated'
              const live = isCurrentEdge(edge)
              return (
                <line
                  key={`${edge.source}-${edge.target}-${edge.kind}-${i}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={live ? 'var(--ink)' : edgeColour(edge.kind)}
                  strokeWidth={live ? 2.4 : Math.min(4, 0.8 + (edge.weight ?? 1) * 0.35)}
                  strokeOpacity={
                    live ? 1 : current !== null ? 0.18 : isHallucination ? 0.9 : 0.45
                  }
                  strokeDasharray={isHallucination ? '4 3' : undefined}
                >
                  <title>
                    {source.label} → {target.label}: {edge.kind} ×{edge.weight ?? 1} (step{' '}
                    {edge.step_index})
                  </title>
                </line>
              )
            })}
          </g>

          <g>
            {[...layout.values()].map((node) => {
              const radius = node.kind === 'persona' ? 8 + Math.min(6, node.n_opinions * 2) : 12
              const dim = node.state === 'unconsulted'
              const own = selfSteps.get(node.id) ?? 0
              return (
                <g
                  key={node.id}
                  opacity={dim ? 0.35 : 1}
                  onClick={onSelectAgent ? () => onSelectAgent(node.id) : undefined}
                  style={onSelectAgent ? { cursor: 'pointer' } : undefined}
                >
                  {current !== null &&
                    (current.actor === node.id || current.recipient === node.id) && (
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={radius + 4}
                        fill="none"
                        stroke="var(--ink)"
                        strokeWidth={1.5}
                      />
                    )}
                  {selectedAgent === node.id && (
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={radius + 9}
                      fill="none"
                      stroke="var(--ink)"
                      strokeWidth={2}
                    />
                  )}
                  {own > 0 && (
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={radius + 5}
                      fill="none"
                      stroke="var(--accent)"
                      strokeWidth={1}
                      strokeDasharray="2 3"
                      strokeOpacity={0.7}
                    >
                      <title>
                        {node.label}: {own} step(s) with no counterpart — formulating
                        questions and choosing whom to ask
                      </title>
                    </circle>
                  )}
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={radius}
                    fill={
                      node.kind === 'phantom'
                        ? 'none'
                        : node.kind === 'persona'
                          ? STATE_COLOUR[node.state]
                          : 'var(--paper-3)'
                    }
                    stroke={node.kind === 'persona' ? 'none' : 'var(--ink-3)'}
                    strokeWidth={node.kind === 'phantom' ? 1.5 : 1}
                    strokeDasharray={node.kind === 'phantom' ? '3 2' : undefined}
                  >
                    <title>
                      {node.label} — {node.state}
                      {node.kind === 'persona' &&
                        `, ${node.n_opinions} position(s), ${node.n_declines} decline(s)`}
                    </title>
                  </circle>
                  <text
                    x={node.x}
                    y={(node.y ?? 0) + radius + 11}
                    textAnchor="middle"
                    fontSize={10}
                    fill={dim ? 'var(--ink-4)' : 'var(--ink-2)'}
                  >
                    {node.label}
                  </text>
                </g>
              )
            })}
          </g>

          {current && <Caption step={current} layout={layout} />}
        </svg>
      </div>

      <div className="legend">
        <span>
          <span className="swatch" style={{ background: STATE_COLOUR.active }} /> stated a
          position
        </span>
        <span>
          <span className="swatch" style={{ background: STATE_COLOUR.declined }} /> declined —
          outside their record
        </span>
        <span>
          <span className="swatch" style={{ background: STATE_COLOUR.unconsulted }} /> on the
          panel, never asked
        </span>
        <span>
          <span className="swatch" style={{ background: STATE_COLOUR.excluded }} /> removed by
          intervention
        </span>
        <span>
          <span
            className="swatch"
            style={{ border: '1px dashed var(--accent)', background: 'none', borderRadius: '50%' }}
          />{' '}
          a ring marks steps with no counterpart — the Advisor thinking, not communicating
        </span>
      </div>

      {hallucinated.length > 0 && (
        <p className="small" style={{ color: 'var(--warn)', marginTop: '0.5rem' }}>
          The Advisor named {hallucinated.length} id(s) that were not on the roster —{' '}
          <span className="mono">{hallucinated.join(', ')}</span>. They were dropped, never
          honoured. The rate is a finding about how reliably a model routes.
        </p>
      )}
    </div>
  )
}

/**
 * The opening of what the current step produced, drawn where it happened.
 *
 * Over the midpoint of the edge for a communication, and over the node itself for a step
 * with no counterpart — the Advisor writing a question or choosing whom to ask is a
 * deliberation, and it belongs on the Advisor rather than floating between two participants
 * that were not involved.
 *
 * `foreignObject` rather than SVG `<text>` because this needs to wrap. The text is
 * `LoopStep.excerpt`, a truncation of the record's own words produced in `views.py` — never
 * a paraphrase, which would be a second account of what was said sitting beside the first.
 */
function Caption({ step, layout }: { step: LoopStep; layout: Map<string, Positioned> }) {
  const from = layout.get(step.actor)
  const to = layout.get(step.recipient)
  if (!from) return null

  const solo = step.actor === step.recipient || !to
  const x = solo ? (from.x ?? 0) : (((from.x ?? 0) + (to!.x ?? 0)) / 2)
  const y = solo ? (from.y ?? 0) : (((from.y ?? 0) + (to!.y ?? 0)) / 2)

  const w = 210
  const h = step.excerpt ? 76 : 34

  // Offset perpendicular to the edge rather than straight up, so the caption never lands on
  // the line it annotates or on either participant. The direction is whichever pushes away
  // from the middle of the canvas, where the nodes are densest.
  let ox = 0
  let oy = -(h / 2 + 22)
  if (!solo) {
    const dx = (to!.x ?? 0) - (from.x ?? 0)
    const dy = (to!.y ?? 0) - (from.y ?? 0)
    const len = Math.hypot(dx, dy) || 1
    const nx = -dy / len
    const ny = dx / len
    const away = (x - WIDTH / 2) * nx + (y - HEIGHT / 2) * ny >= 0 ? 1 : -1
    const reach = h / 2 + 26
    ox = nx * reach * away
    oy = ny * reach * away
  }

  // Nudged inside the canvas so a caption on an outlying node is not half cut off.
  const left = Math.max(4, Math.min(WIDTH - w - 4, x + ox - w / 2))
  const top = Math.max(4, Math.min(HEIGHT - h - 4, y + oy - h / 2))

  return (
    <foreignObject x={left} y={top} width={w} height={h} style={{ overflow: 'visible' }}>
      <div className="graph-caption">
        <div className="graph-caption-label">{step.label}</div>
        {step.excerpt && <div className="graph-caption-text">{step.excerpt}</div>}
      </div>
    </foreignObject>
  )
}

function edgeColour(kind: string): string {
  switch (kind) {
    case 'decline':
      return 'var(--declined)'
    case 'decide':
      return 'var(--nuclear)'
    case 'hallucinated':
      return 'var(--nuclear)'
    case 'perception':
      return 'var(--ink-4)'
    default:
      return 'var(--accent)'
  }
}
