/**
 * Replication counts flowing through the loop to each terminal rung.
 *
 * **Not an escalation path, and never labelled as one.** Phase 1 produces exactly one
 * `PresidentialAction` per replication and `RunRecord.rung` is a single terminal value.
 * There is no sequence of rungs to draw, because the loop is one event and one decision;
 * multi-step escalation arrives in phase 2, when Presidents signal to each other. Drawing a
 * temporal ladder would show something the simulation never ran.
 *
 * What it does show is what varied *upstream* of each terminal rung: the intelligence
 * officer's stated confidence, and whether the panel's positions rested on retrieved sources
 * or on its belief store. Both vary per replication, which the synthesis mode — fixed by
 * config within an arm — does not.
 *
 * The layout comes from `d3-sankey`; every count comes from `views.pipeline_flow`.
 */

import { sankey, sankeyLinkHorizontal } from 'd3-sankey'
import { useMemo } from 'react'

import type { PipelineFlow } from '../types/artsoc'

const WIDTH = 760
const HEIGHT = 320
const NUCLEAR_THRESHOLD = 6

interface Node {
  id: string
  label: string
  stage: number
  count: number
  x0?: number
  x1?: number
  y0?: number
  y1?: number
}

interface Link {
  source: number | Node
  target: number | Node
  value: number
  width?: number
}

export default function PipelineSankey({ flow }: { flow: PipelineFlow }) {
  const layout = useMemo(() => {
    if (flow.nodes.length === 0 || flow.links.length === 0) return null

    const index = new Map(flow.nodes.map((node, i) => [node.id, i]))
    const nodes: Node[] = flow.nodes.map((n) => ({ ...n }))
    const links: Link[] = flow.links
      .filter((l) => index.has(l.source) && index.has(l.target))
      .map((l) => ({
        source: index.get(l.source)!,
        target: index.get(l.target)!,
        value: l.count,
      }))
    if (links.length === 0) return null

    const generator = sankey<Node, Link>()
      .nodeWidth(12)
      .nodePadding(14)
      .extent([
        [1, 8],
        [WIDTH - 1, HEIGHT - 8],
      ])

    return generator({ nodes, links })
  }, [flow])

  if (!layout) {
    return <p className="empty">Not enough variation in this arm to draw a flow.</p>
  }

  const path = sankeyLinkHorizontal<Node, Link>()

  return (
    <div className="scroll-x">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" height={HEIGHT} role="img">
        <title>Pipeline flow to terminal rung</title>

        <g fill="none">
          {layout.links.map((link, i) => (
            <path
              key={i}
              d={path(link) ?? undefined}
              stroke={colourFor(link.target as Node)}
              strokeOpacity={0.28}
              strokeWidth={Math.max(1, link.width ?? 1)}
            >
              <title>
                {(link.source as Node).label} → {(link.target as Node).label}: {link.value}{' '}
                replication(s)
              </title>
            </path>
          ))}
        </g>

        <g>
          {layout.nodes.map((node) => (
            <g key={node.id}>
              <rect
                x={node.x0}
                y={node.y0}
                width={(node.x1 ?? 0) - (node.x0 ?? 0)}
                height={Math.max(1, (node.y1 ?? 0) - (node.y0 ?? 0))}
                fill={colourFor(node)}
                rx={2}
              >
                <title>
                  {node.label}: {node.count} replication(s)
                </title>
              </rect>
              <text
                x={node.stage === 2 ? (node.x0 ?? 0) - 6 : (node.x1 ?? 0) + 6}
                y={((node.y0 ?? 0) + (node.y1 ?? 0)) / 2}
                dy="0.35em"
                textAnchor={node.stage === 2 ? 'end' : 'start'}
                fill="#9aa3b2"
                fontSize={11}
              >
                {node.label} ({node.count})
              </text>
            </g>
          ))}
        </g>
      </svg>

      <div className="legend" style={{ marginTop: '0.5rem' }}>
        <span>
          <span className="swatch" style={{ background: '#6ea8fe' }} /> below the nuclear
          threshold
        </span>
        <span>
          <span className="swatch" style={{ background: '#d05a5a' }} /> rung {NUCLEAR_THRESHOLD}
          + (a weapon was used)
        </span>
      </div>
    </div>
  )
}

function colourFor(node: Node): string {
  if (node.stage !== 2) return node.stage === 0 ? '#4a5160' : '#3d5a8a'
  const rung = Number(node.id.split(':')[1] ?? 0)
  return rung >= NUCLEAR_THRESHOLD ? '#d05a5a' : '#6ea8fe'
}
