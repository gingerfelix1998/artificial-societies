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

import type { GraphEdge, GraphNode } from '../types/artsoc'

const WIDTH = 640
const HEIGHT = 460
const TICKS = 260

const STATE_COLOUR: Record<string, string> = {
  active: '#6ea8fe',
  declined: '#e0a355',
  unconsulted: '#4a5160',
  excluded: '#8b5a8f',
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
  /** Edges with step_index <= cursor are drawn. -1 draws none. */
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
      x: WIDTH / 2 + Math.cos((i / nodes.length) * Math.PI * 2) * 180,
      y: HEIGHT / 2 + Math.sin((i / nodes.length) * Math.PI * 2) * 150,
    }))

    const index = new Map(positioned.map((n) => [n.id, n]))
    const links: SimulationLinkDatum<Positioned>[] = edges
      .filter((e) => index.has(e.source) && index.has(e.target) && e.source !== e.target)
      .map((e) => ({ source: index.get(e.source)!, target: index.get(e.target)! }))

    forceSimulation(positioned)
      .force('charge', forceManyBody().strength(-260))
      .force('link', forceLink<Positioned, SimulationLinkDatum<Positioned>>(links).distance(90))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', forceCollide(26))
      .stop()
      .tick(TICKS)

    return index
  }, [nodes, edges])

  const visible = edges.filter((edge) => edge.step_index <= cursor)

  // The Advisor formulating questions and choosing whom to ask are steps with no
  // counterpart — it is talking to itself. They are drawn as a ring on the node rather than
  // dropped, because they are two of the three places the Advisor exercises judgement and a
  // graph that silently omitted them would under-state what the Advisor does.
  const selfSteps = new Map<string, number>()
  for (const edge of visible) {
    if (edge.source !== edge.target) continue
    selfSteps.set(edge.source, (selfSteps.get(edge.source) ?? 0) + (edge.weight ?? 1))
  }

  return (
    <div>
      <div className="scroll-x">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" height={HEIGHT} role="img">
          <title>Communications between participants in this replication</title>

          <g>
            {visible.map((edge, i) => {
              const source = layout.get(edge.source)
              const target = layout.get(edge.target)
              if (!source || !target || source === target) return null
              const isHallucination = edge.kind === 'hallucinated'
              return (
                <line
                  key={`${edge.source}-${edge.target}-${edge.kind}-${i}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={edgeColour(edge.kind)}
                  strokeWidth={Math.min(4, 0.8 + (edge.weight ?? 1) * 0.35)}
                  strokeOpacity={isHallucination ? 0.9 : 0.45}
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
                  {selectedAgent === node.id && (
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={radius + 9}
                      fill="none"
                      stroke="#f2c14e"
                      strokeWidth={2}
                    />
                  )}
                  {own > 0 && (
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={radius + 5}
                      fill="none"
                      stroke="#6ea8fe"
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
                          : '#2e3440'
                    }
                    stroke={node.kind === 'persona' ? 'none' : '#6ea8fe'}
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
                    fill={dim ? '#4a5160' : '#9aa3b2'}
                  >
                    {node.label}
                  </text>
                </g>
              )
            })}
          </g>
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
            style={{ border: '1px dashed #6ea8fe', background: 'none', borderRadius: '50%' }}
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

function edgeColour(kind: string): string {
  switch (kind) {
    case 'decline':
      return '#e0a355'
    case 'decide':
      return '#d05a5a'
    case 'hallucinated':
      return '#e06c75'
    case 'perception':
      return '#4a5160'
    default:
      return '#6ea8fe'
  }
}
