/**
 * What one participant did in this replication, and the record's account of why.
 *
 * Opened by selecting a node in the interaction graph or a row label in the activity
 * timeline. Every node the graph draws has an entry, including the phantom "named but not
 * on the roster" node — a clickable node that opens nothing reads as a bug, and the
 * hallucination rate is a finding about how reliably a model routes rather than an
 * incidental error.
 *
 * **The "why" is only ever what the record holds.** For a theorist that is its own
 * reasoning, the store it drew on, and the Advisor's stated rationale for consulting it.
 * For the President it is the justification, labelled as the reason given rather than the
 * reason the action occurred: `schema.PresidentialAction` documents it as qualitative data
 * that never fed the rung, so presenting it as a cause would assert something the design
 * declines to claim.
 *
 * A persona reached by top-up is marked apart from one the Advisor chose. Nobody judged the
 * first relevant, and that is the panel-coverage diagnostic at the level of a single answer.
 *
 * Cited passages resolve to their text. A citation is only checkable against the claim it
 * was attached to if it can be read, and an id the store does not contain is shown as
 * unresolved rather than hidden — that is the citation-integrity finding.
 */

import { useMemo, useState } from 'react'

import { citationsByPersona, usePassages, type Passages } from '../lib/usePassages'
import type { AgentAnswer, AgentDetail } from '../types/artsoc'

interface Props {
  agent: AgentDetail | null
  onClose: () => void
}

export default function AgentPanel({ agent, onClose }: Props) {
  // Pydantic defaults make these optional in the generated types. Normalised once here so
  // the markup below reads as the shape it actually is.
  const answers = agent?.answers ?? []
  const passages = agent?.passages ?? []
  const fields = agent?.fields ?? []

  const wanted = useMemo(
    () =>
      agent && answers.length > 0
        ? citationsByPersona(
            answers.map((a) => ({ persona_id: agent.id, citations: a.citations })),
          )
        : new Map<string, string[]>(),
    [agent, answers],
  )
  const resolved = usePassages(wanted)

  if (agent == null) {
    return (
      <>
        <h4>Participant</h4>
        <p className="empty">
          Select anyone in the graph, or a row label in the timeline, to see what they did in
          this replication and what the record says about why.
        </p>
      </>
    )
  }

  return (
    <>
      <div className="row tight">
        <h3 style={{ margin: 0 }}>{agent.label}</h3>
        <span className="tag">{agent.kind}</span>
        <div className="spacer" />
        <button className="ghost small" onClick={onClose}>
          Clear
        </button>
      </div>
      <p className="muted small">{agent.summary}</p>

      {fields.length > 0 && (
        <dl className="conditions" style={{ marginTop: '0.75rem' }}>
          {fields.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {answers.length > 0 && (
        <div className="answers">
          {answers.map((answer) => (
            <Answer key={answer.question_id} answer={answer} passages={resolved} />
          ))}
        </div>
      )}

      {passages.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          {passages.map(([label, text], i) => (
            <div key={`${label}-${i}`}>
              <h5 style={{ marginTop: '0.9rem' }}>{label}</h5>
              <p className="muted small" style={{ margin: 0 }}>
                {text}
              </p>
            </div>
          ))}
        </div>
      )}

      {answers.length === 0 && passages.length === 0 && (
        <p className="empty">
          On the panel for this replication, but never consulted. That is a different fact
          from not being there, and it is what the panel-coverage diagnostic measures.
        </p>
      )}
    </>
  )
}

function Answer({ answer, passages }: { answer: AgentAnswer; passages: Passages }) {
  const [open, setOpen] = useState(false)
  const citations = answer.citations ?? []

  return (
    <article className={`answer${answer.declined ? ' declined' : ''}`}>
      <div className="row tight">
        <span className="mono tiny faint">{answer.question_id}</span>
        <span
          className="tag"
          title={
            answer.how_selected === 'topped_up'
              ? 'Added to reach the requested panel size. Nobody judged this persona relevant to the question.'
              : 'Selected on the basis of relevance to the question.'
          }
        >
          {answer.how_selected === 'topped_up' ? 'topped up' : 'chosen'}
        </span>
        {answer.declined ? (
          <span className="tag declined">declined</span>
        ) : (
          <span className="tag" title="Which store the position rested on.">
            from {answer.basis}
          </span>
        )}
        <div className="spacer" />
        <span className="faint tiny">confidence {answer.confidence.toFixed(2)}</span>
      </div>

      <h5>Asked</h5>
      <p className="muted">{answer.question}</p>

      {answer.selection_rationale && (
        <>
          <h5>Why this persona</h5>
          <p className="faint">{answer.selection_rationale}</p>
        </>
      )}

      {answer.position && (
        <>
          <h5>{answer.declined ? 'What they said instead' : 'Position'}</h5>
          <p>{answer.position}</p>
        </>
      )}

      {answer.reasoning && (
        <>
          <h5>Reasoning</h5>
          <p className="muted">{answer.reasoning}</p>
        </>
      )}

      {citations.length > 0 && (
        <>
          <button className="ghost small" onClick={() => setOpen(!open)}>
            {open ? 'Hide' : 'Read'} the {citations.length} passage
            {citations.length === 1 ? '' : 's'} cited
          </button>
          {open &&
            citations.map((id) => {
              const passage = passages.byId.get(id)
              return passage ? (
                <div className="passage" key={id}>
                  <div className="tiny faint">
                    <span className="tag plain">{passage.source}</span> {passage.section}
                  </div>
                  <p>{passage.text}</p>
                </div>
              ) : (
                <div className="passage unresolved" key={id}>
                  <div className="mono tiny">{id}</div>
                  <p>
                    {passages.loading
                      ? 'Looking this up…'
                      : 'Not in the store. The persona attributed a claim to a passage it was not shown — reported, never corrected, because the rate is a finding about the method.'}
                  </p>
                </div>
              )
            })}
        </>
      )}
    </article>
  )
}
