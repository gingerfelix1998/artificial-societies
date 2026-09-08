/**
 * What one participant did in this replication, and the record's account of why.
 *
 * Opened by clicking a node in the interaction graph or a row label in the Gantt. Every
 * node the graph draws has an entry, including the phantom "named but not on the roster"
 * node — a clickable node that opens nothing reads as a bug, and the hallucination rate is
 * a finding about how reliably a model routes rather than an incidental error.
 *
 * **The "why" is only ever what the record holds.** For a theorist that is its own
 * reasoning, the store it drew on, and the Advisor's stated rationale for consulting it.
 * For the President it is the justification, labelled as the reason given rather than the
 * reason the action occurred: `schema.PresidentialAction` documents it as qualitative data
 * that never fed the rung, so presenting it as a cause would assert something the design
 * declines to claim.
 *
 * A persona reached by top-up is marked apart from one the Advisor chose. Nobody judged the
 * first relevant, and that is the panel-coverage diagnostic showing up at the level of a
 * single answer.
 */

import type { AgentAnswer, AgentDetail } from '../types/artsoc'

interface Props {
  agent: AgentDetail | null
  onClose: () => void
}

function Answer({ answer }: { answer: AgentAnswer }) {
  const citations = answer.citations ?? []
  return (
    <article className="answer">
      <div className="row">
        <span className="qid">{answer.question_id}</span>
        <span
          className={answer.how_selected === 'topped_up' ? 'pill muted' : 'pill'}
          title={
            answer.how_selected === 'topped_up'
              ? 'Added to reach the requested panel size. Nobody judged this persona relevant to the question.'
              : 'Selected on the basis of relevance to the question.'
          }
        >
          {answer.how_selected === 'topped_up' ? 'topped up' : 'chosen'}
        </span>
        {answer.declined ? (
          <span className="pill warn" title="The persona stated no position.">
            declined
          </span>
        ) : (
          <span className="pill" title="Which store the position rested on.">
            from {answer.basis}
          </span>
        )}
        <div className="spacer" />
        <span className="faint small">confidence {answer.confidence.toFixed(2)}</span>
      </div>

      <p className="qtext">{answer.question}</p>

      {answer.selection_rationale ? (
        <p className="faint small">
          <strong>Why this persona:</strong> {answer.selection_rationale}
        </p>
      ) : null}

      {answer.position ? (
        <p className="passage">
          <strong>Position.</strong> {answer.position}
        </p>
      ) : null}
      {answer.reasoning ? (
        <p className="passage">
          <strong>Reasoning.</strong> {answer.reasoning}
        </p>
      ) : null}

      {citations.length > 0 ? (
        <p className="citations small">
          Cited {citations.length}:{' '}
          {citations.map((id) => (
            <code key={id}>{id}</code>
          ))}
        </p>
      ) : null}
    </article>
  )
}

export default function AgentPanel({ agent, onClose }: Props) {
  // Pydantic defaults make these optional in the generated types. Normalised once here so
  // the markup below reads as the shape it actually is.
  const answers = agent?.answers ?? []
  const passages = agent?.passages ?? []
  const fields = agent?.fields ?? []

  if (agent == null) {
    return (
      <section className="panel">
        <header>
          <h2>Agent detail</h2>
          <p className="subtitle">
            Select a node in the graph, or a row label in the timeline, to see what that
            participant did in this replication and what the record says about why.
          </p>
        </header>
        <p className="empty">Nothing selected.</p>
      </section>
    )
  }

  return (
    <section className="panel">
      <header>
        <div className="row">
          <h2 style={{ margin: 0 }}>{agent.label}</h2>
          <span className="pill muted">{agent.kind}</span>
          <div className="spacer" />
          <button className="small" onClick={onClose}>
            Clear
          </button>
        </div>
        <p className="subtitle">{agent.summary}</p>
      </header>

      {fields.length > 0 ? (
        <div className="summary-stats">
          {fields.map(([label, value]) => (
            <div className="summary-stat" key={label}>
              <span className="summary-stat-value">{value}</span>
              <span className="faint small">{label}</span>
            </div>
          ))}
        </div>
      ) : null}

      {answers.length > 0 ? (
        <div className="passages">
          {answers.map((answer) => (
            <Answer key={`${answer.question_id}`} answer={answer} />
          ))}
        </div>
      ) : null}

      {passages.length > 0 ? (
        <div className="passages">
          {passages.map(([label, text], i) => (
            <p className="passage" key={`${label}-${i}`}>
              <strong>{label}.</strong> {text}
            </p>
          ))}
        </div>
      ) : null}

      {answers.length === 0 && passages.length === 0 ? (
        <p className="empty">
          On the panel for this replication, but never consulted. That is a different fact
          from not being there, and it is what the panel-coverage diagnostic measures.
        </p>
      ) : null}
    </section>
  )
}
