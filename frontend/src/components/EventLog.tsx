/**
 * The loop as a chronological list: who acted, on whom, and what was said.
 *
 * Payloads are resolved from the record by the `payload_ref` each step carries — the server
 * sends one copy of the text and a pointer to it, so the log and the other panels cannot
 * disagree about what was said.
 *
 * What is *not* here: prompts. `RunRecord` carries none, because `call_log` is never
 * persisted into it. The log shows what each role produced, never what it was asked.
 */

import { useEffect, useRef } from 'react'

import { titleCase } from '../lib/format'
import type { LoopStep, RunRecord } from '../types/artsoc'

interface Props {
  steps: LoopStep[]
  record: RunRecord
  cursor: number
  onSelect?: (index: number) => void
}

export default function EventLog({ steps, record, cursor, onSelect }: Props) {
  const currentRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Scrolled by setting the container's own scrollTop rather than with `scrollIntoView`.
  // `scrollIntoView` walks every scrollable ancestor, so following playback here also
  // dragged the whole page down to the log — away from the Gantt or the graph the viewer
  // was actually watching, and away from the pause button.
  useEffect(() => {
    const container = containerRef.current
    const current = currentRef.current
    if (!container || !current) return
    const top = current.offsetTop - container.offsetTop
    const bottom = top + current.offsetHeight
    if (top < container.scrollTop) container.scrollTop = top
    else if (bottom > container.scrollTop + container.clientHeight) {
      container.scrollTop = bottom - container.clientHeight
    }
  }, [cursor])

  const visible = steps.filter((step) => step.index <= cursor)

  return (
    <div className="event-log" ref={containerRef}>
      {visible.length === 0 && (
        <p className="empty">Nothing has happened yet. Press play, or step forward.</p>
      )}
      {visible.map((step) => (
        <div
          key={step.index}
          ref={step.index === cursor ? currentRef : undefined}
          className={`event ${step.kind} ${step.index === cursor ? 'current' : ''}`}
          onClick={() => onSelect?.(step.index)}
          style={{ cursor: onSelect ? 'pointer' : undefined }}
        >
          <div className="who">
            {String(step.index).padStart(2, '0')} · {titleCase(step.actor)}
            {step.recipient !== step.actor && <> &rarr; {titleCase(step.recipient)}</>}
            {step.question_id && <span className="faint"> · {step.question_id}</span>}
          </div>
          <div>{step.label}</div>

          {/* The question is repeated on every consultation and reply. Without it a reply
              reads as an answer to nothing, and the question it belongs to is a dozen
              entries further up. */}
          {asked(record, step) && <div className="asked">{asked(record, step)}</div>}

          {sections(record, step).map((section) => (
            <div key={section.label} className="payload">
              {section.label && <span className="payload-label">{section.label}</span>}
              {section.text}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

/** The analytical question a consultation or reply belongs to, for repeating in place. */
function asked(record: RunRecord, step: LoopStep): string | null {
  if (!step.question_id) return null
  if (step.kind !== 'consult' && step.kind !== 'opine' && step.kind !== 'decline') return null
  const question = (record.questions ?? []).find((q) => q.question_id === step.question_id)
  return question ? `Asked: ${question.text}` : null
}

interface Section {
  label: string
  text: string
}

/**
 * Resolve a step's `payload_ref` into labelled blocks.
 *
 * Labelled rather than concatenated: a theorist's position and its reasoning are different
 * kinds of claim, and running them together as one paragraph is what made the log hard to
 * read. The same applies to the brief's consensus and minority halves — what the
 * compression dropped is itself a finding, so it gets its own heading.
 */
function sections(record: RunRecord, step: LoopStep): Section[] {
  const value = deref(record, step.payload_ref)
  if (!value) return []
  const keep = (parts: Section[]) => parts.filter((p) => p.text?.trim())

  switch (step.kind) {
    case 'perception': {
      const event = value as NonNullable<RunRecord['view']>[number]
      return keep([
        { label: '', text: event.description },
        {
          label: 'Collection',
          text: `confidence ${event.confidence}${event.degraded ? ` — ${event.source_note}` : ''}`,
        },
      ])
    }
    case 'brief': {
      const brief = value as RunRecord['intel_brief']
      return keep([
        { label: 'Summary', text: brief.summary },
        { label: 'Assessment', text: brief.assessed_activity },
        {
          label: 'Alternative explanations',
          text: (brief.alternative_explanations ?? []).join('\n• '),
        },
        { label: 'Collection gaps', text: (brief.collection_gaps ?? []).join('\n• ') },
      ])
    }
    case 'query': {
      const query = value as NonNullable<RunRecord['presidential_query']>
      return keep([
        { label: '', text: query.text },
        { label: 'Concerns', text: (query.concerns ?? []).join('\n• ') },
      ])
    }
    case 'formulate':
      return keep([
        { label: '', text: (value as NonNullable<RunRecord['questions']>[number]).text },
      ])
    case 'select': {
      const routing = value as NonNullable<RunRecord['routing']>[number]
      return keep([
        { label: 'Selected', text: (routing.selected ?? []).join(', ') },
        { label: 'Advisor’s reason', text: routing.rationale ?? '' },
      ])
    }
    case 'consult':
      return []
    case 'opine':
    case 'decline': {
      const opinion = value as NonNullable<RunRecord['opinions']>[number]
      return keep([
        {
          label: opinion.out_of_record ? 'What they said instead' : 'Position',
          text: opinion.position,
        },
        { label: 'Reasoning', text: opinion.reasoning },
        { label: 'Cited', text: (opinion.citations ?? []).join('\n') },
      ])
    }
    case 'synthesise': {
      const brief = value as NonNullable<RunRecord['advisor_brief']>
      return keep([
        { label: 'Summary', text: brief.summary },
        { label: 'Consensus', text: (brief.consensus_points ?? []).join('\n• ') },
        { label: 'Minority positions', text: (brief.minority_positions ?? []).join('\n• ') },
      ])
    }
    case 'decide':
      return keep([
        { label: 'Justification', text: (value as RunRecord['action']).justification },
      ])
    default:
      return []
  }
}

function deref(record: RunRecord, ref: string): unknown {
  const match = ref.match(/^(\w+)(?:\[(\d+)\])?$/)
  if (!match) return null
  const [, field, index] = match
  const value = (record as unknown as Record<string, unknown>)[field!]
  if (index === undefined) return value ?? null
  return Array.isArray(value) ? (value[Number(index)] ?? null) : null
}
