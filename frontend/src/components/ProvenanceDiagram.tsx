/**
 * Cited source text → theorist positions → proposed courses of action → the decision.
 *
 * **Every link here comes from an id the record holds.** Passages come from
 * `TheoristOpinion.citations`, options from `CourseOfAction.supporting_opinions`, and the
 * outcome from `PresidentialAction.chosen_coa_id`. None of it is inferred from wording — a
 * lexical-overlap link would look identical on screen and mean nothing, and afterwards
 * there would be no way to tell the two apart. That distinction is the whole value of the
 * diagram.
 *
 * The chosen path is drawn in ink and everything else in grey. What the President did rests
 * on one of the three options; showing all four stages at equal weight would hide which.
 *
 * Where the chain stops, it says so. A control-arm run has no panel to ground an option in,
 * and a record written before ADR 0006 has no such field at all — in both cases the stage
 * is absent rather than empty, and the note explains which.
 */

import { useMemo, useState } from 'react'

import { humanise } from '../lib/format'
import type { ProvenanceFlow, ProvenanceNode } from '../types/artsoc'

const STAGES = ['passage', 'opinion', 'coa', 'decision'] as const
const STAGE_LABEL: Record<string, string> = {
  passage: 'Cited source',
  opinion: 'Theorist position',
  coa: 'Course of action',
  decision: 'Decision',
}

const NODE_H = 20
const GAP = 6
const COL_W = 150
const PAD_T = 26
const PAD_L = 4

interface Placed extends ProvenanceNode {
  x: number
  y: number
  w: number
}

export default function ProvenanceDiagram({
  flow,
  onSelectPassage,
}: {
  flow: ProvenanceFlow
  onSelectPassage?: (passageId: string) => void
}) {
  const [hovered, setHovered] = useState<string | null>(null)

  const { placed, height, width } = useMemo(() => {
    const columns = STAGES.map((stage) => flow.nodes.filter((n) => n.kind === stage))
    const tallest = Math.max(1, ...columns.map((c) => c.length))
    const laid: Placed[] = []

    columns.forEach((column, col) => {
      // Each column is centred against the tallest, so short stages sit beside the middle
      // of the long ones rather than all hugging the top edge.
      const offset = ((tallest - column.length) * (NODE_H + GAP)) / 2
      column.forEach((node, row) => {
        laid.push({
          ...node,
          x: PAD_L + col * COL_W,
          y: PAD_T + offset + row * (NODE_H + GAP),
          w: COL_W - 34,
        })
      })
    })

    return {
      placed: laid,
      height: PAD_T + tallest * (NODE_H + GAP) + 8,
      width: PAD_L + STAGES.length * COL_W,
    }
  }, [flow])

  const byId = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed])

  const isLit = (id: string) => {
    if (!hovered) return false
    if (id === hovered) return true
    // Hovering lights the chain in both directions, so a passage shows what it fed and an
    // option shows what it rested on.
    return flow.links.some(
      (l) =>
        (l.source === hovered && l.target === id) || (l.target === hovered && l.source === id),
    )
  }

  if (flow.nodes.length === 0) return <p className="empty">Nothing recorded for this run.</p>

  return (
    <div>
      <div className="scroll-x">
        <svg
          className="chart"
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          height={height}
          role="img"
          aria-label="What the decision rested on"
        >
          {STAGES.map((stage, i) => (
            <text key={stage} x={PAD_L + i * COL_W} y={12} fontSize={9} fill="var(--ink-4)">
              {STAGE_LABEL[stage]?.toUpperCase()}
            </text>
          ))}

          <g fill="none">
            {flow.links.map((link, i) => {
              const from = byId.get(link.source)
              const to = byId.get(link.target)
              if (!from || !to) return null
              const x1 = from.x + from.w
              const y1 = from.y + NODE_H / 2
              const x2 = to.x
              const y2 = to.y + NODE_H / 2
              const mid = (x1 + x2) / 2
              const lit = isLit(link.source) && isLit(link.target)
              return (
                <path
                  key={`${link.source}-${link.target}-${i}`}
                  d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`}
                  stroke={link.chosen ? 'var(--accent)' : 'var(--rule-2)'}
                  strokeWidth={link.chosen ? 1.4 : 0.8}
                  strokeOpacity={hovered ? (lit ? 1 : 0.15) : link.chosen ? 0.85 : 0.5}
                />
              )
            })}
          </g>

          {placed.map((node) => {
            const dim = hovered !== null && !isLit(node.id)
            const clickable = node.kind === 'passage' && onSelectPassage
            return (
              <g
                key={node.id}
                opacity={dim ? 0.25 : 1}
                onMouseEnter={() => setHovered(node.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={
                  clickable
                    ? () => onSelectPassage(node.id.replace(/^passage:/, ''))
                    : undefined
                }
                style={{ cursor: clickable ? 'pointer' : 'default' }}
              >
                <rect
                  x={node.x}
                  y={node.y}
                  width={node.w}
                  height={NODE_H}
                  rx={2}
                  fill={node.chosen ? 'var(--accent-soft)' : 'var(--paper-2)'}
                  stroke={
                    node.chosen
                      ? 'var(--accent)'
                      : node.declined
                        ? 'var(--declined)'
                        : 'var(--rule)'
                  }
                  strokeWidth={node.chosen ? 1.2 : 0.8}
                  strokeDasharray={node.declined ? '3 2' : undefined}
                />
                <text
                  x={node.x + 6}
                  y={node.y + NODE_H / 2}
                  dy="0.32em"
                  fontSize={9}
                  fill={node.chosen ? 'var(--accent)' : 'var(--ink-2)'}
                >
                  {truncate(label(node), 18)}
                </text>
                <title>{tooltip(node)}</title>
              </g>
            )
          })}
        </svg>
      </div>

      {flow.coa_stage === 'absent' && (
        <div className="notice info" style={{ marginTop: '0.75rem' }}>
          <strong>The chain stops at the opinions</strong>
          {flow.coa_note}
        </div>
      )}

      <div className="legend">
        <span>
          <span className="swatch" style={{ background: 'var(--accent)' }} /> the path the
          President took
        </span>
        <span>
          <span
            className="swatch"
            style={{ border: '1px dashed var(--declined)', background: 'none' }}
          />{' '}
          declined — outside their record
        </span>
        <span className="faint">hover a node to trace its chain; click a source to read it</span>
      </div>
    </div>
  )
}

function label(node: ProvenanceNode): string {
  if (node.kind === 'passage') return `${node.persona_id ?? ''} · ${node.label}`
  if (node.kind === 'coa' || node.kind === 'decision') return humanise(node.label)
  return node.label
}

function tooltip(node: ProvenanceNode): string {
  const head =
    node.kind === 'opinion'
      ? `${node.label}${node.declined ? ' — declined, outside their record' : ''} (${node.question_id})`
      : `${STAGE_LABEL[node.kind]}: ${humanise(node.label)}`
  const chosen = node.chosen ? '\n\nOn the path the President took.' : ''
  return node.detail ? `${head}\n\n${node.detail}${chosen}` : head + chosen
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}
