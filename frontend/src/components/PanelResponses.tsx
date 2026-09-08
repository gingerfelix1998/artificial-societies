/**
 * The advisory exchange, question by question, as prose rather than as a step list.
 *
 * The event log is chronological and drives playback; this is for reading. One block per
 * analytical question: the question the Advisor wrote, its stated reason for choosing whom
 * to ask, then each theorist's answer in full with the passages it cited resolved to their
 * text.
 *
 * **It is an exchange, not a conversation.** Each theorist is asked once and answers once.
 * They never see each other and never reply to one another — peer visibility would make
 * apparent consensus a herding artifact of call ordering, which is why the access matrix
 * forbids it. Presenting this as a dialogue would imply deliberation that did not happen,
 * so the layout is fan-out and gather, and says so.
 *
 * **A decline is displayed as prominently as a position.** "This falls outside my record"
 * is the escape hatch working, and it is the answer that distinguishes "X held this" from
 * "a model impersonating X generated this". Styling it as a gap would hide the single most
 * informative thing a grounded persona can say.
 */

import { useMemo, useState } from 'react'

import { citationsByPersona, usePassages, type Passages } from '../lib/usePassages'
import type { RunRecord, TheoristOpinion } from '../types/artsoc'

export default function PanelResponses({ record }: { record: RunRecord }) {
  const [openQuestion, setOpenQuestion] = useState<string | null>(
    record.questions?.[0]?.question_id ?? null,
  )

  const grouped = useMemo(() => citationsByPersona(record.opinions ?? []), [record])
  const passages = usePassages(grouped)

  const questions = record.questions ?? []
  const routing = record.routing ?? []
  const opinions = record.opinions ?? []

  if (questions.length === 0) {
    return (
      <section className="panel">
        <header>
          <h2>Panel responses</h2>
        </header>
        <div className="banner info" style={{ marginBottom: 0 }}>
          <strong>NO PANEL IN THIS ARM</strong>
          This replication ran the President and the intelligence brief alone. That is what
          makes it the control, so there is no exchange to read — not missing data.
        </div>
      </section>
    )
  }

  return (
    <section className="panel">
      <header>
        <h2>Panel responses</h2>
        <p className="subtitle">
          What the Advisor asked, whom it chose and why, and what each theorist said back.
          An exchange, not a conversation: each theorist is asked once and answers once, and
          none of them can see another&rsquo;s answer — peer visibility would make apparent
          consensus an artifact of call ordering.
        </p>
      </header>

      {questions.map((question) => {
        const record_ = routing.find((r) => r.question_id === question.question_id)
        const answers = opinions.filter((o) => o.question_id === question.question_id)
        const open = openQuestion === question.question_id
        const declined = answers.filter((a) => a.out_of_record).length

        return (
          <div key={question.question_id} className="qblock">
            <button
              className="qhead"
              onClick={() => setOpenQuestion(open ? null : question.question_id)}
              aria-expanded={open}
            >
              <span className="qtoggle">{open ? '▾' : '▸'}</span>
              <span className="qid mono">{question.question_id}</span>
              <span className="qtext">{question.text}</span>
              <span className="qcount faint">
                {answers.length - declined} answered · {declined} declined
              </span>
            </button>

            {open && (
              <div className="qbody">
                <div className="tags">
                  {(question.tags ?? []).map((tag) => (
                    <span key={tag} className="pill">
                      {tag}
                    </span>
                  ))}
                </div>

                {record_ && <Selection routing={record_} />}

                {answers.length === 0 ? (
                  <p className="empty">No opinions recorded for this question.</p>
                ) : (
                  answers.map((answer) => (
                    <Answer
                      key={`${answer.persona_id}-${answer.question_id}`}
                      opinion={answer}
                      passages={passages}
                    />
                  ))
                )}
              </div>
            )}
          </div>
        )
      })}
    </section>
  )
}

/** Whom the Advisor picked, how, and the reason it gave. */
function Selection({ routing }: { routing: NonNullable<RunRecord['routing']>[number] }) {
  const bySource: [string, string[], string][] = [
    ['chosen by the Advisor', routing.chosen_by_advisor ?? [], 'someone judged them relevant'],
    ['matched by tag', routing.matched_by_tag ?? [], 'deterministic overlap, no model involved'],
    ['topped up', routing.topped_up ?? [], 'added to reach k; nobody judged them relevant'],
  ]

  return (
    <div className="selection">
      <h4>Advisor&rsquo;s selection</h4>
      <div className="row small" style={{ gap: '1.25rem' }}>
        {bySource
          .filter(([, ids]) => ids.length > 0)
          .map(([label, ids, why]) => (
            <span key={label} title={why}>
              <span className="faint">{label}:</span> <span className="mono">{ids.join(', ')}</span>
            </span>
          ))}
        <span className="faint">
          from a roster of {(routing.roster ?? []).length}
        </span>
      </div>

      {routing.rationale && <p className="rationale">{routing.rationale}</p>}

      {(routing.hallucinated ?? []).length > 0 && (
        <p className="small" style={{ color: 'var(--warn)' }}>
          The Advisor also named {routing.hallucinated!.join(', ')}, who were not on the
          roster. Dropped, never honoured — the rate is a finding about how reliably a model
          routes.
        </p>
      )}
    </div>
  )
}

/** One theorist's answer, read as prose. */
function Answer({ opinion, passages }: { opinion: TheoristOpinion; passages: Passages }) {
  const [showSources, setShowSources] = useState(false)
  const citations = opinion.citations ?? []

  return (
    <article className={`answer ${opinion.out_of_record ? 'declined' : 'stated'}`}>
      <div className="row" style={{ gap: '0.5rem' }}>
        <strong>{opinion.persona_name}</strong>
        {opinion.out_of_record ? (
          <span className="pill declined">declined — outside their record</span>
        ) : (
          <span className="pill stated">stated a position</span>
        )}
        <span className="faint small">
          basis: {opinion.basis} · confidence {opinion.confidence?.toFixed(2)} · method{' '}
          {opinion.method}
        </span>
      </div>

      {opinion.position && (
        <>
          <h5>{opinion.out_of_record ? 'What they said instead' : 'Position'}</h5>
          <p>{opinion.position}</p>
        </>
      )}

      {opinion.reasoning && (
        <>
          <h5>Reasoning</h5>
          <p className="muted">{opinion.reasoning}</p>
        </>
      )}

      {citations.length > 0 && (
        <div className="citations">
          <button className="ghost small" onClick={() => setShowSources(!showSources)}>
            {showSources ? 'Hide' : 'Show'} the {citations.length} passage
            {citations.length === 1 ? '' : 's'} they cited
          </button>

          {showSources && (
            <div className="passages">
              {citations.map((id) => {
                const passage = passages.byId.get(id)
                if (!passage) {
                  return (
                    <div key={id} className="passage unresolved">
                      <div className="mono small">{id}</div>
                      <p className="small">
                        {passages.loading
                          ? 'Looking this up…'
                          : 'This id is not in the store. The persona attributed a claim to a ' +
                            'passage it was not shown — reported, never corrected, because the ' +
                            'rate is a finding about the method.'}
                      </p>
                    </div>
                  )
                }
                return (
                  <div key={id} className="passage">
                    <div className="small faint">
                      <span className="pill">{passage.source}</span> {passage.section}
                    </div>
                    <p className="small">{passage.text}</p>
                    <div className="mono faint" style={{ fontSize: '0.7rem' }}>
                      {id}
                    </div>
                  </div>
                )
              })}
              <p className="faint small">
                Wikipedia passages are a <strong>tertiary</strong> source — an encyclopedia
                article about the theorist, not the theorist&rsquo;s own writing. Beliefs are
                generated from that persona&rsquo;s own fetched sources and are used only when
                the corpus does not cover the question.
              </p>
            </div>
          )}
        </div>
      )}
    </article>
  )
}
