/**
 * A written reading of the figures on this page, and follow-up questions about them.
 *
 * **Interpretation, never a finding.** The distribution above is the result; this is prose
 * about it and adds nothing. The model is given summary statistics only — no record, no
 * prompt, and no `host_ground_truth` — and its instructions repeat the constraints the page
 * does: only the delta against the control is interpretable, course-of-action support is
 * not influence, and the President's justification is the reason it gave rather than the
 * cause.
 *
 * **Each distinct question is a billed call.** Asking the same one again, in any
 * capitalisation, is served from disk. The UI says so before anyone types.
 */

import { useState } from 'react'

import { api } from '../api/client'
import type { AnalysisAnswer, SessionAnalysis } from '../types/artsoc'

interface Props {
  sessionId: string
  arm: string
  initial: SessionAnalysis | null
  mock: boolean
}

export default function AnalysisPanel({ sessionId, arm, initial, mock }: Props) {
  const [analysis, setAnalysis] = useState<SessionAnalysis | null>(initial)
  const [answers, setAnswers] = useState<AnalysisAnswer[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState<'analysis' | 'question' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const generate = async (regenerate = false) => {
    setBusy('analysis')
    setError(null)
    try {
      setAnalysis(await api.analysis(sessionId, arm, regenerate))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const ask = async () => {
    if (!question.trim()) return
    setBusy('question')
    setError(null)
    try {
      const answer = await api.ask(sessionId, question, arm)
      if (answer) setAnswers([answer, ...answers])
      setQuestion('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="section">
      <header>
        <h2>Interpretation</h2>
        <p className="subtitle">
          A reading of the figures on this page. It is given the summary statistics and the
          diagnostics — never a transcript, a prompt, or what was actually happening in the
          world — and it adds nothing to the numbers it describes.
        </p>
      </header>

      {mock && (
        <div className="notice warn">
          <strong>Nothing here to interpret</strong>
          This session ran on the mock backend, whose output is content-nonsense by design. A
          reading of it would be a reading of noise.
        </div>
      )}

      {error && (
        <div className="notice stop">
          <strong>Request failed</strong>
          {error}
        </div>
      )}

      {analysis && (analysis.sentences ?? []).length > 0 ? (
        <>
          <p className="lede">{(analysis.sentences ?? []).join(' ')}</p>
          <p className="lede-source">{analysis.caveat}</p>
          <button className="ghost small" onClick={() => void generate(true)} disabled={busy !== null}>
            {busy === 'analysis' ? 'Re-reading…' : 'Generate again'}
          </button>
        </>
      ) : (
        <div>
          <button onClick={() => void generate()} disabled={busy !== null}>
            {busy === 'analysis' ? 'Reading the figures…' : 'Read these figures'}
          </button>
          <p className="faint tiny" style={{ marginTop: '0.5rem' }}>
            One model call, cached afterwards, so revisiting this page costs nothing and shows
            the same text.
          </p>
        </div>
      )}

      <div style={{ marginTop: '2rem' }}>
        <h4>Ask about these results</h4>
        <div style={{ maxWidth: '68ch' }}>
          <textarea
            value={question}
            placeholder="e.g. Did suppressing minority positions change where the decisions landed?"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void ask()
            }}
          />
          <div className="row" style={{ marginTop: '0.6rem' }}>
            <button onClick={() => void ask()} disabled={busy !== null || !question.trim()}>
              {busy === 'question' ? 'Reading…' : 'Ask'}
            </button>
            <span className="faint tiny">
              Each new question is one billed model call. The same question asked again is
              served from disk and costs nothing. Answers come from the figures on this page
              only — a question they cannot answer gets said so, not guessed at.
            </span>
          </div>
        </div>

        {answers.length > 0 && (
          <div className="qa" style={{ marginTop: '1.5rem' }}>
            {answers.map((answer) => (
              <div className="qa-item" key={answer.question}>
                <div className="q">{answer.question}</div>
                <div className="a">{answer.answer || 'No answer came back.'}</div>
              </div>
            ))}
            <p className="faint tiny">{answers[0]?.caveat}</p>
          </div>
        )}
      </div>
    </section>
  )
}
