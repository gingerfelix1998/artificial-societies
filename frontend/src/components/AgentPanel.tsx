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
 *
 * **An `excomm_member` node gets a real name and a live chat (ADR 0010).** `agent.label`
 * already carries the real name — the API overlays it before this component ever sees the
 * payload — and `roster[agent.id].role_title` is the anonymous seat, shown as a subtitle so
 * the anonymisation the model actually operated under stays visible. The chat below it is
 * a new, on-demand conversation: nothing sent or received here touches the record.
 */

import { useMemo, useState } from 'react'

import { api } from '../api/client'
import ChatBox, { useChat } from './ChatBox'
import { citationsByPersona, usePassages, type Passages } from '../lib/usePassages'
import type { AgentAnswer, AgentDetail, RosterEntry } from '../types/artsoc'

interface Props {
  agent: AgentDetail | null
  onClose: () => void
  /** `member_id -> {role_title, real_name}` (ADR 0010). Empty when this run convened no
   *  committee, or for an agent that isn't one. */
  roster?: Record<string, RosterEntry>
  sessionId?: string
  arm?: string
  runId?: string
}

export default function AgentPanel({ agent, onClose, roster, sessionId, arm, runId }: Props) {
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

  const isExcommChat = agent?.kind === 'excomm_member' && sessionId && arm && runId
  const chatKey = isExcommChat ? `${sessionId}:${arm}:${runId}:${agent!.id}` : ''
  const chat = useChat(
    () =>
      isExcommChat
        ? api.chatHistory(sessionId, arm, 'excomm', runId, agent!.id)
        : Promise.resolve([]),
    (message) =>
      isExcommChat
        ? api.sendChat(sessionId, arm, 'excomm', runId, agent!.id, message)
        : Promise.reject(new Error('no committee member selected')),
    chatKey,
  )

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
      {agent.kind === 'excomm_member' && roster?.[agent.id] && (
        <p className="faint tiny" style={{ marginTop: '-0.3rem' }}>
          Anonymised in the simulation as: {roster[agent.id]!.role_title}. The name above is
          shown here only — the model never saw it.
        </p>
      )}
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

      {answers.length === 0 && passages.length === 0 && agent.kind !== 'excomm_member' && (
        <p className="empty">
          On the panel for this replication, but never consulted. That is a different fact
          from not being there, and it is what the panel-coverage diagnostic measures.
        </p>
      )}

      {isExcommChat && (
        <ChatBox
          label={agent.label}
          history={chat.history}
          loading={chat.loading}
          error={chat.error}
          onSend={chat.onSend}
          sending={chat.sending}
        />
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
