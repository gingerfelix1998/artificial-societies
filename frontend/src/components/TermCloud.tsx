/**
 * Term frequency over text already in the record.
 *
 * **The label is not optional politeness.** There is no theme coder in this project.
 * `docs/framework/measurement.md` lists reasoning-theme coding as not implemented and says
 * that when it exists it needs inter-coder agreement against a hand-coded sample before any
 * theme count appears in a claim. Calling raw word counts "themes" is precisely the
 * overclaim that document exists to prevent, so the caption is fixed and always rendered.
 *
 * The source toggle matters too: theorist positions, the Advisor's compression of them and
 * the President's justification are three different registers, and a cloud mixing all three
 * is uninterpretable.
 */

import { useMemo, useState } from 'react'

import { TERM_CLOUD_LABEL, termFrequency } from '../lib/terms'
import type { RunRecord } from '../types/artsoc'

type Source = 'theorist' | 'advisor' | 'president'

const SOURCES: { key: Source; label: string; hint: string }[] = [
  {
    key: 'theorist',
    label: 'Theorist positions',
    hint: 'position and reasoning text from every opinion in this arm',
  },
  {
    key: 'advisor',
    label: 'Advisory brief',
    hint: 'consensus points and minority positions, after compression',
  },
  {
    key: 'president',
    label: 'Presidential justification',
    hint: 'the prose that did not produce the rung — the rung comes from the typed action',
  },
]

export default function TermCloud({ records, mock }: { records: RunRecord[]; mock: boolean }) {
  const [source, setSource] = useState<Source>('theorist')

  const terms = useMemo(() => termFrequency(textFor(records, source)), [records, source])
  const active = SOURCES.find((s) => s.key === source)!

  return (
    <section className="panel">
      <header>
        <div className="row">
          <h2 style={{ margin: 0 }}>Term frequency</h2>
          <div className="spacer" />
          {SOURCES.map((option) => (
            <button
              key={option.key}
              className={`small ${option.key === source ? 'primary' : 'ghost'}`}
              onClick={() => setSource(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="subtitle">
          <strong>{TERM_CLOUD_LABEL}</strong> Lowercased, stopword-filtered word counts over{' '}
          {active.hint}. No stemming and no coding of any kind — these are the words that
          appear, not the ideas they carry.
        </p>
      </header>

      {mock ? (
        <div className="banner warn" style={{ marginBottom: 0 }}>
          <strong>NOTHING TO COUNT</strong>
          This session ran on the mock backend, whose output is <code>MOCK:</code>-prefixed
          nonsense by design. A cloud of it would say nothing about anything, so it is not
          drawn.
        </div>
      ) : terms.length === 0 ? (
        <p className="empty">No text of this kind in the arm.</p>
      ) : (
        <div className="term-cloud">
          {terms.map((term) => (
            <span
              key={term.term}
              className={term.weight > 0.45 ? 'hot' : ''}
              style={{ fontSize: `${0.8 + term.weight * 1.5}rem` }}
              title={`${term.count} occurrence(s)`}
            >
              {term.term}
            </span>
          ))}
        </div>
      )}
    </section>
  )
}

function textFor(records: RunRecord[], source: Source): string[] {
  switch (source) {
    case 'theorist':
      return records.flatMap((r) =>
        (r.opinions ?? []).flatMap((o) => [o.position, o.reasoning]),
      )
    case 'advisor':
      return records.flatMap((r) => [
        r.advisor_brief?.summary ?? '',
        ...(r.advisor_brief?.consensus_points ?? []),
        ...(r.advisor_brief?.minority_positions ?? []),
      ])
    case 'president':
      return records.map((r) => r.action.justification)
  }
}
